import re
import unittest

from studio_inventory import ITEMS, room_reply


class StudioInventoryTest(unittest.TestCase):
    task = {"source": "comment", "roomId": "20", "audience": "v1", "name": "小林"}

    def ask(self, prompt, history=(), **fields):
        return room_reply({**self.task, "prompt": prompt, **fields}, history)

    def answer(self, prompt, history=()):
        rows = self.ask(prompt, history)
        self.assertTrue(rows, prompt)
        return "".join(row["text"] for row in rows)

    def test_brief_answers_speak_only_the_requested_detail(self):
        for prompt, subject, fact in (
            ("围巾啥色", "scarf", "莓红色"), ("红围巾在哪", "scarf", "我脖子上"),
            ("监视器在哪", "monitor", "右侧"), ("桌上那小监视器在哪", "monitor", "右侧"),
            ("手机屏幕朝哪", "phone", "内屏朝我"), ("苹果标在哪", "phone", "银白后盖"),
            ("手机多少G", "phone", "瞧不出来"), ("手机什么型号", "phone", "iPhone Duo"),
            ("左边是啥", "phone", "iPhone Duo"), ("你这监视器多少钱", "monitor", "没报过价"),
        ):
            with self.subTest(prompt=prompt):
                rows = room_reply({**self.task, "prompt": prompt}, [], brief=True)
                self.assertIsNotNone(rows)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["pauseMs"], 0)
                self.assertEqual(rows[0].get("focusItem"), subject)
                self.assertIn(fact, rows[0]["text"])
                self.assertLessEqual(len(rows[0]["text"]), 22)

    def test_brief_followups_keep_the_same_viewer_and_item(self):
        for previous, prompt, subject, fact in (
            ("监视器在哪", "多少钱", "monitor", "没报过价"), ("监视器在哪", "那另一边呢", "phone", "左侧"),
            ("围巾啥色", "那它在哪", "scarf", "我脖子上"), ("手机在哪", "屏幕朝哪", "phone", "内屏朝我"),
            ("围巾在哪", "啥色", "scarf", "莓红色"),
        ):
            with self.subTest(prompt=prompt):
                first = {**self.task, "prompt": previous}
                saved = {**first, **room_reply(first, [], brief=True)[0]}
                task = {**self.task, "prompt": prompt}
                rows = room_reply(task, [saved], brief=True)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["focusItem"], subject)
                self.assertIn(fact, rows[0]["text"])
                for other in ({"audience": "v2"}, {"roomId": "21"}):
                    self.assertIsNone(room_reply(task, [{**saved, **other}], brief=True))
                for unrelated in ("哈哈", "嘿嘿", "。。。", "我手机坏了"):
                    self.assertIsNone(room_reply({**task, "prompt": unrelated}, [saved], brief=True))

    def test_multiple_requested_details_survive_both_speech_lengths(self):
        for prompt, facts in (
            ("你桌上两边的手机和监视器分别是什么颜色，放在哪里？", ("左边", "银白色", "右边", "绿色波形")),
            ("说说你这台手机的摆法、屏幕朝哪、后盖是什么标志？", ("平放", "掀起", "内屏朝我", "苹果标")),
        ):
            for brief in (False, True):
                with self.subTest(prompt=prompt, brief=brief):
                    rows = room_reply({**self.task, "prompt": prompt}, [], brief=brief)
                    self.assertEqual(len(rows), 1 if brief else 2)
                    spoken = "".join(row["text"] for row in rows)
                    for fact in facts:
                        self.assertIn(fact, spoken)

    def test_screen_and_host_views_and_body_parts(self):
        for prompt, key, position, detail in (
            ("屏幕左边发亮的是啥？", "phone", "桌面左侧", "银白后盖"),
            ("右侧这个是啥？", "monitor", "桌面右侧", "绿线"),
            ("从你自己这边看，左手边那个是什么？", "monitor", "桌面右侧", "绿线"),
            ("你右手边的是什么", "phone", "桌面左侧", "银白后盖"),
            ("你脖子上那条是什么颜色？", "scarf", "脖子上", "流苏"),
            ("你脚上穿的什么？", "shoes", "脚上", "圆头"),
            ("左后方发光的是啥？", "lamp", "左后方", "暖色灯罩"),
            ("你那绿线一直跳的小屏是啥？", "monitor", "桌面右侧", "波形"),
        ):
            with self.subTest(prompt=prompt):
                rows = self.ask(prompt)
                self.assertIn(ITEMS[key]["name"], rows[0]["text"])
                self.assertIn(position, rows[0]["text"])
                self.assertIn(detail, rows[1]["text"])
                if key in ("phone", "monitor"):
                    self.assertTrue(all(row.get("focusItem") == key for row in rows))

    def test_two_speakable_beats_keep_the_fact_and_the_payoff(self):
        prompts = ["那个模型是什么", "你喜欢贵重的东西吗", "手机多少G", "手机是什么牌子",
                   "这手机多少钱", "你这手机怎么摆的", "手机背面是什么标", "这是笔记本吗",
                   "你这包能装得下手机吗", "你桌上的包提手什么颜色", "你身上这件大衣多少钱",
                   "你今天这身怎么搭配", "你桌上都有什么", "直播间的模型都是什么，在哪里"]
        prompts.extend("你的" + item["name"] + "在哪" for item in ITEMS.values())
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                rows = self.ask(prompt)
                self.assertEqual(len(rows), 2)
                counts = [len(re.findall(r"[\u3400-\u9fff]|[a-zA-Z0-9]+", row["text"])) for row in rows]
                self.assertGreaterEqual(sum(counts), 25)
                self.assertLessEqual(sum(counts), 50)
                self.assertGreaterEqual(min(counts), 6)
                self.assertTrue(all(row["text"].endswith(("。", "？", "！")) for row in rows))
        self.assertIn("包已经撤了", self.answer("你桌上的包提手什么颜色"))
        self.assertIn("内屏朝我", self.answer("这台手机怎么摆的"))

    def test_side_by_side_and_room_overview(self):
        for prompt in ("直播间的模型都是什么，在哪里？", "屏幕上左边的和右边的分别是什么？",
                       "桌上有哪些摆件？", "你桌上的宝贝是什么？"):
            with self.subTest(prompt=prompt):
                spoken = self.answer(prompt)
                self.assertIn("左边是" + ITEMS["phone"]["name"], spoken)
                self.assertIn("右边是" + ITEMS["monitor"]["name"], spoken)
        self.assertIn(ITEMS["window"]["name"], self.answer("直播间的模型都是什么，在哪里？"))
        self.assertIn(ITEMS["mixer"]["name"], self.answer("你桌上都有什么？"))
        outfit = self.answer("豆姐你今天这身怎么搭配的？")
        self.assertTrue(all(i["name"] in outfit for i in ITEMS.values() if i["category"] == "outfit"))

    def test_identity_and_attitude_for_specific_questions(self):
        for prompt, expected in (
            ("手机是什么牌子？", "苹果的iPhone Duo"),
            ("桌上的手机是哪一款？", "型号是iPhone Duo"),
            ("你桌上的包身上写的啥？", "包已经撤了"),
            ("豆姐最喜欢什么贵的？", "喜欢贵的"), ("你喜欢贵重的东西吗？", "喜欢贵的"),
            ("你那包难看死了", "包已经撤了"), ("我看上你右边那小包了", "包已经撤了"),
            ("你戴的围巾是LV的吗？", "看不见牌子"), ("手机多少G？", "瞧不见"),
            ("你那个杯子呢？", "没说镜头里有杯子"), ("你桌上的跑车也是常驻的吗？", "出场时间"),
        ):
            with self.subTest(prompt=prompt):
                self.assertIn(expected, self.answer(prompt))

    def test_spoken_reference_survives_other_rooms_and_viewers_and_restart(self):
        monitor = {**self.task, "prompt": "右边那个是啥？", "text": "看绿色波形。", "focusItem": "monitor"}
        other_viewer = {**monitor, "audience": "v2", "focusItem": "phone"}
        other_room = {**monitor, "roomId": "21", "focusItem": "phone"}
        history = [monitor, other_viewer, other_room]
        for prompt, target in (("那它多少钱？", "没报过价"), ("那它是什么颜色的？", "绿线"),
                               ("它是真是假？", "鉴定书"), ("在哪里买的？", "小票")):
            with self.subTest(prompt=prompt):
                spoken = self.answer(prompt, history)
                self.assertIn(ITEMS["monitor"]["name"], spoken)
                self.assertIn(target, spoken)
        self.assertIn(ITEMS["phone"]["name"], self.answer("哦，那另一边呢？", history))
        self.assertIsNone(self.ask("多少钱？", [other_room, other_viewer]))
        self.assertIsNone(self.ask("多少钱？", [monitor, {**self.task, "text": "老板又来催人了。"}]))
        legacy = {**self.task, "prompt": "左边是包？", "text": "看清楚了。iPhone Duo。"}
        self.assertIn(ITEMS["phone"]["name"], self.answer("什么颜色？", [legacy]))

    def test_phone_pose_logo_and_laptop_silhouette(self):
        prior = [{**self.task, "text": "看这台折叠手机。", "focusItem": "phone"}]
        for prompt, facts in (
            ("手机背面是什么标？", ("银白后盖", "苹果标志", "镜头")),
            ("苹果标在哪？", ("银白后盖", "苹果标志", "镜头")),
            ("手机怎么摆的？", ("下半部平放", "上半部", "内屏朝我")),
            ("怎么摆的？", ("下半部平放", "上半部", "内屏朝我")),
            ("手机屏幕朝哪？", ("内屏朝我", "银白后盖")),
            ("那屏幕呢？", ("内屏朝我", "苹果标志")),
            ("手机键盘朝哪个方向？", ("下半部平放", "内屏", "没给它配实体键盘")),
            ("那它的键盘朝哪？", ("下半部平放", "内屏", "没给它配实体键盘")),
        ):
            with self.subTest(prompt=prompt):
                spoken = self.answer(prompt, prior)
                for fact in ("iPhone Duo", *facts):
                    self.assertIn(fact, spoken)
        for prompt in ("怎么像个小电脑？", "这是笔记本吗？", "桌上有电脑吗？", "那真的是电脑吗？"):
            with self.subTest(prompt=prompt):
                rows = self.ask(prompt)
                self.assertEqual(rows[0]["focusItem"], "phone")
                self.assertIn("iPhone Duo折叠手机", rows[0]["text"])
                self.assertIn("水平铰链", rows[-1]["text"])
        self.assertIn(ITEMS["monitor"]["name"], self.answer("画面右边那台是电脑吗？"))
        self.assertIsNone(self.ask("那屏幕呢？", [{**prior[0], "audience": "someone-else"}]))
        for prompt in ("我桌上的苹果标掉了怎么办？", "你会修笔记本吗？", "我家桌上有电脑吗？",
                       "买电脑还是买平板？", "这台电脑怎么升级内存？", "我要设计苹果标，怎么画？"):
            with self.subTest(prompt=prompt):
                self.assertIsNone(self.ask(prompt))

    def test_unrelated_viewer_possessions_and_gifts_use_the_normal_route(self):
        for prompt in ("我手机坏了怎么办？", "我刚买了个包怎么退？", "你知道我妈的LV包多少钱吗？",
                       "给豆姐买个包吧", "你会修手机吗？怎么截图？", "你这表情包哪找的？", "你包邮吗？",
                       "我的左手边是楼梯，今天摔了一跤", "我的外套怎么洗？"):
            with self.subTest(prompt=prompt):
                self.assertIsNone(self.ask(prompt))
        self.assertIsNone(self.ask("那部手机", source="gift"))
        self.assertIsNone(self.ask("桌上的包", source="manual"))

    def test_program_workplace_and_new_topics_do_not_match_set_dressing(self):
        prior = [{**self.task, "prompt": "你桌上那只包多少钱？", "focusItem": "bag"}]
        for prompt in ("这直播间有什么好玩的？", "这直播间有什么规矩？", "新来的，你直播间都有啥节目？",
                       "地铁左边有人打电话右边有人唱歌，你说呢？", "你左边胳膊怎么了？", "手机壳都找不到了，我怎么请假？",
                       "这种包吃包住的工作能接吗？", "你会包饺子吗？", "周末包场，老板说给加班红包！",
                       "那工资一般多少钱？", "多少钱能买辆车？", "你最喜欢什么颜色？", "真希望明天放假。",
                       "你是个显眼包吗？", "我老板说加班包夜宵，靠谱吗？", "豆姐手机看你的直播卡怎么办？",
                       "老板说开会不让带手机，你怎么看？", "LV 宣布涨价，你怎么看？",
                       "直播间的观众买手机怎么选？", "我脖子上起了疹子，怎么办？",
                       "大语言模型是什么？", "豆姐喜欢别人给你送玫瑰吗？"):
            with self.subTest(prompt=prompt):
                self.assertIsNone(self.ask(prompt, prior))
        # A stray branded line in old history does not turn an unrelated conversation into a prop question.
        legacy = {**self.task, "prompt": "老板催加班", "text": "看我这只LV 老花小包。"}
        self.assertIsNone(self.ask("那它多少钱？", [legacy]))
        self.assertIsNone(self.ask("那它多少钱？", [{**prior[0], "at": 1_000}], _stamp=3_000))

    def test_only_the_referenced_subject_is_named(self):
        self.assertIn("给我个位置", self.answer("那个模型是什么？"))
        monitor = {**self.task, "focusItem": "monitor"}
        self.assertIn(ITEMS["monitor"]["name"], self.answer("那个模型是什么？", [monitor]))
        self.assertNotIn(ITEMS["phone"]["name"], self.answer("那个模型是什么？", [monitor]))
        for prompt, subject in (("你的监视器多少钱？", "monitor"), ("右边的监视器挺好看", "monitor"),
                                ("这手机多少钱？", "phone"), ("手机是什么牌子？", "phone"),
                                ("你桌上的手机是LV的吗？", "phone"),
                                ("你这条围巾好漂亮", "scarf")):
            with self.subTest(prompt=prompt):
                spoken = self.answer(prompt)
                self.assertIn(ITEMS[subject]["name"], spoken)
                for key in {"phone", "monitor"} - {subject}:
                    self.assertNotIn(ITEMS[key]["name"], spoken)
        for prompt in ("你喜欢贵重的东西吗？", "你桌上的跑车也是常驻的吗？"):
            spoken = self.answer(prompt)
            self.assertNotIn(ITEMS["phone"]["name"], spoken)
            self.assertNotIn(ITEMS["monitor"]["name"], spoken)

    def test_removed_bag_and_new_gift_wall_match_the_set(self):
        self.assertNotIn("bag", ITEMS)
        for prompt in ("你之前的LV包呢？", "包在哪", "那个老花包多少钱？", "桌上的小包呢"):
            with self.subTest(prompt=prompt):
                self.assertIn("撤了", self.answer(prompt))
        stale = {**self.task, "prompt": "那个LV小包？", "text": "右边是包，左边是iPhone Duo。", "focusItem": "bag"}
        self.assertIsNone(self.ask("什么颜色？", [stale]))
        self.assertNotIn("LV", self.answer("桌上有什么？", [stale]))
        self.assertIn("身后上方", self.answer("你的礼物墙在哪？"))
        self.assertIn("礼物墙", self.answer("你身后那块写着名字的牌是什么？"))
        self.assertIn("最近三笔", self.answer("礼物墙显示什么？"))

if __name__ == "__main__":
    unittest.main()
