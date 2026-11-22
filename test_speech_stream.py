import os
from unittest import TestCase
from unittest.mock import Mock, patch

import speech_backend as speech


class StreamingVoiceTest(TestCase):
    def setUp(self):
        process = Mock()
        process.poll.return_value = 0
        self.commands = []
        for context in (
            patch.object(speech, "_process", process), patch.object(speech, "_state", "ready"),
            patch.object(speech, "_session_rate", None), patch.object(speech, "warmup"),
            patch.dict(os.environ, {"DOUJIE_SPEECH_RATE": "1.18"}),
            patch.dict(speech._cache, clear=True), patch.dict(speech._jobs, clear=True),
            patch.dict(speech._cancelled, clear=True),
        ):
            context.start()
            self.addCleanup(context.stop)
        self.writer = patch.object(speech, "_write", side_effect=self.send)
        self.writer.start()
        self.addCleanup(self.writer.stop)

    def send(self, command):
        self.commands.append(command)
        if command["type"] == "synthesize":
            job = speech._jobs[command["request_id"]]
            # A real worker sends chunks before reporting success.
            job["chunks"].append(b"\x01\x00")
            job["total"] += 2
        return True

    def finish_worker(self, key, ok=True):
        with speech._cv:
            job = speech._jobs[key]
            job.update(done=True, ok=ok)
            if ok:
                job["chunks"].append(b"\x02\x00")
                job["total"] += 2
            speech._cv.notify_all()

    def test_first_pcm_is_available_before_completion_and_replay_uses_cache(self):
        chunks = speech.pcm_chunks("说重点。", "live")
        self.assertEqual(next(chunks), b"\x01\x00")
        self.assertFalse(speech._jobs["live"]["done"])
        self.finish_worker("live")
        self.assertEqual(list(chunks), [b"\x02\x00"])
        self.assertEqual(list(speech.pcm_chunks("说重点。", "next")), [b"\x01\x00", b"\x02\x00"])
        self.assertEqual(len(self.commands), 1)
        speech.shutdown()
        self.assertFalse(speech._cache)

    def test_cancel_or_client_disconnect_never_caches_partial_words(self):
        for key, operation in [("stop", "cancel"), ("lost", "disconnect"), ("failed", "failure")]:
            with self.subTest(operation=operation):
                chunks = speech.pcm_chunks("说重点。", key)
                self.assertEqual(next(chunks), b"\x01\x00")
                if operation == "disconnect":
                    chunks.close()
                else:
                    if operation == "cancel":
                        speech.cancel(key)
                    else:
                        self.finish_worker(key, ok=False)
                    with self.assertRaises(speech.SpeechUnavailable):
                        next(chunks)
                self.assertNotIn(key, speech._jobs)
                self.assertFalse(speech._cache)

    def test_rate_is_part_of_cache_key_and_snapshotted_per_generation(self):
        original = speech.pcm_chunks("这就急了？", "a")
        next(original)
        self.assertEqual(self.commands[-1]["speed"], 1.18)
        speech.set_rate(1.32)
        self.finish_worker("a")
        list(original)
        self.assertEqual(speech.status()["rate"], 1.32)
        fast = speech.pcm_chunks("这就急了？", "b")
        next(fast)
        self.assertEqual(self.commands[-1]["speed"], 1.32)
        fast.close()
        for invalid in [True, "1.2", float("nan"), float("inf"), .79, 1.61]:
            with self.assertRaises(ValueError):
                speech.set_rate(invalid)
