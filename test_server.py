import http.client
import io
import json
import socket
from threading import Event, Thread
import time
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from server import Handler, LocalServer, PCM_MEDIA_TYPE, PreviewBusy, Scheduler, validate, MAX_BODY, MAX_QUEUE, MAX_NICKNAME
from host_dialogue import Dialogue


def event(kind, stamp=None, **fields):
    data = {"content": "PRIVATE-COMMENT"} if kind == "comment" else {}
    return {"eventId": str(uuid.uuid4()), "roomId": "943959289826", "type": kind,
            "capturedAt": stamp or datetime.now(timezone.utc).isoformat(),
            "actor": {"nickname": "PRIVATE-ACTOR"}, "rawText": "PRIVATE-RAW", "data": data, **fields}


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer(0)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, value=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        headers = {} if headers is None else dict(headers)
        if value is not None:
            headers.setdefault("Content-Type", "application/json")
            value = json.dumps(value, ensure_ascii=False).encode("utf-8")
        conn.request(method, path, value, headers)
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def test_contract_validation_and_security(self):
        gift = event("gift")
        exact = {"schemaVersion": 1, "events": [gift]}
        self.assertEqual(self.request("POST", "/live-events", exact), (204, b""))
        self.assertEqual(self.request("POST", "/live-events", exact), (204, b""))
        state = json.loads(self.request("GET", "/api/state")[1])
        self.assertTrue(state["autoEnabled"])
        self.assertEqual(len(state["recent"]), 1)
        self.assertEqual(state["recent"][0]["nickname"], "PRIVATE-ACTOR")
        archive = json.loads(self.request("GET", "/api/archive?kind=events&limit=1")[1])
        self.assertEqual(archive["items"][0]["eventId"], gift["eventId"])
        self.assertIsNone(archive["nextCursor"])
        self.assertEqual(self.request("GET", "/api/archive?kind=events&view=stage")[0], 403)
        self.assertEqual(self.request("GET", "/api/archive?limit=0")[0], 400)
        self.assertNotIn("PRIVATE-RAW", str(state))
        self.assertEqual(json.loads(self.request("GET", "/api/state?view=stage")[1])["recent"], [])
        self.assertEqual(self.request("POST", "/live-events", dict(exact, schemaVersion=True))[0], 400)
        self.assertEqual(self.request("POST", "/live-events", exact, {"Origin":"https://example.org"})[0], 403)
        self.assertEqual(self.request("POST", "/api/control", {"action":"stop"}, {"Sec-Fetch-Site":"cross-site"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host":"fake.example"})[0], 403)
        self.assertEqual(self.request("POST", "/live-events", exact, {"Content-Length":str(MAX_BODY+1)})[0], 413)
        self.assertEqual(self.request("POST", "/api/tts", {"text":""})[0], 400)
        longest_welcome = "欢迎" + "豆" * MAX_NICKNAME
        with patch("server.speech_backend.wav", return_value=b"welcome") as speak:
            self.assertEqual(self.request("POST", "/api/tts", {"text": longest_welcome}), (200, b"welcome"))
            speak.assert_called_once_with(longest_welcome, None)

    def test_private_trial_routes_do_not_expose_persona_on_stage(self):
        scene = {"source":"comment", "text":"给你个面子"}
        self.assertEqual(self.request("POST", "/api/persona/preview?view=stage", scene)[0], 403)
        stage = {"Referer":f"http://127.0.0.1:{self.server.server_port}/stage.html"}
        self.assertEqual(self.request("POST", "/api/persona/preview", scene, stage)[0], 403)
        self.assertEqual(self.request("POST", "/api/control", {"action":"settings", "persona":"随便写"}, stage)[0], 403)
        self.assertNotIn("llm", json.loads(self.request("GET", "/api/state", headers=stage)[1]))
        status, data = self.request("POST", "/api/persona/preview", {**scene, "text":""})
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(data))

    def test_sse_updates_and_stop(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request("GET", "/api/stream")
        response = conn.getresponse()
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream; charset=utf-8")

        def read_state():
            self.assertEqual(response.readline().strip(), b"event: state")
            response.readline()
            data = json.loads(response.readline().decode().removeprefix("data: "))
            self.assertEqual(response.readline().strip(), b"")
            return data

        self.assertFalse(read_state()["stopped"])
        self.assertEqual(self.request("POST", "/api/control", {"action":"stop"})[0], 200)
        state = read_state()
        self.assertTrue(state["stopped"])
        self.assertFalse(state["autoEnabled"])
        self.assertIsNone(state["active"])
        self.assertEqual(state["queueDepth"], 0)
        self.assertEqual(self.request("POST", "/api/control", {"action":"auto","enabled":True})[0], 400)
        self.assertEqual(self.request("POST", "/api/control", {"action":"reset"})[0], 200)
        read_state()
        conn.close()

    def test_stage_can_claim_an_unplayed_cue_and_cannot_see_history(self):
        self.assertEqual(self.request("POST", "/api/control", {"action":"manual","cue":"talk","text":"existing cue"})[0], 200)
        until = time.monotonic()+1
        while self.server.scheduler.state()["active"] is None and time.monotonic() < until:
            time.sleep(.005)
        self.assertIsNotNone(self.server.scheduler.state()["active"])
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request("GET", "/api/stream?view=stage")
        response = conn.getresponse()
        self.assertEqual(response.readline().strip(), b"event: state")
        response.readline()
        state = json.loads(response.readline().decode().removeprefix("data: "))
        self.assertEqual(state["recent"], [])
        cue = state["active"]
        self.assertEqual(cue["status"], "ready")
        payload = {"id": cue["id"], "player": "stage-a", "phase": "start"}
        self.assertTrue(json.loads(self.request("POST", "/api/playback", payload)[1])["accepted"])
        self.assertFalse(json.loads(self.request("POST", "/api/playback", dict(payload, player="stage-b"))[1])["accepted"])
        self.assertEqual(self.request("POST", "/api/control", {"action":"stop"})[0], 200)
        self.assertEqual(self.request("POST", "/api/control", {"action":"reset"})[0], 200)
        conn.close()


class ServerStartupTest(unittest.TestCase):
    def test_port_conflict_preserves_socket_error_and_running_service(self):
        with LocalServer(0) as existing:
            with patch("server.speech_backend.shutdown") as voice_shutdown:
                with self.assertRaises(OSError):
                    with LocalServer(existing.server_port):
                        self.fail("two studios acquired the same live port")
                voice_shutdown.assert_not_called()
            self.assertFalse(existing.scheduler.closed)
        with socket.socket() as foreign:
            # Check a listening process with address reuse enabled, including on Windows.
            foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            foreign.bind(("127.0.0.1", 0))
            foreign.listen(1)
            with self.assertRaises(OSError):
                with LocalServer(foreign.getsockname()[1]):
                    self.fail("studio acquired a port owned by another listener")


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.s = Scheduler()
        self.s.dialogue.configure("", None)
        self.addCleanup(self.s.close)

    def active(self, timeout=3):
        with self.s.cv:
            self.assertTrue(self.s.cv.wait_for(lambda: self.s.active is not None, timeout))
            return self.s.state()["active"]

    def test_room_prop_can_be_previewed_pointed_at_and_recalled_by_its_viewer(self):
        self.s.dialogue.configure("mock-key", None)
        message = {"source": "comment", "text": "你桌上右边是什么？"}
        viewer = {"nickname": "小林", "userId": "private-room-viewer"}
        with patch.object(Dialogue, "_json_reply", side_effect=AssertionError("unexpected model call")):
            preview = self.s.preview(message)
            self.assertIn("monitor", [part.get("focusItem") for part in preview["segments"]])
            self.assertIsNone(self.s.state()["active"])
            self.ingest(event("comment", actor=viewer, data={"content": message["text"]}))
            monitor = self.active()
            self.assertIn("监视器", monitor["text"])
            self.assertIn("monitor", [part.get("focusItem") for part in monitor["segments"]])
            self.air(monitor)
            self.assertEqual(self.s.state()["history"][0]["focusItem"], "monitor")
            self.ingest(event("comment", actor=viewer, data={"content": "那另一边呢？"}))
            phone = self.active()
            self.assertIn("iPhone Duo", phone["text"])
            self.assertIn("phone", [part.get("focusItem") for part in phone["segments"]])

    def ack(self, cue, phase, player="stage-a", **fields):
        return self.s.playback({"id": cue["id"], "phase": phase, "player": player, **fields})

    def air(self, cue):
        self.assertTrue(self.ack(cue, "start"))
        for i in range(len(cue["segments"])):
            self.assertTrue(self.ack(cue, "segment", index=i))
            self.assertTrue(self.ack(cue, "segment_end", index=i))
        self.assertTrue(self.ack(cue, "complete"))

    def ingest(self, *rows):
        self.s.ingest(validate({"schemaVersion": 1, "events": list(rows)}))

    def test_quick_comment_retry_and_second_stage_only_produce_one_spoken_cue(self):
        self.s.dialogue.configure("mock-key", None)
        comment = event("comment", actor={"nickname": "小林"}, data={"content": "哈哈哈"})
        choose = {"action": "reply", "roomId": comment["roomId"], "eventId": comment["eventId"]}
        with patch.object(self.s.dialogue, "plan") as plan:
            self.ingest(comment, comment)
            cue = self.active()
            self.assertEqual((cue["planner"], len(cue["segments"])), ("local", 1))
            self.assertEqual(cue["replyTarget"], {"name": "小林", "text": "哈哈哈"})
            self.s.control(choose)
            self.assertTrue(self.ack(cue, "start"))
            self.assertFalse(self.ack(cue, "start", player="second-stage"))
            self.assertTrue(self.ack(cue, "segment", index=0))
            self.assertTrue(self.ack(cue, "segment_end", index=0))
            self.assertTrue(self.ack(cue, "complete"))
            self.ingest(comment)
            self.s.control(choose)
            state = self.s.state()
            self.assertEqual((state["active"], state["queue"], len(state["recent"])), (None, [], 1))
            self.assertEqual([(r["id"], r["text"]) for r in state["history"]], [(cue["id"], cue["text"])])
            # The same viewer can send the same words again as an independent event.
            self.ingest(event("comment", actor=comment["actor"], data=comment["data"]))
            another = self.active()
            self.assertNotEqual(another["id"], cue["id"])
            self.air(another)
            self.assertEqual(len(self.s.state()["history"]), 2)
            plan.assert_not_called()

    def test_selected_quip_topic_and_private_trial_can_all_bypass_a_busy_model(self):
        self.s.dialogue.configure("mock-key", None)
        self.s.control({"action": "auto", "enabled": False})
        row = event("comment", actor={"nickname": "阿雨"}, data={"content": "哈哈哈"})
        with patch.object(Dialogue, "plan") as plan:
            self.ingest(row)
            select = {"action": "reply", "roomId": row["roomId"], "eventId": row["eventId"]}
            self.s.control(select)
            comment = self.active()
            self.assertEqual((comment["source"], len(comment["segments"])), ("comment", 1))
            self.air(comment)
            self.s.control({"action": "topic", "text": "哈哈哈", "name": "小林"})
            topic = self.active()
            self.assertEqual((topic["source"], len(topic["segments"])), ("topic", 1))
            self.air(topic)
            with self.s.preview_slot:
                preview = self.s.preview({"source": "comment", "text": "哈哈哈"})
            self.assertEqual((preview["mode"], len(preview["segments"])), ("local", 1))
            plan.assert_not_called()

    def test_only_ready_quips_can_use_the_idle_mic_while_another_viewer_waits(self):
        self.s.dialogue.configure("mock-key", None)
        began, release = Event(), Event()
        def slow(*args):
            began.set()
            release.wait(4)
            return [{"text": "车费别替老板垫。", "gesture": "point", "expression": "smirk"}], "deepseek"
        def chat(viewer, text):
            return event("comment", actor={"nickname": viewer}, data={"content": text})
        with patch.object(self.s.dialogue, "plan", side_effect=slow) as plan, patch("server.COMMENT_BURST_GAP", .03):
            self.ingest(chat("阿林", "老板把整组的打车费都记在我一个人头上。"))
            try:
                self.assertTrue(began.wait(1))
                self.ingest(chat("阿林", "哈哈哈"), chat("小鱼", "哈哈哈"))
                brief = self.active()
                self.assertEqual((brief["planner"], brief["name"]), ("local", "小鱼"))
                time.sleep(.05)  # The fourth viewer arrives outside the burst detection window.
                self.ingest(chat("小陈", "哈哈哈"))
            finally:
                release.set()
            with self.s.cv:
                self.assertTrue(self.s.cv.wait_for(lambda: self.s.planning is None, 2))
            self.air(brief)
            answered = self.active()
            self.assertEqual((answered["planner"], answered["name"]), ("deepseek", "阿林"))
            self.air(answered)
            for name in ("阿林", "小陈"):
                waiting = self.active()
                self.assertEqual((waiting["planner"], waiting["name"]), ("local", name))
                self.air(waiting)
            plan.assert_called_once()

    def test_room_join_uses_one_fixed_local_greeting_per_real_event(self):
        self.s.dialogue.configure("mock-key", None, "见谁都多骂一句。")
        named = event("room_join", actor={"nickname": " 小林 ", "userId": "private-id"}, data={"displayCount": 6})
        second = event("room_join", actor={"nickname": "阿月"})
        anonymous = event("room_join", actor=None)
        crowd = event("room_join", actor=None, data={"displayCount": 20, "countText": "20人"})
        with patch.object(self.s.dialogue, "plan") as model:
            self.ingest(named, named, second, anonymous, crowd)
            for expected in ("欢迎小林", "欢迎阿月", "欢迎"):
                cue = self.active()
                self.assertEqual((cue["source"], cue["text"]), ("room_join", expected))
                self.assertEqual([part["text"] for part in cue["segments"]], [expected])
                self.assertNotIn("private-id", str(cue))
                self.air(cue)
            model.assert_not_called()
        self.s.control({"action": "auto", "enabled": False})
        self.ingest(event("room_join", actor={"nickname": "下一个"}))
        state = self.s.state()
        self.assertEqual(len(state["recent"]), 5)
        self.assertEqual([row["status"] for row in state["recent"][:2]], ["ignored", "ignored"])
        self.assertEqual((state["active"], state["queueDepth"]), (None, 0))

    def test_welcome_burst_makes_room_for_recent_arrivals_and_commentary(self):
        names = [f"观众{i:02}" for i in range(MAX_QUEUE + 1)]
        with self.s.cv:
            self.ingest(*(event("room_join", actor={"nickname": name}) for name in names))
            self.ingest(event("comment"), event("gift", data={"giftName": "玫瑰"}))
            state = self.s.state()
            self.assertEqual(state["queueDepth"], MAX_QUEUE)
            self.assertEqual([task["source"] for task in state["queue"][:2]], ["gift", "comment"])
            self.assertEqual([task["name"] for task in state["queue"][2:]], names[3:])
            self.assertEqual({r["nickname"] for r in state["recent"] if r["status"] == "busy"}, set(names[:3]))
            self.assertEqual(len(state["recent"]), MAX_QUEUE + 3)

    def test_stale_welcomes_expire_without_entering_spoken_history(self):
        self.s.control({"action": "manual", "text": "还没说完。"})
        blocking = self.active()
        with patch("server.WELCOME_LIFETIME", .04):
            self.ingest(event("room_join"))
            with self.s.cv:
                self.assertTrue(self.s.cv.wait_for(lambda: not self.s.queue, 2))
                self.assertEqual(self.s.state()["recent"][0]["status"], "expired")
            self.air(blocking)
            self.ingest(event("room_join"))
            # A disconnected stage misses this greeting even if the cue was already ready.
            with self.s.cv:
                self.assertTrue(self.s.cv.wait_for(lambda: self.s.state()["recent"][0]["status"] == "expired", 2))
        self.assertEqual([r["source"] for r in self.s.state()["history"]], ["manual"])

    def test_queue_priority_dedup_gift_merge_and_privacy(self):
        rose = lambda t,n: event("gift", "2026-11-15T12:30:0" + str(t) + ".000Z", data={"giftName":"玫瑰", "displayCount":n})
        first, second = rose(1, 1), rose(2, 5)
        self.s.control({"action": "auto", "enabled": True})
        with self.s.cv:
            self.ingest(second, first, second, event("comment"), event("like"), event("like"), event("room_join"))
            self.s.control({"action":"manual","cue":"heart","expression":"happy"})
            state = self.s.state()
            self.assertEqual([t["source"] for t in state["queue"]], ["manual", "gift", "comment", "room_join", "like"])
            self.assertEqual(state["queue"][1]["giftCount"], 5)
            self.assertEqual(state["giftFx"]["count"], 5)
            self.assertEqual(len(state["recent"]), 7)  # Six collector rows and the director's manual cue.
            self.assertNotIn("PRIVATE-RAW", str(state))
            self.assertNotIn("PRIVATE-COMMENT", str(self.s.state(stage=True)))
        cue = self.active()
        self.assertEqual(cue["cue"], "heart")
        self.air(cue)
        self.assertFalse(self.ack(cue, "complete"))
        state = self.s.control({"action":"stop"})
        self.assertIsNone(state["active"])
        self.assertEqual(state["queueDepth"], 0)
        self.assertFalse(state["autoEnabled"])

    def test_topic_gift_and_followup_are_grounded_in_played_words(self):
        self.s.control({"action":"submit", "text":"老板说公司就是我第二个家。", "name":"小林"})
        topic = self.active()
        self.assertEqual(topic["source"], "topic")
        self.assertIn("几平", topic["text"])
        self.assertTrue(self.ack(topic, "start"))
        self.assertFalse(self.ack(topic, "start", player="other"))
        self.assertFalse(self.ack(topic, "complete", player="other"))
        self.assertTrue(self.ack(topic, "segment", index=0))
        self.s.control({"action":"auto","enabled": True})
        gift = event("gift", actor={"nickname":"小林","openId":"private-account"}, data={"giftName":"加油鸭","displayCount":1})
        followup = event("comment", actor=gift["actor"], data={"content":"那我真去问？"})
        self.ingest(gift, followup)
        self.assertEqual(self.active()["id"], topic["id"])
        self.assertEqual(self.s.state(stage=True)["giftFx"]["effect"], "duck")
        self.assertEqual(self.s.state()["history"], [])
        # A real segment is still playing. Only its player's actual completion can release it.
        time.sleep(.7)
        self.assertTrue(self.ack(topic, "segment_end", index=0))
        self.assertTrue(self.ack(topic, "complete"))
        show = self.active()
        self.assertEqual(show["giftId"], "duck")
        self.assertIn("第二个家", show["text"])
        self.assertIn("抢麦", show["text"])
        self.air(show)
        reply = self.active()
        self.assertEqual(reply["eventId"], followup["eventId"])
        self.assertIn("第二个家", reply["text"])
        self.air(reply)
        state = self.s.state()
        self.assertEqual([t["source"] for t in state["history"]], ["comment","gift","topic"])
        self.assertNotIn("private-account", str(state))

    def test_skip_retains_only_confirmed_segments(self):
        self.ingest(event("gift", data={"giftName": "玫瑰", "displayCount": 2}))
        cue = self.active()
        self.assertTrue(self.ack(cue,"start"))
        self.assertTrue(self.ack(cue,"segment",index=0))
        self.assertFalse(self.ack(cue,"complete"))
        self.assertTrue(self.ack(cue,"segment_end",index=0))
        self.assertTrue(self.ack(cue,"segment",index=1))
        self.s.control({"action":"skip"})
        self.assertFalse(self.ack(cue,"complete"))
        self.assertEqual(self.s.state()["history"][0]["text"], cue["segments"][0]["text"])

    def test_director_can_select_one_comment_in_manual_mode(self):
        self.s.control({"action":"auto", "enabled":False})
        row = event("comment")
        self.ingest(row)
        self.assertIsNone(self.s.state()["active"])
        control = {"action": "reply", "eventId": row["eventId"], "roomId": row["roomId"]}
        with self.s.cv:
            self.s.control(control)
            self.s.control(control)
            self.assertEqual(len(self.s.queue), 1)
        cue = self.active()
        self.air(cue)
        self.s.control(control)
        self.assertEqual(self.s.state()["queueDepth"], 0)

    def test_compact_collector_and_active_combo_updates(self):
        self.s.control({"action":"auto", "enabled":True})
        raw = {"eventId":"rose-1", "roomId":"opening-night", "type":"gift","actor":{"nickname":"观众"},
               "data":{"giftName":"玫瑰","displayCount":1}}
        self.s.ingest(validate(raw))
        cue = self.active()
        self.assertTrue(self.ack(cue,"start"))
        later = {**raw,"eventId":"rose-2","data":{**raw["data"], "displayCount":10}}
        self.s.ingest(validate([later, later]))
        self.assertEqual(self.s.state()["queueDepth"], 0)
        self.assertEqual(self.s.state()["active"]["giftCount"], 10)
        self.assertEqual(self.s.state()["giftFx"]["count"], 10)

    def test_delayed_model_reply_cannot_reappear_after_stop(self):
        began, release = Event(), Event()
        original = self.s.dialogue.plan
        def delayed(task, history):
            began.set()
            release.wait(3)
            return original(task, history)
        self.s.dialogue.plan = delayed
        self.s.control({"action":"submit", "text":"第一条投稿"})
        self.assertTrue(began.wait(1))
        self.s.control({"action":"stop"})
        self.s.control({"action":"reset"})
        self.s.control({"action":"manual","text":"现在开麦了。"})
        current = self.active()
        # Delayed director clicks also target their original act, never the new one.
        self.s.control({"action":"skip", "id": current["id"] - 1})
        self.assertEqual(self.s.state()["active"]["id"], current["id"])
        release.set()
        with self.s.cv:
            self.assertTrue(self.s.cv.wait_for(lambda: self.s.planning is None, 1))
        self.air(current)
        self.assertEqual(self.s.state()["queue"], [])
        self.assertEqual([r["text"] for r in self.s.state()["history"]], ["现在开麦了。"])

    def test_pending_model_shows_selected_prompt_then_falls_back_on_deadline(self):
        began, release = Event(), Event()
        def delayed(*args):
            began.set()
            release.wait(2)
            return [{"text":"迟到的回复", "gesture":"talk", "expression":"smirk"}], "deepseek"
        with patch.object(self.s.dialogue, "plan", delayed), patch("server.COMMENT_PLAN_BUDGET", .15):
            try:
                self.s.control({"action":"submit", "text":"今晚有人把加班说成福利。", "name":"小林"})
                self.assertTrue(began.wait(1))
                stage = self.s.state(stage=True)
                self.assertEqual(stage["preparing"]["name"], "小林")
                self.assertEqual(stage["received"]["cueId"], stage["preparing"]["id"])
                self.assertEqual(self.s.state()["history"], [])
                cue = self.active()
                self.assertEqual(cue["planner"], "fallback")
                self.assertNotIn("迟到的回复", cue["text"])
                self.assertIsNone(self.s.state(stage=True)["preparing"])
            finally:
                release.set()
            self.air(cue)
            self.assertEqual(self.s.state()["history"][0]["text"], cue["text"])

    def test_gift_first_beat_immediate_and_finalized_tail_is_idempotent(self):
        self.s.control({"action":"manual", "text":"这场会从三点开到下班。"})
        self.air(self.active())
        self.s.control({"action":"auto","enabled":True})
        self.s.dialogue.configure("test-key", None)
        began, release = Event(), Event()
        punchline = "礼物都到了，会议纪要呢？"
        def slow_tail(*args):
            began.set()
            release.wait(2)
            return punchline
        with patch.object(self.s.dialogue, "gift_line", slow_tail):
            try:
                self.ingest(event("gift", data={"giftName":"玫瑰","displayCount":1}))
                self.assertTrue(began.wait(1))
                cue = self.active(.3)
                self.assertTrue(cue["tailPending"])
                self.assertTrue(self.ack(cue,"start"))
            finally:
                release.set()
            with self.s.cv:
                self.assertTrue(self.s.cv.wait_for(lambda: self.s.refining_gift is None, 1))
            command = {"id":cue["id"], "phase":"segment","index":0,"player":"stage-a","acceptNextSegment":True}
            for _ in range(2):
                response = {}
                self.assertTrue(self.s.playback(command, response))
                self.assertEqual(response["nextSegment"]["text"], punchline)
            self.assertFalse(self.s.state()["active"]["tailPending"])
            self.assertTrue(self.ack(cue,"segment",index=1))
            self.assertTrue(self.ack(cue,"complete"))
            self.assertTrue(self.s.state()["history"][0]["text"].endswith(punchline))

    def test_gift_rewrite_can_land_during_the_opener_but_never_after_commit(self):
        self.s.dialogue.configure("test-key", None)
        for ordinal, (finish, model_arrived) in enumerate((("segment", True), ("segment_end", True), ("segment_end", False))):
            with self.subTest(finish=finish, model_arrived=model_arrived):
                began, release = Event(), Event()
                def delayed(*args):
                    began.set()
                    release.wait(2)
                    return "花收了，麦还在我手上。"
                with patch.object(self.s.dialogue, "gift_line", delayed):
                    try:
                        # Distinct collector timestamps keep these independent one-off gifts out of combo dedup.
                        self.ingest(event("gift", f"2026-11-15T12:30:0{ordinal}Z", data={"giftName":"玫瑰", "displayCount":1}))
                        self.assertTrue(began.wait(1))
                        cue = self.active()
                        self.assertTrue(self.ack(cue, "start"))
                        base = cue["segments"][1]
                        message = {"id":cue["id"], "player":"stage-a", "index":0}
                        def ack(phase, accept, defer=False):
                            result = {}
                            self.assertTrue(self.s.playback(dict(message, phase=phase, acceptNextSegment=accept,
                                                                 deferNextSegment=defer), result))
                            return result
                        self.assertEqual(ack("segment", True, True), {"nextSegment":base, "tailPending":True})
                        if model_arrived:
                            release.set()
                            with self.s.cv:
                                self.assertTrue(self.s.cv.wait_for(lambda:self.s.refining_gift is None, 1))
                        fixed = ack(finish, finish == "segment")
                        self.assertFalse(fixed["tailPending"])
                        self.assertEqual(fixed["nextSegment"]["text"],
                                         "花收了，麦还在我手上。" if finish == "segment" else base["text"])
                    finally:
                        release.set()
                    with self.s.cv:
                        self.assertTrue(self.s.cv.wait_for(lambda:self.s.refining_gift is None, 1))
                    # Relayed/retried first-segment ACKs cannot replace whatever the stage has prepared.
                    self.assertEqual(ack("segment_end", False), fixed)
                    self.assertEqual(ack("segment", True, True), fixed)
                    self.assertTrue(self.ack(cue, "segment", index=1))
                    self.assertTrue(self.ack(cue, "complete"))

    def test_speech_rate_changes_independently_while_stopped(self):
        initial = self.s.state()["voice"]["rate"]
        self.addCleanup(self.s.control, {"action":"speech_rate", "rate":initial})
        self.s.control({"action":"stop"})
        state = self.s.control({"action":"speech_rate", "rate":1.35})
        self.assertTrue(state["stopped"])
        self.assertEqual(state["voice"]["rate"], 1.35)
        for bad in (True, 0, 1.7, "fast"):
            with self.assertRaises(ValueError):
                self.s.control({"action":"speech_rate", "rate":bad})

    def test_gift_trial_and_live_keep_the_local_punchline_if_rewrite_is_unusable(self):
        trial = {"source": "gift", "giftName": "玫瑰", "giftCount": 3}
        local = self.s.preview(trial)["segments"]
        self.s.dialogue.configure("mock-key", None)
        replies = [{"line": "哦！！！"}, {"line": "谁叫你给花安排开场白的？" * 7}]
        with patch.object(Dialogue, "_json_reply", side_effect=replies) as model:
            preview = self.s.preview(trial)
            self.assertEqual((preview["mode"], preview["segments"]), ("fallback", local))
            self.ingest(event("gift", actor={"nickname": "小林"}, data={"giftName": "玫瑰", "displayCount": 3}))
            cue = self.active()
            self.assertIn("小林，3份玫瑰", cue["segments"][0]["text"])
            self.assertTrue(self.ack(cue, "start"))
            with self.s.cv:
                self.assertTrue(self.s.cv.wait_for(lambda: self.s.refining_gift is None, 2))
            accepted = {}
            self.assertTrue(self.s.playback({"id": cue["id"], "phase": "segment", "index": 0,
                                            "player": "stage-a", "acceptNextSegment": True}, accepted))
            self.assertEqual(accepted["nextSegment"], local[-1])
            self.assertEqual(model.call_count, 2)

    def test_preview_uses_unsaved_direction_and_never_mutates_live_state(self):
        self.s.dialogue.configure("test-key", None, "这是保存的人设")
        saved = self.s.state()
        writes = self.s.store.db.total_changes
        direction = "这是草稿的独家起手式"
        punctuality = "叫他发个定位，我看看他这一天挪了几步。"
        calls = []
        def model(key, payload, timeout):
            calls.append(payload)
            if '"line"' in payload["messages"][0]["content"]:
                return {"line":"排场挺大，话筒还是我的。"}
            return {"segments":[{"text": punctuality, "gesture":"lean", "expression":"smirk"}]}
        with patch.object(Dialogue, "_json_reply", staticmethod(model)):
            trial = self.s.preview({"source":"comment", "text":"今天等了整天", "persona":direction})
            gift = self.s.preview({"source":"gift", "giftName":"玫瑰", "giftCount":3, "persona":direction})
        self.assertEqual((trial["mode"], gift["mode"]), ("deepseek", "deepseek"))
        self.assertEqual("".join(part["text"] for part in trial["segments"]), punctuality)
        self.assertEqual(gift["segments"][-1]["text"], "排场挺大，话筒还是我的。")
        self.assertIn("玫瑰", gift["segments"][0]["text"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(direction in c["messages"][0]["content"] for c in calls))
        self.assertEqual(self.s.state(), saved)
        self.assertEqual(self.s.store.db.total_changes, writes)

    def test_stalled_private_trial_cannot_hold_the_live_queue(self):
        began, release = Event(), Event()
        self.s.dialogue.configure("test-key", None)
        def slow(*args, **kwargs):
            began.set()
            release.wait(3)
            raise OSError("offline")
        trial = {"source":"comment", "text":"整天迟到"}
        with patch.object(Dialogue, "_json_reply", staticmethod(slow)), patch("server.COMMENT_PLAN_BUDGET", .04):
            try:
                response = self.s.preview(trial)
                self.assertTrue(began.is_set())
                self.assertEqual(response["mode"], "fallback")
                with self.assertRaises(PreviewBusy):
                    self.s.preview(trial)
                self.s.control({"action":"manual", "text":"现在开麦。"})
                self.assertEqual(self.active(.5)["text"], "现在开麦。")
            finally:
                release.set()

    def test_save_while_planning_discards_unsent_old_material(self):
        began, release = Event(), Event()
        def plan(task, history):
            persona = self.s.dialogue.status()["persona"]
            if not began.is_set():
                began.set()
                release.wait(2)
            return [{"text":persona[:24], "gesture":"lean", "expression":"smirk"}], "deepseek"
        with patch.object(self.s.dialogue, "plan", plan):
            self.s.control({"action":"submit", "text":"现在试麦"})
            try:
                self.assertTrue(began.wait(1))
                self.s.control({"action":"settings", "persona":"重新写过的台本"})
            finally:
                release.set()
            self.assertEqual(self.active()["text"], "重新写过的台本")


class LocalWire:
    """Two byte streams drive the same HTTP parser without binding a client socket."""
    def __init__(self, incoming):
        self.input = io.BytesIO(incoming)
        self.output = io.BytesIO()

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.write(data)

    def settimeout(self, timeout):
        pass


class SpeechHTTPTest(unittest.TestCase):
    def setUp(self):
        self.server = LocalServer(0)
        self.addCleanup(self.server.server_close)

    def wire(self, accept=PCM_MEDIA_TYPE):
        payload = b'{"text":"test","requestId":"test-voice"}'
        headers = (f"POST /api/tts HTTP/1.1\r\nHost: localhost:{self.server.server_port}\r\nConnection: close\r\n"
                   f"Content-Type: application/json\r\nAccept: {accept}\r\nContent-Length: {len(payload)}\r\n\r\n")
        return LocalWire(headers.encode("ascii") + payload)

    def handle(self, wire):
        Handler(wire, ("127.0.0.1", 1), self.server)

    def response(self, wire):
        result = http.client.HTTPResponse(LocalWire(wire.output.getvalue()))
        result.begin()
        return result

    def test_first_pcm_block_flushed_before_generation_finishes(self):
        first, second = bytes(range(16)), bytes(range(16, 28))
        more, release = Event(), Event()
        def chunks(*args):
            yield first
            more.set()
            release.wait(1)
            yield second
        wire = self.wire()
        with patch("speech_backend.pcm_chunks", chunks, create=True):
            thread = Thread(target=self.handle, args=(wire,))
            thread.start()
            try:
                self.assertTrue(more.wait(1))
                self.assertIn(first, wire.output.getvalue())
                self.assertNotIn(second, wire.output.getvalue())
            finally:
                release.set()
                thread.join(2)
        response = self.response(wire)
        self.assertEqual(response.getheader("Content-Type"), PCM_MEDIA_TYPE)
        self.assertTrue(response.chunked)
        self.assertEqual(response.read(), first + second)

    def test_interrupted_pcm_stream_is_not_marked_complete(self):
        def broken(*args):
            yield bytes(range(16))
            raise RuntimeError("synthesis interrupted")
        with patch("speech_backend.pcm_chunks", broken, create=True):
            wire = self.wire()
            self.handle(wire)
        with self.assertRaises(http.client.IncompleteRead):
            self.response(wire).read()

    def test_stop_after_first_audio_truncates_stream_and_releases_worker(self):
        released = Event()
        def interrupted(*args):
            try:
                yield b"first-audio"
                self.server.scheduler.control({"action":"stop"})
                yield b"obsolete-audio"
            finally:
                released.set()
        with patch("speech_backend.pcm_chunks", interrupted):
            wire = self.wire()
            self.handle(wire)
        self.assertTrue(released.is_set())
        self.assertNotIn(b"obsolete-audio", wire.output.getvalue())
        with self.assertRaises(http.client.IncompleteRead):
            self.response(wire).read()

    def test_missing_audio_before_first_block_and_legacy_wav(self):
        with patch("speech_backend.pcm_chunks", return_value=(b for b in ()), create=True):
            wire = self.wire()
            self.handle(wire)
            self.assertEqual(self.response(wire).status, 503)
        with patch("speech_backend.wav", return_value=b"RIFF-test"):
            wire = self.wire("audio/wav")
            self.handle(wire)
        result = self.response(wire)
        self.assertEqual(result.read(), b"RIFF-test")
        self.assertEqual(result.getheader("Content-Type"), "audio/wav")


if __name__ == "__main__":
    unittest.main()
