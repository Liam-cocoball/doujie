from itertools import count
from unittest import TestCase
from unittest.mock import patch

from server import Scheduler, validate


class RepeatedBroadcastTest(TestCase):
    def setUp(self):
        self.studio = Scheduler()
        self.studio.dialogue.configure("", None)
        self.addCleanup(self.studio.close)
        self.ids = count(1)

    def send(self, *prompts):
        rows = []
        for prompt in prompts:
            event_id = str(next(self.ids))
            rows.append({"roomId": "test", "eventId": event_id, "type": "comment",
                         "actor": {"nickname": event_id}, "data": {"content": prompt}})
        self.studio.ingest(validate(rows))
        return rows[-1]["eventId"]

    def air(self):
        with self.studio.cv:
            self.assertTrue(self.studio.cv.wait_for(lambda: self.studio.active is not None, 2))
            cue = self.studio.state(stage=True)["active"]
        for phase in ("start", "segment", "complete"):
            self.assertTrue(self.studio.playback({"id": cue["id"], "player": "test", "phase": phase, "index": 0}))
        return cue

    def test_three_prepared_reactions_choose_distinct_words_when_they_air(self):
        self.send("哈哈", "嘿嘿", "😂")
        spoken = [self.air()["text"] for _ in range(3)]
        self.assertEqual(len(set(spoken)), 3)

    def test_unsupported_burst_comment_is_saved_and_can_be_picked_manually(self):
        self.send("甲", "乙", "丙", "玄紫青")
        first = self.air()
        self.assertEqual((first["source"], first["text"]), ("gift_invite", first["giftInvite"]))
        skipped = self.send("墨青灰")
        with self.studio.cv:
            self.assertTrue(self.studio.cv.wait_for(
                lambda: any(r["eventId"] == skipped and r["status"] == "superseded" for r in self.studio.recent), 2))
        self.studio.control({"action": "reply", "roomId": "test", "eventId": skipped})
        self.assertEqual(self.air()["eventId"], skipped)

    def test_identical_model_answer_to_different_questions_gets_a_specific_alternative(self):
        canned = "算盘拨得这么响，我隔壁都听见了。"
        self.studio.dialogue.configure("test-key", None)
        with patch.object(self.studio.dialogue, "_json_reply", return_value={"segments": [{"text": canned}]}):
            self.send("怎样提加薪？")
            first = self.air()
            self.send("怎么应对无偿加班？")
            second = self.air()
        self.assertEqual(first["text"], canned)
        self.assertEqual(second["planner"], "fallback")
        self.assertNotEqual(second["text"], first["text"])
