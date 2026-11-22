import unittest
from unittest.mock import patch

from host_dialogue import Dialogue


class CommentPersonaTest(unittest.TestCase):
    def setUp(self):
        self.dialogue = Dialogue()
        self.dialogue.configure("test-only", None)
        self.comment = {"source": "comment", "roomId": "studio", "prompt": "同事又抢我功劳"}

    def test_short_draft_keeps_the_specific_roast_in_one_utterance(self):
        roast = "你敲的键盘，他倒敢给回车键冠名。"
        with patch.object(self.dialogue, "_json_reply", return_value={"segments": [
                {"text": "你已经很努力了，加油呀。"}, {"text": roast}]}) as api:
            reply, mode = self.dialogue.plan(self.comment, [])
        api.assert_called_once()
        instruction = api.call_args.args[1]["messages"][0]["content"]
        self.assertIn("尖酸刻薄", instruction)
        self.assertIn("一句短话", instruction)
        self.assertEqual((mode, [part["text"] for part in reply]), ("deepseek", [roast]))

    def test_keep_sarcastic_praise_with_a_concrete_payoff(self):
        roast = "辛苦了，抄个署名就算你加班了？"
        with patch.object(self.dialogue, "_json_reply", return_value={"segments": [{"text": roast}]}):
            reply, mode = self.dialogue.plan(self.comment, [])
        self.assertEqual((mode, [part["text"] for part in reply]), ("deepseek", [roast]))

    def test_encouragement_alone_uses_local_fallback_only_for_default(self):
        pep = "相信自己，你一定可以的。"
        with patch.object(self.dialogue, "_json_reply", return_value={"segments": [{"text": pep}]}) as api:
            reply, mode = self.dialogue.plan(self.comment, [])
            self.assertEqual(mode, "fallback")
            self.assertEqual(len(reply), 1)
            self.assertNotIn(pep, reply[0]["text"])
            self.dialogue.configure(None, None, "把评论台当成鼓励大会。")
            custom, mode = self.dialogue.plan(self.comment, [])
        self.assertEqual(api.call_count, 2)
        self.assertEqual((mode, [part["text"] for part in custom]), ("deepseek", [pep]))
