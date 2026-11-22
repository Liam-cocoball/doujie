"""Drive the broadcast scheduler with collectors and a stage, using a disposable studio."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch
from uuid import UUID

from server import Scheduler, validate


class CommentPressureTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "studio.sqlite3"
        self.epoch = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.open_studio()

    def open_studio(self):
        self.studio = Scheduler(data_path=self.path)
        self.studio.dialogue.configure("", None)
        self.addCleanup(self.studio.close)

    def event(self, number, *, kind="comment", text="加薪怎么开口？", stamp=None, room="123"):
        when = self.epoch + timedelta(milliseconds=number if stamp is None else stamp)
        data = {"comment": {"content": text}, "gift": {"giftName": "玫瑰"}, "like": {"displayCount": 1}}[kind]
        return {"eventId": str(UUID(int=number)), "roomId": room, "type": kind,
                "actor": {"nickname": f"观众{number}"}, "capturedAt": when.isoformat(),
                "rawText": "", "data": data}

    def ingest(self, *events):
        self.studio.ingest(validate({"schemaVersion": 1, "events": list(events)}))

    def active(self):
        with self.studio.cv:
            self.assertTrue(self.studio.cv.wait_for(lambda: self.studio.active is not None, 2))
            return self.studio.state()["active"]

    def ack(self, cue, phase, **fields):
        self.assertTrue(self.studio.playback({"player": "test-stage", "id": cue["id"], "phase": phase, **fields}))

    def finish(self, cue):
        self.ack(cue, "start")
        for index in range(len(cue["segments"])):
            self.ack(cue, "segment", index=index)
            self.ack(cue, "segment_end", index=index)
        self.ack(cue, "complete")

    def select(self, row):
        self.studio.control({"action": "reply", "roomId": row["roomId"], "eventId": row["eventId"]})

    def test_fast_comment_rate_is_detected_with_an_empty_queue_and_does_not_spill_into_other_rooms(self):
        with patch("server.time", wraps=time) as clock:
            clock.monotonic.return_value = 1000
            for number in (1, 2, 3):
                clock.monotonic.return_value += 2
                row = self.event(number)
                self.ingest(row, row, self.event(40 + number, text=" "))
                self.finish(self.active())
            self.assertFalse(self.studio._room_busy("123", clock.monotonic()))
            self.studio.control({"action": "manual", "text": "开场。"})
            self.active()
            self.ingest(self.event(9, kind="like", room="222"), self.event(10, room="222"))
            clock.monotonic.return_value += 2
            self.ingest(self.event(11), self.event(12, kind="like"))
            self.assertTrue(self.studio._room_busy("123", clock.monotonic()))
            self.assertFalse(self.studio._room_busy("222", clock.monotonic()))
            queue = self.studio.state()["queue"]
            self.assertCountEqual([(c["roomId"], c["source"]) for c in queue],
                                  [("222", "like"), ("222", "comment"), ("123", "comment")])
            self.assertEqual(self.studio.state()["recent"][0]["status"], "superseded")
            self.assertFalse(self.studio._room_busy("123", clock.monotonic() + 6))

    def test_latest_question_can_outlast_a_laugh_for_only_two_seconds(self):
        self.studio.control({"action": "manual", "text": "开场。"})
        self.active()
        with patch("server.time", wraps=time) as clock:
            clock.monotonic.return_value = 1000
            self.ingest(*(self.event(n) for n in (1, 2, 3)), self.event(4, text="哈哈"))
            self.assertEqual(self.studio.state()["queue"][0]["eventId"], self.event(3)["eventId"])
            self.ingest(self.event(5), self.event(6, text="嘿嘿"))
            self.assertEqual(self.studio.state()["queue"][0]["eventId"], self.event(5)["eventId"])
            clock.monotonic.return_value += 2.1
            self.ingest(self.event(7, text="嘿嘿"))
            self.assertEqual(self.studio.state()["queue"][0]["eventId"], self.event(7)["eventId"])
            self.ingest(self.event(8, stamp=4))
            self.assertEqual(self.studio.state()["queue"][0]["eventId"], self.event(7)["eventId"])

    def test_ordinary_traffic_and_quiet_recovery_keep_capture_order(self):
        with patch("server.COMMENT_BURST_GAP", .04):
            ordinary = [self.event(n) for n in (1, 2, 3)]
            self.ingest(*reversed(ordinary))
            for row in ordinary:
                cue = self.active()
                self.assertEqual(cue["eventId"], row["eventId"])
                self.finish(cue)
            burst = [self.event(n) for n in (4, 5, 6, 7)]
            self.ingest(*burst)
            newest = self.active()
            self.assertEqual(newest["eventId"], burst[-1]["eventId"])
            self.finish(newest)
            time.sleep(.06)
            ordinary = [self.event(n) for n in (8, 9)]
            self.ingest(*reversed(ordinary))
            for row in ordinary:
                cue = self.active()
                self.assertEqual(cue["eventId"], row["eventId"])
                self.finish(cue)

    def test_concurrent_collectors_keep_latest_protect_playback_and_archive_skips(self):
        first = self.event(1)
        self.ingest(first)
        playing = self.active()
        self.ack(playing, "start")
        self.ack(playing, "segment", index=0)

        chosen = self.event(2, text="哈哈")
        self.ingest(chosen)
        self.select(chosen)
        self.ingest(self.event(3, kind="gift"))
        self.studio.control({"action": "submit", "text": "哈哈", "name": "导播"})
        burst = [self.event(n) for n in range(4, 94)]
        with ThreadPoolExecutor(max_workers=4) as collectors:
            list(collectors.map(self.ingest, reversed(burst)))
        # A later arrival with the same capture time wins, a delayed older event cannot displace it.
        newest = self.event(94, stamp=93)
        self.ingest(newest)
        self.ingest(self.event(95, stamp=50), newest)
        state = self.studio.state()
        self.assertEqual((state["active"]["id"], state["active"]["status"]), (playing["id"], "playing"))
        self.assertCountEqual([cue["source"] for cue in state["queue"]], ["topic", "gift", "comment", "comment"])
        self.assertCountEqual([cue["eventId"] for cue in state["queue"] if cue["source"] == "comment"],
                              [chosen["eventId"], newest["eventId"]])
        self.ack(playing, "segment_end", index=0)
        self.ack(playing, "complete")
        for expected, comment in (("comment", chosen), ("topic", None), ("gift", None), ("comment", newest)):
            cue = self.active()
            self.assertEqual(cue["source"], expected)
            if comment:
                self.assertEqual(cue["eventId"], comment["eventId"])
            self.finish(cue)
        self.assertEqual(self.studio.state()["queueDepth"], 0)
        self.studio.close()
        self.open_studio()
        events = self.studio.archive("events", limit=100)["items"]
        by_id = {row["eventId"]: row["status"] for row in events}
        self.assertEqual(len(events), 96)  # 95 collector events plus the director's topic
        self.assertEqual(by_id[newest["eventId"]], "played")
        self.assertTrue(all(by_id[row["eventId"]] == "superseded" for row in burst))
        self.assertEqual(by_id[str(UUID(int=95))], "superseded")
        # Even a skipped comment outside the 60-entry recent list can still be hand-picked once.
        recent_ids = {row["eventId"] for row in self.studio.state()["recent"]}
        old = next(row for row in events if row["status"] == "superseded" and row["eventId"] not in recent_ids)
        self.select(old)
        self.select(old)
        cue = self.active()
        self.assertEqual(cue["eventId"], old["eventId"])
        self.finish(cue)
        self.assertEqual(self.studio.state()["queueDepth"], 0)

    def test_result_from_replaced_planner_cannot_resurface_or_block_fresh_reply(self):
        began, release = Event(), Event()

        def slow_plan(*args):
            began.set()
            release.wait(4)
            return [{"text": "这句已经过时。", "gesture": "nod", "expression": "neutral"}], "deepseek"

        stale = self.event(1, text="怎样准备下周的面试？")
        burst = [self.event(n, text=f"准备第{n}次谈加薪，怎么开口？") for n in (2, 3, 4)]
        with patch.object(self.studio.dialogue, "plan", side_effect=slow_plan):
            try:
                self.ingest(stale)
                self.assertTrue(began.wait(2))
                self.ingest(*burst)
                cue = self.active()
                self.assertEqual(cue["eventId"], burst[-1]["eventId"])
                self.finish(cue)
                # While that flood is fresh, even an empty mic must not revive delayed old events.
                self.ingest(self.event(5, stamp=1))
            finally:
                release.set()
            with self.studio.cv:
                self.assertTrue(self.studio.cv.wait_for(lambda: self.studio.planning is None, 2))
        state = self.studio.state()
        self.assertEqual((state["active"], state["queueDepth"]), (None, 0))
        self.assertEqual([row["id"] for row in state["history"]], [cue["id"]])
        self.assertEqual({row["status"] for row in state["recent"] if row["eventId"] != cue["eventId"]},
                         {"superseded"})

    def test_comment_burst_retires_merged_likes_and_does_not_replay_them_after_quiet(self):
        with patch("server.COMMENT_BURST_GAP", .15):
            self.ingest(self.event(1))
            holding = self.active()
            self.ingest(self.event(2, kind="like"), self.event(3, kind="like"))
            self.assertEqual([cue["source"] for cue in self.studio.state()["queue"]], ["like"])
            in_burst = self.event(8, kind="like")
            in_burst["data"]["displayCount"] = 200
            self.ingest(*(self.event(n) for n in (4, 5, 6, 7)), in_burst)
            self.assertEqual([cue["source"] for cue in self.studio.state()["queue"]], ["comment"])
            self.finish(holding)
            self.finish(self.active())
            rows = self.studio.archive("events")["items"]
            likes = [r for r in rows if r["type"] == "like"]
            self.assertEqual([r["status"] for r in likes], ["superseded"] * 3)
            self.assertIsNone(likes[0]["cueId"])
            self.assertEqual(likes[0]["displayCount"], 200)
            time.sleep(.18)
            fresh = self.event(9, kind="like")
            self.ingest(fresh)
            cue = self.active()
            self.assertEqual((cue["source"], cue["name"]), ("like", "观众9"))
            self.finish(cue)
        self.assertEqual([row["name"] for row in self.studio.state()["history"] if row["source"] == "like"],
                         ["观众9"])
        self.assertEqual(self.studio.state()["queueDepth"], 0)

    def test_comment_burst_does_not_interrupt_a_like_already_playing(self):
        self.ingest(self.event(1, kind="like"))
        speaking = self.active()
        self.ack(speaking, "start")
        self.ack(speaking, "segment", index=0)
        self.ingest(*(self.event(n) for n in (2, 3, 4, 5)), self.event(6, kind="like"))
        state = self.studio.state()
        self.assertEqual((state["active"]["id"], state["active"]["status"]), (speaking["id"], "playing"))
        self.assertEqual([(t["source"], t.get("eventId")) for t in state["queue"]],
                         [("comment", self.event(5)["eventId"])])
        self.ack(speaking, "segment_end", index=0)
        self.ack(speaking, "complete")
        self.finish(self.active())
        likes = [r for r in self.studio.archive("events")["items"] if r["type"] == "like"]
        self.assertEqual([r["status"] for r in likes], ["superseded", "played"])

    def test_comment_burst_releases_unclaimed_like_and_rejects_late_stage_claim(self):
        self.ingest(self.event(1, kind="like"))
        unclaimed = self.active()
        self.assertEqual((unclaimed["source"], unclaimed["status"]), ("like", "ready"))
        self.ingest(*(self.event(n) for n in (2, 3, 4, 5)))
        self.assertFalse(self.studio.playback({"player": "late-stage", "id": unclaimed["id"], "phase": "start"}))
        comment = self.active()
        self.assertEqual(comment["eventId"], self.event(5)["eventId"])
        self.finish(comment)
        state = self.studio.state()
        self.assertEqual([r["status"] for r in state["recent"] if r["type"] == "like"], ["superseded"])
        self.assertEqual([r["source"] for r in state["history"]], ["comment"])
