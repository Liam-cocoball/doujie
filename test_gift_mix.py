"""Exercise automatic microphone allocation through real stage acknowledgements."""
from collections import Counter
from itertools import count
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from server import Scheduler, validate


class GiftAndWelcomeMixTest(TestCase):
    def setUp(self):
        self.studio = Scheduler()
        self.addCleanup(self.studio.close)
        self.studio.dialogue.configure("", None)
        self.ids = count(1)

    def send(self, *kinds, prompt="嘿嘿"):
        rows = []
        for kind in kinds:
            n = str(next(self.ids))
            data = {"content": prompt} if kind == "comment" else {"giftName": "玫瑰"} if kind == "gift" else {}
            rows.append({"type": kind, "roomId": "mix", "eventId": n, "actor": {"nickname": "听众" + n}, "data": data})
        self.studio.ingest(validate(rows))
        return rows

    def active(self):
        with self.studio.cv:
            self.assertTrue(self.studio.cv.wait_for(lambda: self.studio.active is not None, timeout=2))
            return self.studio.state(stage=True)["active"]

    def ack(self, cue, phase, player="stage-a", **fields):
        return self.studio.playback({"id": cue["id"], "phase": phase, "player": player, **fields})

    def finish(self, cue):
        self.assertTrue(self.ack(cue, "start"))
        for index in range(len(cue["segments"])):
            self.assertTrue(self.ack(cue, "segment", index=index))
            self.assertTrue(self.ack(cue, "segment_end", index=index))
        self.assertTrue(self.ack(cue, "complete"))

    def stock_both(self):
        pending = {cue["source"] for cue in self.studio.state()["queue"]}
        missing = [kind for kind in ("comment", "room_join") if kind not in pending]
        if missing:
            self.send(*missing)

    def test_two_full_rounds_with_both_ready_and_retried_claims(self):
        self.studio.control({"action": "manual", "text": "试麦。"})
        opener = self.active()
        self.stock_both()
        self.finish(opener)
        turns = []
        for _ in range(24):
            cue = self.active()
            self.assertTrue(self.ack(cue, "start"))
            self.assertTrue(self.ack(cue, "start"))  # Retry after a lost acknowledgement.
            self.assertFalse(self.ack(cue, "start", player="stage-b"))
            self.stock_both()
            self.finish(cue)
            if cue["source"] in ("comment", "room_join"):
                turns.append(cue["source"])
            if len(turns) == 20:
                break
        expected = {"comment": 7, "room_join": 3}
        self.assertEqual(Counter(turns[:10]), expected)
        self.assertEqual(Counter(turns[10:]), expected)

    def test_only_one_lane_available_uses_the_mic_each_time(self):
        for kind in ("room_join", "comment"):
            with self.subTest(kind=kind):
                for i in range(10):
                    event, = self.send(kind, prompt="怎么提加薪？")
                    cue = self.active()
                    self.assertEqual((cue["source"], cue.get("eventId")), (kind, event["eventId"]))
                    self.finish(cue)

    def test_gift_preempts_unclaimed_comment_and_welcome_without_losing_them(self):
        for kind in ("comment", "room_join"):
            with self.subTest(kind=kind):
                original, = self.send(kind)
                unclaimed = self.active()
                self.send("gift")
                gift = self.active()
                self.assertEqual(gift["source"], "gift")
                self.assertFalse(self.ack(unclaimed, "start", player="late-stage"))
                self.finish(gift)
                resumed = self.active()
                self.assertEqual((resumed["source"], resumed["eventId"]), (kind, original["eventId"]))
                self.finish(resumed)

    def test_gift_waits_for_the_sentence_on_air_then_goes_before_both_queues(self):
        self.send("comment")
        current = self.active()
        self.assertTrue(self.ack(current, "start"))
        self.assertTrue(self.ack(current, "segment", index=0))
        self.stock_both()
        self.send("gift")
        self.assertEqual(self.active()["id"], current["id"])
        self.finish(current)
        gift = self.active()
        self.assertEqual(gift["source"], "gift")
        self.finish(gift)

    def test_available_welcome_and_gift_do_not_wait_for_slow_comment_model(self):
        began, release = Event(), Event()

        def slow(*args):
            began.set()
            release.wait(4)
            return [{"text": "加班费得写进明细。", "expression": "smirk", "gesture": "nod"}], "deepseek"

        with patch.object(self.studio.dialogue, "plan", side_effect=slow):
            try:
                self.send("comment", prompt="加班费该怎么和老板谈？")
                self.assertTrue(began.wait(2))
                self.send("room_join")
                welcome = self.active()
                self.assertEqual(welcome["source"], "room_join")
                self.assertTrue(self.ack(welcome, "start"))
                self.send("gift")
                self.finish(welcome)
                gift = self.active()
                self.assertEqual(gift["source"], "gift")
                self.finish(gift)
            finally:
                release.set()
            comment = self.active()
            self.assertEqual(comment["source"], "comment")
            self.finish(comment)
