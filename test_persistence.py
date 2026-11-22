"""Use a disposable database and real process restart for the broadcast archive."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from server import LocalServer, Scheduler, validate
from host_dialogue import DEFAULT_PERSONA
import speech_backend
from studio_secrets import KeyProtectionError
from studio_store import studio_path


def comment(number, room="A"):
    return {"eventId": str(number), "type": "comment", "roomId": room,
            "actor": {"nickname": "小豆", "userId": "private-viewer-123"},
            "data": {"content": f"这条弹幕编号 {number}。"}, "rawText": "private-collector-line"}


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "room.sqlite3"
        self.addCleanup(speech_backend.shutdown)

    def open(self):
        studio = Scheduler(data_path=self.data)
        self.addCleanup(studio.close)
        return studio

    def active(self, studio):
        with studio.cv:
            self.assertTrue(studio.cv.wait_for(lambda: studio.active is not None, 3))
            return studio.state()["active"]

    def test_durable_events_room_dedup_and_archive_selection(self):
        studio = self.open()
        self.assertTrue(studio.auto)
        studio.control({"action": "auto", "enabled": False})
        studio.ingest(validate([comment(i) for i in range(80)]))
        studio.ingest(validate([comment(0), comment(0, "B")]))
        studio.close()
        studio = self.open()
        studio.ingest(validate(comment(0)))
        state = studio.state()
        self.assertFalse(state["autoEnabled"])
        self.assertEqual((state["active"], state["queueDepth"]), (None, 0))
        self.assertNotIn("archiveBefore", studio.state(stage=True))
        self.assertEqual(len(state["recent"]), 60)
        older = studio.archive("events", state["archiveBefore"]["events"])
        self.assertIsNone(older["nextCursor"])
        self.assertEqual(len(older["items"]), 21)
        self.assertEqual(len({r["archiveId"] for r in state["recent"] + older["items"]}), 81)
        self.assertNotIn("private-", str(older))
        stage = studio.control({"action": "reply", "roomId": "A", "eventId": "0"})
        cue = self.active(studio)
        self.assertEqual(cue["replyTarget"], {"name": "小豆", "text": comment(0)["data"]["content"]})
        self.assertNotIn("private-", str(stage))
        for path in self.data.parent.glob("room.sqlite3*"):
            self.assertNotIn(b"private-viewer-123", path.read_bytes())
            self.assertNotIn(b"private-collector-line", path.read_bytes())

    def test_crash_recovers_only_confirmed_words_without_replaying_queue(self):
        program = (
            "import os,sys; from server import Scheduler; "
            "s=Scheduler(data_path=sys.argv[1]); s.dialogue.configure('',None); "
            "s.control({'action':'submit','text':'我准备找老板谈加薪，怎么开口？他不同意又怎么办？展开讲讲。','name':'小豆'}); "
            "s.cv.acquire(); assert s.cv.wait_for(lambda:s.active,3); "
            "t=s.active; ack=lambda phase,**kw: s.playback(dict(id=t['id'],player='old',phase=phase,**kw)); "
            "assert len(t['segments'])>1; assert ack('start') and ack('segment',index=0) and ack('segment_end',index=0); "
            "s.control({'action':'manual','text':'这条不该在重启时播出'}); "
            "print(t['segments'][0]['text'],flush=True); os._exit(0)"
        )
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", program, str(self.data)],
                                capture_output=True, encoding="utf-8", check=True, timeout=10)
        recovered = self.open()
        state = recovered.state()
        self.assertIsNone(state["active"])
        self.assertIsNone(state["received"])
        self.assertEqual(state["queue"], [])
        self.assertEqual([r["status"] for r in state["recent"]], ["interrupted", "interrupted"])
        self.assertEqual([(r["text"], r["status"]) for r in state["history"]],
                         [(result.stdout.strip(), "interrupted")])
        recovered.control({"action": "manual", "text": "这是新任务"})
        active = self.active(recovered)
        self.assertGreater(active["id"], max(r["cueId"] for r in state["recent"]))
        self.assertFalse(recovered.playback({"id": state["recent"][0]["cueId"], "phase": "start", "player": "old"}))

    def test_saved_preferences_secret_and_explicit_clear(self):
        encrypted = "dpapi-v1:opaque-for-test"
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "from-env"}), \
             patch("server.protect_key", return_value=encrypted) as protect, \
             patch("server.unprotect_key", return_value="test-explicit-token"):
            one = self.open()
            one.control({"action": "settings", "apiKey": "test-explicit-token", "model": "test-model"})
            one.control({"action": "speech_rate", "rate": 1.35})
            one.control({"action": "stop"})
            protect.assert_called_once_with("test-explicit-token")
            one.close()
            for file in self.data.parent.glob("room.sqlite3*"):
                self.assertNotIn(b"test-explicit-token", file.read_bytes())
                self.assertNotIn(b"from-env", file.read_bytes())
            two = self.open()
            state = two.state()
            self.assertTrue(state["llm"]["keySaved"])
            self.assertTrue(state["stopped"])
            self.assertFalse(state["autoEnabled"])
            self.assertEqual(state["voice"]["rate"], 1.35)
            self.assertEqual(two.dialogue.key, "test-explicit-token")
            self.assertEqual(state["llm"]["model"], "test-model")
            public = json.dumps(state)
            self.assertNotIn("test-explicit-token", public)
            self.assertNotIn(encrypted, public)
            two.control({"action": "settings", "model": "test-next"})
            self.assertTrue(two.state()["llm"]["keySaved"])
            two.control({"action": "settings", "apiKey": ""})
            self.assertEqual(two.dialogue.key, "from-env")
            two.close()
            three = self.open()
            self.assertFalse(three.state()["llm"]["keySaved"])
            self.assertEqual(three.dialogue.key, "from-env")
            with patch("server.protect_key", side_effect=KeyProtectionError("unavailable")):
                ui = three.control({"action": "settings", "apiKey": "temporary-only"})
            self.assertFalse(ui["llm"]["keySaved"])
            self.assertTrue(ui["llm"]["keyNotice"])
            self.assertEqual(three.dialogue.key, "temporary-only")

    def test_persona_survives_restart_and_default_reset_follows_the_shipped_script(self):
        studio = self.open()
        studio.control({"action":"settings", "persona":"  嘴上嫌弃，包袱落在细节。  "})
        studio.control({"action":"settings", "model":"test-model"})
        self.assertNotIn("嘴上嫌弃", str(studio.state(stage=True)))
        studio.close()
        studio = self.open()
        self.assertEqual(studio.state()["llm"]["persona"], "嘴上嫌弃，包袱落在细节。")
        for value in (None, " ", ["偏题"], "太" * (studio.state()["llm"]["personaMaxLength"] + 1)):
            with self.assertRaises(ValueError):
                studio.control({"action":"settings", "persona":value, "model":"must-not-save"})
        self.assertEqual(studio.state()["llm"]["model"], "test-model")
        studio.control({"action":"settings", "persona":DEFAULT_PERSONA})
        self.assertNotIn("persona", studio.store.settings())
        studio.close()
        self.assertEqual(self.open().state()["llm"]["persona"], DEFAULT_PERSONA)

    def test_earlier_broadcast_pages_and_in_progress_visibility(self):
        studio = self.open()
        for n in range(35):
            studio.control({"action": "manual", "text": f"完成第 {n} 句"})
            cue = self.active(studio)
            for phase in ("start", "segment", "segment_end"):
                self.assertTrue(studio.playback({"id": cue["id"], "phase": phase, "player": "stage", "index": 0}))
            self.assertNotIn(cue["id"], {r["id"] for r in studio.archive("history")["items"]})
            self.assertTrue(studio.playback({"id": cue["id"], "phase": "complete", "player": "stage"}))
        studio.close()
        studio = self.open()
        state = studio.state()
        self.assertEqual(len(state["history"]), 28)
        page = studio.archive("history", state["archiveBefore"]["history"], 4)
        last = studio.archive("history", page["nextCursor"], 4)
        rows = state["history"] + page["items"] + last["items"]
        self.assertIsNone(last["nextCursor"])
        self.assertEqual([r["text"] for r in rows], [f"完成第 {n} 句" for n in reversed(range(35))])

    def test_write_failure_cannot_accept_or_broadcast_an_unarchived_cue(self):
        import sqlite3
        studio = self.open()
        with patch.object(studio.store, "set_event_cue", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                studio.ingest(validate(comment(42)))
        self.assertTrue(studio.state()["stopped"])
        self.assertIsNone(studio.state()["active"])
        self.assertEqual(studio.state()["queue"], [])
        studio.close()
        recovered = self.open()
        self.assertEqual(recovered.state()["recent"], [])
        recovered.ingest(validate(comment(42)))
        self.assertEqual(self.active(recovered)["eventId"], "42")

    def test_production_port_selects_a_private_studio_archive(self):
        with patch.dict(os.environ, {"DOUJIE_DATA_DIR": self.temp.name}):
            self.assertNotEqual(studio_path(8080), studio_path(8081))
            with LocalServer(0, data_path=studio_path(8080)) as server:
                server.scheduler.control({"action":"auto", "enabled":False})
            with LocalServer(0, data_path=studio_path(8080)) as restored:
                self.assertFalse(restored.scheduler.auto)
            with LocalServer(0, data_path=studio_path(8081)) as separate:
                self.assertTrue(separate.scheduler.auto)
