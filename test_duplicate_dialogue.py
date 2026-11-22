import unittest
from unittest.mock import patch

from host_dialogue import Dialogue, is_generic_reply


class DuplicateDialogueTest(unittest.TestCase):
    def setUp(self):
        self.dialogue = Dialogue()
        self.dialogue.configure("mock-key", None)
        self.task = {"source": "comment", "roomId": "123", "name": "小林", "prompt": "怎么处理，分三步讲讲。"}

    def generated_lines(self, *lines):
        result = {"segments": [{"text": line} for line in lines]}
        with patch.object(self.dialogue, "_json_reply", return_value=result):
            segments, mode = self.dialogue.plan(self.task, [])
        self.assertEqual(mode, "deepseek")
        return [segment["text"] for segment in segments]

    def test_overlapping_model_segments_keep_only_new_continuation(self):
        lead = "先把记录按日期列清楚，把超时的那几行圈出来。"
        answer = "再找负责人对着数字把每一步讲明白。"
        self.assertEqual(self.generated_lines(lead, "把超时的那几行圈出来，" + answer), [lead, answer])
        self.assertEqual(self.generated_lines(lead, lead.replace("，", "。") + answer), [lead, answer])

    def test_repeated_clause_is_removed_but_emphasis_and_changed_meaning_survive(self):
        line = "行，行，先把记录按日期列清楚，先把记录按日期列清楚，把双方的说明补上。"
        next_line = "别把双方的说明补上之前那份表当成完整记录。"
        self.assertEqual(self.generated_lines(line, next_line),
                         [line.replace("先把记录按日期列清楚，", "", 1), next_line])
        lead = "我从没有说过要把超时的那几行圈出来。"
        reply = "把超时的那几行圈出来，那是他自己提的主意。"
        self.assertEqual(self.generated_lines(lead, reply), [lead, reply])

    def test_gift_tail_cannot_rebroadcast_the_opening(self):
        opening = "玫瑰我收下了，别催我给你笑。"
        tail = "嘴角又没跟花一起打包。"
        for line, expected in ((opening, None), (opening + tail, tail),
                               ("别催我给你笑，" + tail, tail)):
            with self.subTest(line=line), patch.object(self.dialogue, "_json_reply", return_value={"line": line}):
                self.assertEqual(self.dialogue.gift_line("玫瑰", {}, "我可没答应附赠笑脸。", opening), expected)

    def test_generic_routes_rotate_across_intervening_turns_and_specific_answers_are_exempt(self):
        self.dialogue.configure("", None)
        for template in ("门边多了第{}筐竹篮", "第{}筐竹篮有多深？"):
            history, heard = [], []
            for n in range(22):
                task = {**self.task, "prompt": template.format(n)}
                segments, _ = self.dialogue.plan(task, history[-28:])
                line = "".join(s["text"] for s in segments)
                self.assertTrue(is_generic_reply(segments))
                self.assertNotIn(line, heard[-6:])
                self.assertNotIn("咂出味", line)
                self.assertNotIn("最想改哪一步", line)
                heard.append(line)
                history.extend(({**task, "text": line}, {**task, "text": "莓红色。"}))
        for prompt in ("怎么提加薪？", "围巾啥色？", "哈哈", "你是谁"):
            segments, _ = self.dialogue.plan({**self.task, "prompt": prompt}, [])
            self.assertFalse(is_generic_reply(segments))
        long = {**self.task, "prompt": "我昨晚在回家的路上看见门边多了一筐竹篮，想了好久也没想起来是谁放在那里的。"}
        segments, _ = self.dialogue.plan(long, [])
        self.assertTrue(is_generic_reply(segments))
        self.assertTrue(is_generic_reply([{"text": "".join(s["text"] for s in segments)}]))

    def test_retired_fallback_questions_in_an_archive_or_model_draft(self):
        kept = "先把记录按日期列清楚，再核对两个人交接的时间。谁签的名字就找谁把这一段交接讲清楚。"
        for retired in ("是当时就想笑，还是回过头才咂出味？", "这件事要是能倒回去，你最想改哪一步？"):
            self.assertTrue(is_generic_reply([{"text": retired}]))
            self.assertEqual(self.generated_lines(retired + kept), [kept])
        near = "我看了半天交接记录，回过头才咂出味。"
        self.assertEqual(self.generated_lines(near, kept), [near, kept])
