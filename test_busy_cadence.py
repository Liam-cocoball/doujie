from itertools import count
import time
from unittest import TestCase
from unittest.mock import patch

from server import Scheduler, validate


class BusyCadenceTest(TestCase):
    def setUp(self):
        clock = patch("server.time", wraps=time)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.second = 0
        self.clock.monotonic.side_effect = lambda: 1000 + self.second
        self.clock.time.side_effect = lambda: 1900000000 + self.second
        self.studio = Scheduler()
        self.studio.dialogue.configure("", None)
        self.addCleanup(self.studio.close)
        self.ids = count(1)

    def event(self, prompt="", kind="comment", room="test"):
        n = next(self.ids)
        return {"roomId": room, "eventId": str(n), "type": kind, "actor": {"nickname": f"观众{n}"},
                "data": {"content": prompt} if kind == "comment" else {"giftName": "玫瑰"}}

    def send(self, *rows):
        self.studio.ingest(validate(list(rows)))

    def drain(self):
        """Let the scheduler and stage finish work eligible at the current simulated instant."""
        played = []
        while True:
            with self.studio.cv:
                def settled():
                    return self.studio.active or all(t["_readyAt"] > 1000 + self.second for t in self.studio.queue)
                self.assertTrue(self.studio.cv.wait_for(settled, 2))
                cue = self.studio.state(stage=True)["active"]
            if not cue:
                return played
            def ack(phase, **fields):
                self.assertTrue(self.studio.playback({"player": "test-stage", "id": cue["id"],
                                                      "phase": phase, **fields}))
            ack("start")
            for i in range(len(cue["segments"])):
                ack("segment", index=i)
                ack("segment_end", index=i)
            ack("complete")
            played.append(cue)

    def test_minute_of_chat_makes_repeated_invites_and_still_answers_recent_questions(self):
        transcript = []
        newest = {}
        for self.second in range(61):
            if 14 <= self.second <= 24 or 37 <= self.second <= 49:
                prompt = "我的加班费要怎么谈？"
            else:
                prompt = "哈哈" if self.second % 2 == 0 else "玄紫青"
            winner = self.event(prompt)
            newest[self.second] = winner
            rows = [self.event("嘿嘿") for _ in range(3)] + [winner]
            if self.second == 30:
                rows.append(self.event(kind="gift"))
            self.send(*rows)
            transcript.extend((self.second, cue) for cue in self.drain())

        invites = [(s, cue) for s, cue in transcript if cue.get("giftInvite")]
        self.assertGreaterEqual(len(invites), 3)
        self.assertTrue(all(b - a >= 25 for (a, _), (b, _) in zip(invites, invites[1:])))
        standalone = [(s, cue) for s, cue in invites if cue["source"] == "gift_invite"]
        self.assertTrue(standalone)
        for _, cue in standalone:
            self.assertFalse(cue.get("replyTarget"))
            self.assertFalse(cue.get("name"))
            self.assertEqual(cue["giftInvite"], cue["text"])
        answers = [(s, cue) for s, cue in transcript if cue["source"] == "comment"]
        self.assertTrue(any("加班费" in cue["prompt"] for _, cue in answers))
        self.assertTrue(all(any(s == second for s, _ in answers)
                            for second in (*range(14, 25), *range(37, 50))),
                        "an idle microphone can answer successive substantive questions")
        for second, cue in answers:
            self.assertEqual(cue["eventId"], newest[second]["eventId"])
        self.assertEqual([s for s, cue in transcript if cue["source"] == "gift"], [30])

        # The audience-wide appeal never consumes the viewer's right to a directed reply.
        skipped = newest[standalone[0][0]]
        self.studio.control({"action": "reply", "roomId": skipped["roomId"], "eventId": skipped["eventId"]})
        picked, = self.drain()
        self.assertEqual((picked["source"], picked["eventId"]), ("comment", skipped["eventId"]))
        self.assertNotIn("giftInvite", picked)
        self.second += 8
        quiet = self.event("早呀")
        self.send(quiet)
        normal, = self.drain()
        self.assertEqual((normal["source"], normal["eventId"]), ("comment", quiet["eventId"]))
        self.assertNotIn("giftInvite", normal)

    def test_arrival_rate_triggers_an_appeal_even_when_queue_drains_between_events(self):
        for self.second in range(3):
            self.send(self.event("哈哈"))
            ordinary, = self.drain()
            self.assertEqual(ordinary["source"], "comment")
            self.assertNotIn("giftInvite", ordinary)
        self.second += 1
        self.send(self.event("嘿嘿"))
        invite, = self.drain()
        self.assertEqual(invite["source"], "gift_invite")
        self.assertTrue(invite["giftInvite"])
        self.send(self.event("你好", room="quiet-room"))
        quiet, = self.drain()
        self.assertEqual(quiet["source"], "comment")
        self.assertNotIn("giftInvite", quiet)
