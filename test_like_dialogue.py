import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from host_dialogue import like_beat
from server import CROWD_GAP, Scheduler, validate


class LikeDialogueTest(unittest.TestCase):
    def test_single_taps_and_counted_batches_avoid_recent_punchlines(self):
        history = []
        variants, gestures = [], set()
        active = None
        for index in range(60):
            task = {"roomId": "A", "source": "like"}
            count = (None, 1, 8)[index % 3]
            segment = like_beat(task, count, history[-28:], active)
            self.assertNotIn(task["_likeVariant"], variants[-8:])
            variants.append(task["_likeVariant"])
            gestures.add(segment["gesture"])
            self.assertLess(len(segment["text"]), 32)
            if count is None:
                self.assertNotRegex(segment["text"], r"[0-9]")
            if count == 8:
                self.assertIn("8", segment["text"])
            if active:
                history.append(active)
            active = {**task, "text": segment["text"]}
        self.assertEqual(len(set(variants[:16])), 16)
        self.assertGreaterEqual(len(gestures), 5)

    def test_merged_counts_active_cue_and_reopened_archive(self):
        def likes(*counts):
            return validate({"schemaVersion": 1, "events": [
                {"eventId": str(uuid4()), "type": "like", "roomId": "22", "rawText": "",
                 "capturedAt": "2026-11-21T12:00:00Z", "actor": None,
                 "data": {} if count is None else {"displayCount": count}}
                for count in counts
            ]})

        def active(studio):
            with studio.cv:
                self.assertTrue(studio.cv.wait_for(lambda: studio.active, timeout=2))
                return studio.state(stage=True)["active"]

        def finish(studio, cue):
            for phase, fields in (("start", {}), ("segment", {"index": 0}), ("complete", {})):
                self.assertTrue(studio.playback({"id": cue["id"], "player": "test", "phase": phase, **fields}))

        with TemporaryDirectory() as temp, patch.dict(CROWD_GAP, like=0), \
                patch("host_dialogue.random.choice", side_effect=lambda choices: choices[0]):
            db = Path(temp) / "likes.sqlite3"
            studio = Scheduler(data_path=db)
            try:
                studio.ingest(likes(4, 3))
                first = active(studio)
                self.assertIn("7", first["text"])
                self.assertEqual(len(first["segments"]), 1)
                studio.ingest(likes(12))
                pending = studio.state()["queue"][0]
                self.assertIn("12", pending["text"])
                self.assertNotEqual(re.sub(r"\d+", "#", first["text"]), re.sub(r"\d+", "#", pending["text"]))
                studio.ingest(likes(None, 20))
                merged = studio.state()["queue"]
                self.assertEqual([cue["id"] for cue in merged], [pending["id"]])
                self.assertNotRegex(merged[0]["text"], r"\d")
                self.assertEqual(merged[0]["gesture"], pending["gesture"])
                finish(studio, first)
                second = active(studio)
                self.assertEqual(second["text"], merged[0]["text"])
                finish(studio, second)
            finally:
                studio.close()
            reopened = Scheduler(data_path=db)
            try:
                history = reopened.state()["history"]
                self.assertEqual([row["text"] for row in history], [second["text"], first["text"]])
                reopened.ingest(likes(7))
                third = active(reopened)
                self.assertNotEqual(third["text"], first["text"])
                self.assertNotEqual(third["text"], pending["text"].replace("12", "7"))
                self.assertNotIn("_likeVariant", third)
                finish(reopened, third)
                for _ in range(reopened.history.maxlen + 1):
                    reopened.control({"action": "manual", "text": "导播试麦。"})
                    finish(reopened, active(reopened))
                self.assertTrue(all(row["source"] == "manual" for row in reopened.state()["history"]))
                reopened.ingest(likes(7))
                fourth = active(reopened)
                self.assertNotIn(fourth["text"], (first["text"], pending["text"].replace("12", "7"), third["text"]))
            finally:
                reopened.close()
