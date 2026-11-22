import io
import json
import os
import unittest
from unittest.mock import patch

from host_dialogue import DEFAULT_MODEL, DEFAULT_PERSONA, MAX_PERSONA_LENGTH, Dialogue


class DialogueTest(unittest.TestCase):
    def test_short_question_skips_windup_and_two_requests_keep_both_answers(self):
        self.dialogue.configure("mock-key", None)
        first = "先带两项能核对的业绩，再开价。"
        second = "考勤表带上，只标出超时那几行，让老板对着工时谈钱。"
        for windup in ("问得挺好。", "这事我可太懂了。"):
            with self.subTest(windup=windup), patch.object(self.dialogue, "_json_reply", return_value={
                    "segments": [{"text":windup + first}]}) as api:
                rows, mode = self.dialogue.plan({**self.task, "prompt":"怎么提加薪？"}, [])
                self.assertEqual((mode, [r["text"] for r in rows]), ("deepseek", [first]))
                self.assertEqual(api.call_count, 1)
        for question in ("怎么加薪？分三步说。", "和老板聊加薪，第一句话说什么，后面怎么拿出考勤记录？"):
            with self.subTest(question=question), patch.object(self.dialogue, "_json_reply", return_value={
                    "segments": [{"text":first}, {"text":second}]}):
                rows, mode = self.dialogue.plan({**self.task, "prompt":question}, [])
                self.assertEqual((mode, [r["text"] for r in rows]), ("deepseek", [first, second]))

    def setUp(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "DEEPSEEK_MODEL": ""}):
            self.dialogue = Dialogue()
        self.task = {"source": "comment", "roomId": "20", "audience": "account-817",
                     "name": "小林", "prompt": "那我真去问？"}
        self.last = {**self.task, "prompt": "老板说公司就是我第二个家。", "text": "这房子给你分几平？"}

    def test_offline_followup_matches_the_same_viewer_and_room(self):
        other_room = {**self.last, "roomId": "21", "prompt": "不在本场的对话"}
        other_viewer = {**self.last, "audience": "another-account", "prompt": "另一位观众的发言"}
        with patch("host_dialogue.request.urlopen") as network:
            segments, mode = self.dialogue.plan(self.task, [self.last, other_viewer, other_room])
        network.assert_not_called()
        self.assertEqual(mode, "local")
        self.assertIn("第二个家", "".join(s["text"] for s in segments))

    def test_short_topics_get_one_specific_offline_line(self):
        for prompt, anchors in (("老板说，公司是我家。", ("房", "家人", "几平")),
                                ("这个周会开了两小时", ("会", "周报", "成果")),
                                ("他又已读不回", ("字", "读", "消息", "沉默", "手指")),
                                ("约会结账又要我买单", ("钱", "账", "单", "分数"))):
            with self.subTest(prompt=prompt):
                segments, mode = self.dialogue.plan({**self.task, "prompt": prompt}, [])
                self.assertEqual(mode, "local")
                self.assertEqual(len(segments), 1)
                line = segments[0]["text"]
                self.assertTrue(any(word in line for word in anchors), line)
                self.assertLessEqual(sum(c.isalnum() for c in line), 28)
                self.assertLessEqual(segments[0]["pauseMs"], 150)
                self.assertTrue(segments[0]["gesture"] and segments[0]["expression"])

    def test_social_noise_gets_one_very_short_local_beat_even_with_a_key(self):
        self.dialogue.configure("mock-key", None)
        for source, prompt in (("comment", "😂😂"), ("comment", "？？！"), ("comment", "哈哈哈"),
                               ("comment", "嘿嘿"), ("topic", "你好！")):
            with self.subTest(prompt=prompt), patch.object(self.dialogue, "_json_reply") as api:
                rows, mode = self.dialogue.plan({**self.task, "source":source, "prompt":prompt}, [self.last])
                api.assert_not_called()
                self.assertEqual((mode, len(rows)), ("local", 1))
                line = rows[0]["text"]
                self.assertTrue(0 < sum(c.isalnum() for c in line) <= 12, line)
                self.assertNotIn("第二个家", line)
                self.assertFalse(rows[0].get("focusItem"))

    def test_reaction_prefix_does_not_swallow_a_specific_question(self):
        self.dialogue.configure("mock-key", None)
        for prompt in ("😂老板又画饼了", "哈哈，加班费去哪了？", "你好，怎么跟老板谈涨薪？"):
            with self.subTest(prompt=prompt), patch.object(self.dialogue, "_json_reply", return_value={
                    "segments":[{"text":"让老板把发钱日期写下来。", "expression":"skeptical", "gesture":"lean"}]}) as api:
                rows, mode = self.dialogue.plan({**self.task, "prompt":prompt}, [])
                api.assert_called_once()
                self.assertEqual(mode, "deepseek")
                self.assertEqual([r["text"] for r in rows], ["让老板把发钱日期写下来。"])
                self.assertEqual((rows[0]["expression"], rows[0]["gesture"]), ("skeptical", "lean"))

    def test_expansion_needs_a_subject_or_a_previous_turn_from_this_viewer(self):
        self.dialogue.configure("mock-key", None)
        task = {**self.task, "prompt":"展开讲讲"}
        unrelated = [{**self.last, "audience":"different-account"}]
        with patch.object(self.dialogue, "_json_reply") as api:
            rows, mode = self.dialogue.plan(task, unrelated)
        api.assert_not_called()
        self.assertEqual((mode, len(rows)), ("local", 1))
        self.assertTrue(any(w in rows[0]["text"] for w in ("哪", "什么", "啥", "说清", "给个")))
        self.assertNotIn("房", rows[0]["text"])

    def test_keeps_her_bad_temper_in_bad_news_good_news_and_direct_banter(self):
        for prompt, anchors in (("刚被裁了，老板还让我笑", ("工牌", "钱", "财务", "老板", "补偿", "笑")),
                                ("我终于涨工资了！", ("工资", "嘚瑟", "成绩", "涨", "钱", "财务")),
                                ("老婆贴贴", ("试用", "靠近", "老婆", "证", "亲", "婚", "撩", "贴")),
                                ("给爷笑一个", ("遥控", "键", "笑", "按", "指挥", "脸")),
                                ("有本事你骂我一句", ("骂", "外包", "甲方", "领号")),
                                ("你太凶了，别骂我", ("凶", "嫌", "辣", "骂", "烫", "脾气")),
                                ("我老婆已读不回", ("字", "消息", "读", "年假", "心理")),
                                ("刷了礼物你总该听我的", ("礼", "包邮", "脸色", "听话", "账", "发票"))):
            with self.subTest(prompt=prompt):
                segments, _ = self.dialogue.plan({**self.task, "prompt": prompt}, [])
                spoken = "".join(s["text"] for s in segments)
                self.assertTrue(any(anchor in spoken for anchor in anchors), spoken)
                self.assertTrue(all(s["expression"] != "soft" for s in segments))

    def test_short_challenges_and_pet_names_each_rotate_complete_comebacks(self):
        for prompt, anchors in (("你就这水平？", ("评委", "刺", "本事")),
                                ("叫声老公", ("证", "结婚", "婚都结了", "候补"))):
            with self.subTest(prompt=prompt):
                task = {**self.task, "prompt": prompt}
                history = []
                for _ in range(3):
                    segments, mode = self.dialogue.plan(task, history)
                    self.assertEqual((mode, len(segments)), ("local", 1))
                    line = segments[0]["text"]
                    self.assertTrue(any(anchor in line for anchor in anchors), line)
                    self.assertNotIn(line, [row["text"] for row in history])
                    history.append({**task, "text": line})

        segments, _ = self.dialogue.plan({**self.task, "prompt": "我就这一个同事，他还抢功劳"}, [])
        self.assertIn("署名", "".join(part["text"] for part in segments))

    def test_unfamiliar_stories_vary_the_televised_tag(self):
        task = {**self.task, "prompt": "窗口挂了一盏紫色的灯"}
        first, _ = self.dialogue.plan(task, [])
        history = [{**task, "text": first[0]["text"]}]
        second, _ = self.dialogue.plan(task, history)
        self.assertNotIn(task["prompt"], "".join(s["text"] for s in first + second))
        self.assertNotIn("紫色的灯", second[0]["text"])
        self.assertNotEqual(first[0]["text"], second[0]["text"])

    def test_offline_roasts_keep_comment_and_nickname_off_the_mic(self):
        for prompt in ("那扇门为什么一直关着", "所有人都得穿银色雨衣", "墙上的时钟停了吗？",
                       "他说从不犹豫，结果转头就买了三只", "一片树叶飘过窗台"):
            with self.subTest(prompt=prompt):
                segments, _ = self.dialogue.plan({**self.task, "prompt": prompt}, [])
                spoken = "".join(part["text"] for part in segments)
                self.assertNotIn(self.task["name"], spoken)
                for clause in prompt.rstrip("？").split("，"):
                    self.assertNotIn(clause, spoken)
        poses = set()
        for turn in range(4):
            planned, _ = self.dialogue.plan({**self.task, "id": turn, "prompt": "老板又画饼"}, [])
            poses.add((planned[0]["gesture"], planned[0]["expression"]))
        self.assertEqual(len(poses), 4)

    def test_model_readback_and_vocative_are_removed_before_synthesis(self):
        self.dialogue.configure("mock-key", None)
        task = {**self.task, "prompt": "公司允许迟到吗？"}
        reply = {"segments": [
            {"text": "这位观众问：“公司允许迟到吗？”", "gesture": "look", "expression": "skeptical"},
            {"text": "小林，老板迟到也扣钱，我才信这钟准。"},
        ]}
        with patch.object(self.dialogue, "_json_reply", return_value=reply):
            segments, mode = self.dialogue.plan(task, [])
        self.assertEqual(mode, "deepseek")
        self.assertEqual([s["text"] for s in segments], ["老板迟到也扣钱，我才信这钟准。"])
        self.assertEqual(segments[0]["expression"], "deadpan")
        # An echoed fragment and the real response can arrive together, in the same beat.
        kept = "翻下考勤表，谁负责记老板的迟到？"
        mixed = {"segments": [{"text": "你问：“公司允许迟到吗？”" + kept}]}
        with patch.object(self.dialogue, "_json_reply", return_value=mixed):
            segments, mode = self.dialogue.plan(task, [])
        self.assertEqual((segments[0]["text"], mode), (kept, "deepseek"))
        with patch.object(self.dialogue, "_json_reply", return_value={"segments": [{"text": task["prompt"]}]}):
            segments, mode = self.dialogue.plan(task, [])
        self.assertEqual(mode, "fallback")
        self.assertNotIn(task["prompt"], "".join(s["text"] for s in segments))

    def test_model_receives_broadcast_context_and_returns_playable_beats(self):
        self.dialogue.configure("mock-key", None)
        reply = {"segments": [
            {"text": "问，叫他把户型图摊开。", "expression": "skeptical", "gesture": "look", "pauseMs": 220},
            {"text": "记得问面积，复印机到茶水间那两步可别算公摊。", "expression": "smirk", "gesture": "shrug"},
        ]}
        envelope = {"choices": [{"message": {"content": json.dumps(reply, ensure_ascii=False)}}]}
        response = io.BytesIO(json.dumps(envelope).encode())
        task = {**self.task, "prompt":"刚才那件事我想认真问清楚，展开讲讲怎么跟老板开口、又该怎么接他的话？"}
        with patch("host_dialogue.request.urlopen", return_value=response) as network:
            segments, mode = self.dialogue.plan(task, [self.last, {**self.last, "roomId": "21", "prompt": "另一间的投稿"}])
        self.assertEqual((mode, segments[1]["gesture"]), ("deepseek", "shrug"))
        self.assertEqual(segments[0]["pauseMs"], 180)
        sent = json.loads(network.call_args.args[0].data)
        self.assertEqual(network.call_args.kwargs["timeout"], 5)
        self.assertEqual(sent["model"], DEFAULT_MODEL)
        self.assertEqual(sent["response_format"]["type"], "json_object")
        context = sent["messages"][-1]["content"]
        self.assertIn(self.last["text"], context)
        self.assertIn(task["prompt"], context)
        self.assertNotIn("另一间的投稿", context)
        self.assertNotIn(self.task["audience"], context)
        self.assertNotIn(self.task["name"], context)
        self.assertNotIn("mock-key", json.dumps(self.dialogue.status()))

    def test_visible_props_are_factual_even_if_the_operator_changes_the_persona(self):
        item = {**self.task, "prompt":"你桌上这个手机是什么型号？"}
        self.dialogue.configure("mock-key", None, "天天吹牛，什么都敢说。")
        with patch.object(self.dialogue, "_json_reply", side_effect=AssertionError("invented room facts")):
            rows, mode = self.dialogue.plan(item, [])
        self.assertEqual(mode, "local")
        self.assertEqual(len(rows), 1)
        self.assertIn("iPhone Duo", rows[0]["text"])
        self.assertNotIn("LV", rows[0]["text"])
        self.assertIn("phone", [row.get("focusItem") for row in rows])

    def test_viewer_can_talk_about_their_lv_without_giving_the_host_a_bag(self):
        self.dialogue.configure("mock-key", None)
        question = {**self.task, "prompt": "我新买的LV包肩带断了怎么办？"}
        with patch.object(self.dialogue, "_json_reply", return_value={
                "segments": [{"text": "我有个LV包，比你的结实。先把断掉的肩带和小票带去门店。"}]}):
            segments, mode = self.dialogue.plan(question, [])
        self.assertEqual(mode, "deepseek")
        self.assertEqual(segments[0]["text"], "先把断掉的肩带和小票带去门店。")

    def test_new_comments_and_gifts_omit_scene_history_and_welcome_names(self):
        persona = "说话像个急脾气的裁判。我有一个LV小包。"
        self.dialogue.configure("mock-key", None, persona)
        item = {**self.last, "prompt": "桌上那台手机？", "text": "我的 iPhone Duo。", "focusItem": "phone"}
        join = {**self.last, "source": "room_join", "text": "欢迎迎宾甲7781！"}
        for prompt, reply in (("这直播间有什么好玩的？", "你递个难题，我负责拆台。"),
                              ("我手机坏了，老板还让我把工单秒回。", "先让老板把那张维修单签了。"),
                              ("那我真去问？", "真去，叫他把承诺落在纸上。")):
            with self.subTest(prompt=prompt), patch.object(self.dialogue, "_json_reply", return_value={
                    "segments": [{"text": reply + "我的LV包可看不上这点排场。"}]}) as api:
                rows, mode = self.dialogue.plan({**self.task, "prompt": prompt}, [self.last, item, join])
                self.assertEqual((rows[0]["text"], mode), (reply, "deepseek"))
                messages = api.call_args.args[1]["messages"]
                self.assertIn("急脾气的裁判", messages[0]["content"])
                self.assertIn(prompt, messages[1]["content"])
                for unwanted in ("iPhone Duo", "LV", item["prompt"], self.last["text"], "迎宾甲7781", "account-817", "小林"):
                    self.assertNotIn(unwanted, str(messages))
        self.assertEqual(self.dialogue.status()["persona"], persona)
        old_brand_job = {**self.last, "source":"manual", "prompt":"我在LV店打工", "text":"LV门店还欠你钱？"}
        for context in (item, join, old_brand_job):
            with self.subTest(source=context["source"]), patch.object(self.dialogue, "_json_reply", return_value={
                    "line": "玫瑰靠边插，还得给我的包留个位。"}) as api:
                self.assertIsNone(self.dialogue.gift_line("玫瑰", context, "花留着。"))
                messages = api.call_args.args[1]["messages"]
                self.assertNotIn("刚聊的话题", messages[1]["content"])
                self.assertNotIn("iPhone Duo", str(messages))
                self.assertNotIn("LV", str(messages))
                self.assertNotIn("迎宾甲7781", str(messages))

    def test_generated_adverts_fall_back_but_personal_devices_and_brand_jobs_can_air(self):
        self.dialogue.configure("mock-key", None)
        for advert in ("看我桌上的小包。", "我手边那台折叠手机都比你会安排会议。", "左边手机右边包，你先挑个话题。"):
            with self.subTest(advert=advert), patch.object(self.dialogue, "_json_reply", return_value={
                    "segments": [{"text":advert}]}):
                rows, mode = self.dialogue.plan({**self.task, "prompt":"今晚又得加班。"}, [])
                self.assertEqual(mode, "fallback")
                self.assertNotIn(advert, "".join(r["text"] for r in rows))
        for prompt, reply in (("我手机欠费了还得回工单", "工单归老板，别让你的手机倒贴话费。"),
                              ("我在LV门店上班天天被催业绩", "LV门店的业绩指标，倒是准点下班啊。"),
                              ("新工作包吃包住怎么样", "包吃包住，还包不包加班费？"),
                              ("隔壁同事开会刷视频", "我的建议是把手机调静音，别替全公司选配乐。")):
            with self.subTest(prompt=prompt), patch.object(self.dialogue, "_json_reply", return_value={
                    "segments":[{"text":reply}]}):
                rows, mode = self.dialogue.plan({**self.task, "prompt":prompt}, [])
                self.assertEqual((mode, rows[0]["text"]), ("deepseek", reply))

    def test_explicit_callbacks_only_recall_the_same_account(self):
        other = {**self.last, "audience":"other", "prompt":"另一位同名者", "text":"绝密暗号。"}
        for prompt in ("你还记得我刚才说的事吗", "刚才那件事后来有下文了。", "要是他还是不肯呢？"):
            with self.subTest(prompt=prompt):
                self.dialogue.configure("mock-key", None)
                with patch.object(self.dialogue, "_json_reply", return_value={"segments":[{"text":"先叫他把房本拿来。"}]}) as api:
                    self.dialogue.plan({**self.task, "prompt":prompt}, [self.last, other])
                material = api.call_args.args[1]["messages"][1]["content"]
                self.assertIn(self.last["prompt"], material)
                self.assertNotIn(other["text"], material)

    def test_invalid_model_output_still_produces_a_performance(self):
        self.dialogue.configure("mock-key", None)
        with patch("host_dialogue.request.urlopen", return_value=io.BytesIO(b"{}")):
            segments, mode = self.dialogue.plan(self.task, [self.last])
        self.assertEqual(mode, "fallback")
        self.assertTrue(all(s["text"] and s["gesture"] and s["expression"] for s in segments))

    def test_incomplete_repetitive_and_breathless_drafts_get_a_specific_local_payoff(self):
        task = {**self.task, "source":"topic", "prompt":"部门每周都把周会开到半夜，讲完六张表还是一条结论都没出，你说我们这时间花得冤不冤？"}
        self.dialogue.configure("mock-key", None)
        for lines in (["嗯。"], ["滚！"], ["会议会议会议会议。快点快点快点快点快点。"],
                      ["第一，保持积极心态。第二，加强沟通交流。第三，做好时间管理。"],
                      ["等老板把今天要求登记的全部细节重新抄写到会议记录里面再考虑要不要把六个部门的三份审批文件重新印出来好逐条核实签字人的职位"]):
            with self.subTest(lines=lines), patch.object(self.dialogue, "_json_reply", return_value={
                    "segments":[{"text":line} for line in lines]}) as api:
                rows, mode = self.dialogue.plan(task, [])
                self.assertEqual(api.call_count, 1)
                self.assertEqual(mode, "fallback")
                self.assertIn("集体成果", rows[-1]["text"])
                spoken = "".join(r["text"] for r in rows)
                self.assertTrue(25 <= sum(c.isalnum() for c in spoken) <= 50)
                self.assertNotIn("LV", spoken)

    def test_complete_model_jokes_and_grounded_hooks_keep_their_own_words(self):
        self.dialogue.configure("mock-key", None)
        task = {**self.task, "prompt":"会议花了四个钟头"}
        good = "会议越开越长，工资条倒是学会压缩了。"
        last = "先给会议室装个打卡机吧，它天天下班比老板还晚。"
        long_setup = "为了开好这场会议大家先花了整整两个小时讨论要用什么方法研究下次会议可能需要展示的各类统计文件以及审批表格的个人签署要求。"
        for lines, expected in (([good], good), ([good] * 3, good), ([long_setup, last], last)):
            with self.subTest(lines=lines), patch.object(self.dialogue, "_json_reply", return_value={
                    "segments":[{"text":s} for s in lines]}):
                rows, mode = self.dialogue.plan(task, [])
                self.assertEqual((mode, "".join(r["text"] for r in rows)), ("deepseek", expected))
        hook = "加班费长脚了？"
        with patch.object(self.dialogue, "_json_reply", return_value={"segments":[{"text":hook}]}):
            rows, mode = self.dialogue.plan({**self.task, "prompt":"加班费和工资条不见了"}, [])
        self.assertEqual((mode, rows[0]["text"]), ("deepseek", hook))
        self.assertEqual(len(rows), 1)

    def test_detailed_reply_can_finish_three_points_without_clipping_the_payoff(self):
        self.dialogue.configure("mock-key", None)
        topic = ("老板周五刚说周末自愿，转身就让组长把不来的名字记下来。我又不想当场顶撞他。"
                 "详细讲讲，我该先问什么，他再拿团队精神压我怎么回，最后怎么收场？")
        lines = [
            "先让组长把报名和考勤分开写。正经报名表只问谁来，哪有专门统计缺席的。",
            "老板再讲团队精神，你就问这半天算调休还是算钱，叫他把答案写在通知底下。",
            "最后把自己的安排说清楚。你周末原来就有事，又没答应让人把休息日当公摊面积。",
        ]
        result = {"segments":[{"text":line, "expression":"smirk", "gesture":gesture}
                              for line, gesture in zip(lines, ("look", "lean", "point"))]}
        with patch.object(self.dialogue, "_json_reply", return_value=result) as api:
            rows, mode = self.dialogue.plan({**self.task, "source":"topic", "prompt":topic}, [])
        api.assert_called_once()
        self.assertEqual(mode, "deepseek")
        self.assertEqual([r["text"] for r in rows], lines)
        self.assertEqual([r["gesture"] for r in rows], ["look", "lean", "point"])
        spoken = "".join(r["text"] for r in rows)
        self.assertTrue(50 < sum(c.isalnum() for c in spoken) <= 140)

        endings = [
            "他如果坚持这是家庭聚会，那家人提议换个日子，总还有发言权吧。",
            "领导若改口说是紧急任务，就请他写明验收的人和具体的截止时间。",
            "等话讲到这里，再问一句实际干活的时间什么时候记在工资条上。",
        ]
        oversized = [line + ending for line, ending in zip(lines, endings)]
        self.assertGreater(sum(c.isalnum() for line in oversized for c in line), 150)
        with patch.object(self.dialogue, "_json_reply", return_value={"segments":[{"text":s} for s in oversized]}):
            rows, mode = self.dialogue.plan({**self.task, "source":"topic", "prompt":topic}, [])
        self.assertTrue(1 <= len(rows) <= 3)
        self.assertLessEqual(sum(c.isalnum() for row in rows for c in row["text"]), 150)
        if mode == "deepseek":
            sentences = {s for original in oversized for s in original.rstrip("。").split("。")}
            for row in rows:
                self.assertTrue(row["text"].endswith("。"), row["text"])
                for sentence in row["text"].rstrip("。").split("。"):
                    self.assertIn(sentence, sentences)

    def test_length_is_set_by_request_not_just_the_number_of_characters(self):
        self.dialogue.configure("mock-key", None)
        task = {**self.task, "prompt":"展开讲讲"}
        lines = [
            "把老板说的家人落实到纸上，先问清是算工时还是能分房。",
            "他要是把话题扯到奉献，你就请他从房本上挑个房间给你，别让茶水间冒充主卧。",
            "下回留下过夜前再问一句，水电归谁交。要你出房租的时候，老板可就想起来你是员工了。",
        ]
        with patch.object(self.dialogue, "_json_reply", return_value={"segments":[{"text":s} for s in lines]}) as api:
            rows, mode = self.dialogue.plan(task, [self.last])
        api.assert_called_once()
        material = api.call_args.args[1]["messages"][-1]["content"]
        self.assertIn(self.last["prompt"], material)
        self.assertEqual(mode, "deepseek")
        self.assertEqual([r["text"] for r in rows], lines)

        concise = "先问这半天算钱还是算调休。"
        task = {**self.task, "prompt":"老板打算把周末加班算成团建，还问大家为什么不来，要怎么安排。长话短说，我先问什么？"}
        with patch.object(self.dialogue, "_json_reply", return_value={"segments":[{"text":concise}]}) as api:
            rows, mode = self.dialogue.plan(task, [])
        api.assert_called_once()
        self.assertEqual((mode, [r["text"] for r in rows]), ("deepseek", [concise]))

    def test_daily_topics_keep_a_specific_payoff_offline_and_after_timeout(self):
        for prompt, anchors in (("老板说周六来公司全凭自愿，那我能不来吗？", ("自愿", "缺席", "请假")),
                                ("周末躺平两天好快乐", ("周末", "枕头", "躺", "休息")),
                                ("今天刚学会做蛋炒饭", ("蛋炒饭", "火候", "锅", "鸡蛋"))):
            task = {**self.task, "source":"topic", "prompt":prompt}
            with self.subTest(prompt=prompt):
                self.dialogue.configure("", None)
                local, _ = self.dialogue.plan(task, [])
                self.dialogue.configure("mock-key", None)
                with patch.object(self.dialogue, "_json_reply", side_effect=TimeoutError):
                    rows, mode = self.dialogue.plan(task, [])
                self.assertEqual((mode, rows), ("fallback", local))
                spoken = "".join(r["text"] for r in rows)
                self.assertTrue(any(w in spoken for w in anchors), spoken)
                if prompt.startswith(("周末", "今天")):
                    self.assertEqual(len(rows), 1)
                    self.assertTrue(4 <= sum(c.isalnum() for c in spoken) <= 28, spoken)
                else:
                    self.assertLessEqual(len(rows), 2)

    def test_gift_punchline_can_pick_up_the_topic_already_on_air(self):
        self.dialogue.configure("mock-key", None)
        response = {"choices": [{"message": {"content": json.dumps({"line": "花算你的，这个家得让老板掏首付。"})}}]}
        with patch("host_dialogue.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as network:
            line = self.dialogue.gift_line("玫瑰", self.last, "今天少带一根刺。")
        self.assertIn("首付", line)
        self.assertEqual(network.call_args.kwargs["timeout"], 2)
        material = json.loads(network.call_args.args[0].data)["messages"][-1]["content"]
        self.assertIn("玫瑰", material)
        self.assertIn(self.last["text"], material)
        self.assertNotIn(self.last["audience"], material)

    def test_default_persona_intercepts_fawning_on_both_paths_without_another_request(self):
        self.dialogue.configure("mock-key", None)
        result = {"segments": [{"text": "抱抱你，感谢你的支持。", "expression": "soft"}]}
        with patch.object(self.dialogue, "_json_reply", return_value=result) as api:
            rows, mode = self.dialogue.plan(self.task, [])
        self.assertEqual(api.call_count, 1)
        self.assertEqual(mode, "fallback")
        self.assertNotIn("抱抱你", "".join(r["text"] for r in rows))
        with patch.object(self.dialogue, "_json_reply", return_value={"line": "谢谢宝宝送来的跑车，爱你哟！"}):
            self.assertIsNone(self.dialogue.gift_line("跑车", {}, "司机都比你有脾气。"))
        reversal = "谢您抬举啊，连个日期都懒得编。"
        with patch.object(self.dialogue, "_json_reply", return_value={"line": reversal}):
            self.assertEqual(self.dialogue.gift_line("跑车", {}, "少跟我摆谱。"), reversal)

    def test_custom_persona_is_snapshot_for_replies_gifts_and_an_isolated_preview(self):
        self.dialogue.configure("mock-key", "live-model", "  反话留到最后三个字。 ")
        preview = self.dialogue.for_preview("先说一句快板。")
        self.assertEqual(self.dialogue.status()["persona"], "反话留到最后三个字。")
        self.assertEqual(preview.status()["model"], "live-model")
        custom = "抱抱你，先把想问的话说完，我等你。"
        with patch.object(preview, "_json_reply", return_value={"segments": [{"text": custom}]}) as network:
            rows, mode = preview.plan(self.task, [])
        self.assertEqual((mode, rows[0]["text"]), ("deepseek", custom))
        self.assertIn("先说一句快板。", network.call_args.args[1]["messages"][0]["content"])
        self.assertNotIn(DEFAULT_PERSONA, network.call_args.args[1]["messages"][0]["content"])
        with patch.object(self.dialogue, "_json_reply", return_value={"line": "钥匙你收好，我不考科二。"}) as network:
            self.assertTrue(self.dialogue.gift_line("跑车", {}, "客气什么？", opening="车停门口。"))
        messages = network.call_args.args[1]["messages"]
        self.assertIn("反话留到最后三个字。", messages[0]["content"])
        self.assertNotIn("刚聊的话题", messages[1]["content"])
        self.assertIn("车停门口。", messages[1]["content"])
        self.dialogue.configure(None, None, DEFAULT_PERSONA)
        self.assertEqual(self.dialogue.status()["persona"], self.dialogue.status()["defaultPersona"])

    def test_invalid_persona_never_partially_changes_model_or_credentials(self):
        before = self.dialogue.status()
        for invalid in (" ", "a" * (MAX_PERSONA_LENGTH + 1), "坏\x00输入", "坏\udfff输入", []):
            with self.assertRaises(ValueError):
                self.dialogue.configure("mock-key", "new-model", invalid)
            self.assertEqual(self.dialogue.status(), before)

    def test_old_result_does_not_refresh_new_personas_status(self):
        self.dialogue.configure("mock-key", None)

        def edit_while_in_flight(key, payload, timeout):
            self.assertIn(DEFAULT_PERSONA, payload["messages"][0]["content"])
            self.dialogue.configure(None, None, "轮到我来当裁判。")
            return {"segments": [{"text": "谢谢宝宝！"}]}

        with patch.object(self.dialogue, "_json_reply", side_effect=edit_while_in_flight):
            _, mode = self.dialogue.plan(self.task, [])
        self.assertEqual(mode, "fallback")
        self.assertEqual(self.dialogue.status()["mode"], "deepseek")
        self.assertEqual(self.dialogue.status()["message"], "")


if __name__ == "__main__":
    unittest.main()
