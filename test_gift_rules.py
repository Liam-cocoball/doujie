import unittest
from unittest.mock import Mock, patch

from gift_rules import GIFTS, GiftCombos, can_merge_gift, contextual_gift, gift_merge_key, gift_script, merge_gift


class GiftRulesTest(unittest.TestCase):
    def test_all_special_gifts_have_distinct_performances(self):
        self.assertEqual(len(GIFTS), 9)
        scripts = [gift_script(gift["name"], names=["阿雨"]) for gift in GIFTS]
        self.assertEqual([item["giftFx"] for item in scripts], [gift["id"] for gift in GIFTS])
        self.assertEqual(len({item["segments"][1]["text"] for item in scripts}), len(GIFTS))
        for gift, item in zip(GIFTS, scripts):
            self.assertEqual(item["effect"], gift["id"])
            line = item["segments"][0]["text"]
            self.assertIn(gift["name"], line)
            self.assertIn("阿雨", line)
            self.assertTrue(all(segment["expression"] and segment["gesture"] for segment in item["segments"]))

    def test_common_price_tiers_and_unknown_names(self):
        for name, price, script_id in (
            ("初次见到的礼物", 1, "generic_low"), ("天鹅之梦", 50, "generic_mid"),
            ("蝶 · 连理枝", 280, "generic_mid"), ("热气球", 520, "generic_high"),
            ("嘉年华", 30000, "generic_high"),
        ):
            script = gift_script(name)
            self.assertEqual((script["giftPrice"], script["giftId"]), (price, script_id))
            self.assertEqual((script["giftFx"], script["effect"]), ("generic", "generic"))
        self.assertIn("礼物", gift_script(None)["segments"][0]["text"])
        self.assertNotEqual(gift_merge_key("抖音"), gift_merge_key("陌生礼物"))

    def test_gift_variants_stay_in_character_at_every_tier(self):
        names = [g["name"] for g in GIFTS] + ["陌生礼物", "天鹅之梦", "嘉年华"]
        for name in names:
            with self.subTest(gift=name):
                first, second, third, again = [gift_script(name, count=3, names=["小林"], variant=i) for i in range(4)]
                self.assertEqual(first, again)
                for i in range(2):
                    self.assertEqual(len({script["segments"][i]["text"] for script in (first, second, third)}), 3)
                for script in (first, second, third):
                    opening, closing = script["segments"]
                    self.assertIn("小林", opening["text"])
                    self.assertIn("3份" + name, opening["text"])
                    thank = r"谢谢|谢了|谢啦"
                    self.assertRegex(opening["text"].split(name)[0], thank)
                    self.assertNotRegex(closing["text"], thank)
                    self.assertTrue(all(phrase not in opening["text"] + closing["text"]
                                        for phrase in ("么么哒", "再刷", "多刷")))
                    self.assertNotIn("soft", (opening["expression"], closing["expression"]))

    def test_merge_rerenders_acknowledgement(self):
        first = gift_script(" 玫 瑰", count=2, names=["阿雨"], variant=1)
        second = gift_script("玫瑰", count=1, names=["阿雨", "小鱼"])
        merged = merge_gift(first, second)
        self.assertEqual(merged["giftCount"], 3)
        self.assertEqual(merged["giftViewers"], ["阿雨", "小鱼"])
        self.assertEqual(merged["giftVariant"], 1)
        self.assertEqual(merged["segments"][1], first["segments"][1])
        self.assertIn("3份", merged["segments"][0]["text"])
        self.assertEqual(first["giftCount"], 2)
        with self.assertRaises(ValueError):
            merge_gift(first, gift_script("跑车"))

    def test_all_group_members_are_thanked_and_supported_names_fit_tts(self):
        from server import MAX_TTS_TEXT
        first = gift_script("玫瑰", names=["阿雨", "小鱼", "星星"])
        line = first["segments"][0]["text"]
        self.assertIn("谢谢阿雨、小鱼、星星", line)
        self.assertTrue(can_merge_gift(first, gift_script("玫瑰", names=["小鱼"])))
        self.assertFalse(can_merge_gift(first, gift_script("玫瑰", names=["桃子"])))
        self.assertFalse(can_merge_gift(first, gift_script("玫瑰")))
        anonymous = gift_script("玫瑰", 2)
        self.assertIn("谢谢送礼的朋友，2份玫瑰", anonymous["segments"][0]["text"])
        self.assertEqual(anonymous["giftViewers"], [])
        self.assertTrue(can_merge_gift(anonymous, gift_script("玫瑰")))
        long_names = [c * 160 for c in "甲乙丙"]
        large = gift_script("花" * 120, 10**9, long_names)
        self.assertEqual(large["giftViewers"], long_names)
        self.assertLessEqual(len(large["segments"][0]["text"]), MAX_TTS_TEXT)

    def test_custom_persona_cannot_add_another_thank_you_to_the_gift_payoff(self):
        from host_dialogue import Dialogue
        dialogue = Dialogue()
        dialogue.configure("test-key", None, "我偏要当个客气主播。")
        with patch.object(dialogue, "_json_reply", return_value={"line": "再谢谢送礼的朋友，今天这朵花可真漂亮。"}):
            self.assertIsNone(dialogue.gift_line("玫瑰", {}, "刺我收着。", "谢谢，花放这儿。"))

    def test_real_scheduler_keeps_every_named_donor_in_the_first_spoken_segment(self):
        from server import Scheduler, validate
        studio = Scheduler()
        self.addCleanup(studio.close)
        studio.dialogue.configure("", None)

        def active():
            with studio.cv:
                self.assertTrue(studio.cv.wait_for(lambda: studio.active, timeout=2))
                return studio.state(stage=True)["active"]

        def finish(cue):
            ack = {"id": cue["id"], "player": "test"}
            self.assertTrue(studio.playback({**ack, "phase": "start"}))
            for i in range(len(cue["segments"])):
                self.assertTrue(studio.playback({**ack, "phase": "segment", "index": i}))
            self.assertTrue(studio.playback({**ack, "phase": "complete"}))

        studio.control({"action": "manual", "text": "开场。"})
        opener = active()
        gifts = (("小林", 2), ("阿雨", 1), ("小鱼", 3), ("星星", 4), ("", 1))
        studio.ingest(validate([{"roomId": "test", "eventId": str(i), "type": "gift",
                                 "actor": {"nickname": name} if name else None,
                                 "data": {"giftName": "玫瑰", "displayCount": count}}
                                for i, (name, count) in enumerate(gifts)]))
        finish(opener)
        delivered = {}
        for _ in range(3):
            cue = active()
            line = cue["segments"][0]["text"]
            self.assertRegex(line, r"谢谢|谢了|谢啦")
            for person in cue["giftViewers"]:
                self.assertIn(person, line)
            delivered[tuple(cue["giftViewers"])] = cue["giftCount"]
            finish(cue)
        self.assertEqual(delivered, {("小林", "阿雨", "小鱼"): 6, ("星星",): 4, (): 1})
        self.assertEqual(studio.state()["queueDepth"], 0)

    def test_combo_duplicate_out_of_order_reset_and_window(self):
        combo = GiftCombos()
        snapshots = [(1, 0), (3, 1), (3, 1), (2, .5), (3, 2), (4, 2),
                     (1, 3), (5, 2.5), (3, 4), (4, 14)]
        self.assertEqual([combo.increment("room", "viewer", "玫瑰", n, t) for n, t in snapshots],
                         [1, 2, 0, 0, 0, 1, 1, 0, 2, 4])
        self.assertEqual(combo.increment("another-room", "viewer", "玫瑰", 3, 15), 3)
        self.assertEqual(combo.increment("room", "someone-else", "玫瑰", 3, 15), 3)
        self.assertEqual(combo.increment("room", "viewer", "大啤酒", 3, 15), 3)

    def test_explicit_combo_id_and_standalone_gifts(self):
        combo = GiftCombos()
        self.assertEqual([combo.increment("r", "a", "花", n, t, "streak")
                          for n, t in [(2, 0), (1, 2), (2, 3), (4, 20)]], [2, 0, 0, 2])
        self.assertEqual(combo.increment("r", "a", "花", 1, 21, "new-streak"), 1)
        self.assertEqual([combo.increment("r", "b", "花", 1, t) for t in (0, 0, 2)], [1, 0, 1])
        self.assertEqual(combo.increment("r", "b", "花", None, 3), 1)

    def test_contextual_gift_keeps_opener_and_poses(self):
        task = gift_script("跑车", 2, ["小鱼"])
        row = {"source": "comment", "prompt": "老板又让我加班？", "text": "这要看情况。"}
        result = contextual_gift(task, [row], lambda context, default: "这辆车接你下班，总比加班强。")
        self.assertEqual(result[0], task["segments"][0])
        self.assertIn("加班", result[-1]["text"])
        self.assertEqual(result[-1]["gesture"], task["segments"][-1]["gesture"])
        self.assertNotEqual(result[-1]["text"], task["segments"][-1]["text"])
        fallback = contextual_gift(task, [row], lambda *_: 1 / 0)
        self.assertNotIn("老板又让我加班", fallback[-1]["text"])
        self.assertIn("加班费", fallback[-1]["text"])
        rose = contextual_gift(gift_script("玫瑰"), [row])
        self.assertIn("到货日期", rose[-1]["text"])
        repeated = contextual_gift(task, [row, {"source": "gift"}])
        self.assertEqual(repeated, task["segments"])

    def test_repeated_topic_and_model_punchline_use_fresh_gift_script(self):
        topic = {"source": "comment", "prompt": "老板又让我加班。"}
        gift = gift_script("玫瑰")
        old = contextual_gift(gift, [topic])
        history = [topic, {"source": "gift", "text": "".join(s["text"] for s in old)}, topic]
        current = gift_script("玫瑰", variant=1)
        cousin = old[-1]["text"].replace("？", "！")
        result = contextual_gift(current, history, lambda *_: cousin)
        self.assertEqual(result, current["segments"])

    def test_rose_performances_rotate_even_when_archive_ids_have_same_parity(self):
        from server import Scheduler, validate
        studio = Scheduler()
        self.addCleanup(studio.close)
        studio.dialogue.configure("", None)
        scripts = []
        for index in range(7):
            studio.ingest(validate([{"type": "gift", "eventId": f"gift-{index}", "roomId": "qa",
                                     "data": {"giftName": "玫瑰"}},
                                    {"type": "unknown", "eventId": f"gap-{index}", "roomId": "qa"}]))
            with studio.cv:
                self.assertTrue(studio.cv.wait_for(lambda: studio.active is not None, timeout=2))
                cue = studio.state()["active"]
            scripts.append(cue["text"])
            self.assertNotIn(cue["text"], scripts[:-1][-2:])
            ack = {"id": cue["id"], "player": "test"}
            self.assertTrue(studio.playback({**ack, "phase": "start"}))
            for i in range(2):
                self.assertTrue(studio.playback({**ack, "phase": "segment", "index": i}))
            self.assertTrue(studio.playback({**ack, "phase": "complete"}))
        self.assertEqual(len(set(scripts)), 3)

    def test_first_and_consecutive_gifts_can_use_persona_without_repeating_old_topic(self):
        gift = gift_script("嘉年华", variant=1)
        for history in ([], [{"source": "comment", "prompt": "加班"}, {"source": "gift"}]):
            rewrite = Mock(return_value="灯光师，把我那块名牌挪到前面。")
            segments = contextual_gift(gift, history, rewrite)
            rewrite.assert_called_once_with({}, gift["segments"][-1]["text"])
            self.assertEqual(segments[0], gift["segments"][0])
            self.assertEqual(segments[-1]["text"], rewrite.return_value)
            self.assertNotEqual(gift["segments"][-1]["text"], rewrite.return_value)
            self.assertEqual(contextual_gift(gift, history, Mock(return_value=None)), gift["segments"])


if __name__ == "__main__":
    unittest.main()
