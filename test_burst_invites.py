import itertools
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import patch

from server import Scheduler, validate


class BurstGiftInviteTest(TestCase):
    def setUp(self):
        clock = patch("server.time", wraps=time)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.monotonic.return_value = 1000
        wall_start = time.time()
        self.clock.time.side_effect = lambda: wall_start + (self.clock.monotonic.return_value - 1000)
        self.ids = itertools.count(1)
        self.open_studio()

    def open_studio(self, path=None):
        self.studio = Scheduler(data_path=path)
        self.addCleanup(self.studio.close)
        self.studio.dialogue.configure("", None)

    def event(self, text="", room="A", kind="comment"):
        number = next(self.ids)
        data = {"content": text} if kind == "comment" else {"giftName": "玫瑰"} if kind == "gift" else {}
        return {"roomId": room, "eventId": str(number), "type": kind, "actor": {"nickname": f"观众{number}"},
                "data": data}

    def ingest(self, *rows):
        self.studio.ingest(validate(list(rows)))

    def burst(self, last):
        self.ingest(*(self.event(text, last["roomId"]) for text in ("头一条", "第二条", "第三条")), last)

    def active(self, kind="comment"):
        with self.studio.cv:
            self.assertTrue(self.studio.cv.wait_for(lambda: self.studio.active is not None, 2))
            cue = self.studio.state(stage=True)["active"]
        self.assertEqual(cue["source"], kind)
        return cue

    def finish(self, cue):
        def ack(phase, **fields):
            self.assertTrue(self.studio.playback({"id": cue["id"], "player": "test-stage", "phase": phase, **fields}))
        ack("start")
        for index in range(len(cue["segments"])):
            ack("segment", index=index)
            ack("segment_end", index=index)
        ack("complete")

    def check_invite(self, cue):
        invite = cue.get("giftInvite")
        self.assertIsInstance(invite, str)
        self.assertTrue(invite.strip())
        self.assertEqual(len(cue["segments"]), 1)
        self.assertEqual(cue["segments"][0]["text"].count(invite), 1)
        self.assertTrue(cue["text"].replace(invite, "").strip())

    def test_only_current_burst_winners_air_invites_with_per_room_cooldowns(self):
        self.ingest(self.event("红围巾是什么颜色？"))
        calm = self.active()
        self.assertNotIn("giftInvite", calm)
        self.finish(calm)
        first = self.event("加薪怎么开口？")
        self.burst(first)
        cue = self.active()
        self.assertEqual(cue["eventId"], first["eventId"])
        self.check_invite(cue)
        self.finish(cue)

        self.burst(self.event("怎么谈加薪？", room="B"))
        other = self.active()
        self.check_invite(other)
        self.finish(other)
        self.clock.monotonic.return_value += 24
        self.burst(self.event("天天加班怎么办？"))
        early = self.active()
        self.assertNotIn("giftInvite", early)
        self.finish(early)
        self.clock.monotonic.return_value += 1
        self.ingest(self.event("工资怎么谈？"))
        eligible = self.active("comment")
        self.check_invite(eligible)
        self.finish(eligible)
        self.clock.monotonic.return_value += 26
        self.ingest(self.event("朋友又迟到了？"))
        quiet = self.active()
        self.assertNotIn("giftInvite", quiet)
        self.finish(quiet)

    def test_directed_and_gift_related_turns_leave_the_invite_for_audience_chat(self):
        self.studio.control({"action": "manual", "text": "开场试麦。"})
        opener = self.active("manual")
        chosen = self.event("怎么提加薪？")
        gift_topic = self.event("给你送朵玫瑰。怎么跟老板谈加薪？")
        self.ingest(chosen, self.event("第二条"), self.event("第三条"), gift_topic)
        self.studio.control({"action": "reply", "eventId": chosen["eventId"], "roomId": chosen["roomId"]})
        self.studio.control({"action": "manual", "text": "导播原话。"})
        self.ingest(self.event(kind="gift"), self.event(kind="room_join"))
        self.finish(opener)
        for kind in ("manual", "comment", "gift", "comment", "room_join"):
            cue = self.active(kind)
            self.assertNotIn("giftInvite", cue)
            if kind == "manual":
                self.assertEqual(cue["text"], "导播原话。")
            self.finish(cue)
        archived = self.studio.archive("events")["items"]
        self.assertEqual(next(r["status"] for r in archived if r["eventId"] == gift_topic["eventId"]), "played")
        # Respect a freshly thanked donor for the same interval as an invitation.
        self.clock.monotonic.return_value += 25
        self.burst(self.event("遇到甩锅怎么办？"))
        unclaimed = self.active()
        self.check_invite(unclaimed)
        self.studio.control({"action": "skip", "id": unclaimed["id"]})
        self.ingest(self.event("开会迟到怎么办？"))
        next_reply = self.active()
        self.check_invite(next_reply)
        self.finish(next_reply)

    def test_only_heard_invites_restore_cooldown_on_restart(self):
        self.studio.close()
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "invite-test.sqlite3"
        self.open_studio(path)
        self.burst(self.event("今天开会怎么收尾？"))
        first = self.active()
        self.check_invite(first)
        self.finish(first)
        self.studio.close()
        self.clock.monotonic.return_value += 1
        self.open_studio(path)
        self.burst(self.event("同事迟到怎么办？"))
        early = self.active()
        self.assertNotIn("giftInvite", early)
        self.finish(early)
        self.clock.monotonic.return_value += 26
        self.burst(self.event("开会跑题了怎么办？"))
        self.check_invite(self.active())
        self.studio.close()  # This cue was never claimed or heard.
        self.open_studio(path)
        self.burst(self.event("朋友放鸽子怎么办？"))
        after_restart = self.active()
        self.check_invite(after_restart)
        self.finish(after_restart)

    def test_a_real_gift_replaces_an_unclaimed_room_invite(self):
        self.burst(self.event("哈哈"))
        first = self.active("gift_invite")
        self.ingest(self.event(kind="gift"))
        gift = self.active("gift")
        self.assertFalse(self.studio.playback({"player": "late-stage", "phase": "start", "id": first["id"]}))
        self.finish(gift)
        self.assertFalse(any(r.get("giftInvite") for r in self.studio.archive("history")["items"]))

    def test_unclaimed_room_invite_expires_when_the_room_falls_quiet(self):
        self.burst(self.event("哈哈"))
        first = self.active("gift_invite")
        self.clock.monotonic.return_value += 7
        self.assertFalse(self.studio.playback({"player": "late-stage", "phase": "start", "id": first["id"]}))
        self.ingest(self.event("嘿嘿"))
        calm = self.active("comment")
        self.assertNotIn("giftInvite", calm)
        self.finish(calm)
