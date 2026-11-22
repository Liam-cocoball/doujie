from copy import deepcopy
import unittest

from audience_invites import append_gift_invite, make_gift_invite, mentions_gifts
from host_dialogue import EXPRESSIONS, GESTURES


class AudienceInviteTest(unittest.TestCase):
    def test_standalone_and_appended_invites_rotate_together_with_one_spoken_beat(self):
        history = []
        invites = []
        gestures = set()
        for index in range(24):
            if index % 2:
                reply = "这话问到点上了。"
                line = append_gift_invite([{"text": reply}], history)[0]["text"]
                invite = line.removeprefix(reply)
            else:
                part = make_gift_invite(history)
                self.assertIn(part["expression"], EXPRESSIONS)
                self.assertIn(part["gesture"], GESTURES)
                self.assertEqual(part["pauseMs"], 0)
                gestures.add(part["gesture"])
                line = invite = part["text"]
            self.assertTrue(mentions_gifts(invite))
            self.assertLessEqual(len(invite), 26)
            self.assertNotIn(invite, invites[-11:])
            invites.append(invite)
            history.append(line)
        self.assertGreater(len(gestures), 1)

    def test_invite_shares_last_beat_and_keeps_the_answer_and_performance(self):
        segments = [{"text": "当老板的先把工资结了。", "gesture": "point"},
                    {"text": "饼留给食堂", "expression": "smirk", "pauseMs": 80}]
        original = deepcopy(segments)
        aired = append_gift_invite(segments, [])
        self.assertEqual(segments, original)
        self.assertEqual(len(aired), 2)
        self.assertEqual(aired[0], original[0])
        self.assertTrue(aired[1]["text"].startswith("饼留给食堂。"))
        self.assertTrue(mentions_gifts(aired[1]["text"]))
        self.assertEqual({**aired[1], "text": "饼留给食堂"}, original[1])
        self.assertEqual(append_gift_invite(aired, []), aired)

    def test_recent_full_replies_rotate_gifts_before_repeating(self):
        history = []
        for index in range(12):
            reply = f"第{index}条弹幕倒挺有意思。"
            text = append_gift_invite([{"text": reply}], history)[0]["text"]
            invite = text.removeprefix(reply)
            self.assertNotEqual(invite, "")
            self.assertNotIn(invite, "".join(history[-5:]))
            history.append(text)

    def test_already_discussing_gifts_and_unusable_endings(self):
        for text in ("送礼能点歌吗？", "打赏先免了。", "玫瑰的刺谁拔？", "给主播刷一个。", " "):
            with self.subTest(text=text):
                segments = [{"text": text}]
                self.assertIs(append_gift_invite(segments, []), segments)
        segments = [{"text": "嘉年华收到了。"}, {"text": "下一位。"}]
        self.assertIs(append_gift_invite(segments, []), segments)
        self.assertEqual(append_gift_invite([], []), [])

    def test_never_exceeds_a_single_synthesis_request_or_truncates_the_reply(self):
        for length in range(135, 165):
            text = "答" * length
            segments = [{"text": text}]
            aired = append_gift_invite(segments, [])
            self.assertEqual(len(aired), 1)
            self.assertTrue(aired[0]["text"].startswith(text))
            if aired is not segments:
                self.assertLessEqual(len(aired[0]["text"]), 162)
            if length >= 162:
                self.assertIs(aired, segments)
