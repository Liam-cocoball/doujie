"""Verify Windows account protection, including opening saved data after a restart."""
import base64
import hashlib
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from studio_secrets import KeyProtectionError, protect_key, supports_key_protection, unprotect_key


class StudioSecretsTest(unittest.TestCase):
    def test_rejects_plaintext_and_unknown_or_malformed_envelopes(self):
        for value in ("example-sensitive-text", "dpapi-v2:abcd", "dpapi-v1:$!", "dpapi-v1:",
                      "dpapi-v1:中文", "dpapi-v1:" + "x" * 17000, None):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(KeyProtectionError) as result:
                unprotect_key(value)
            self.assertNotIn("example-sensitive-text", str(result.exception))

    def test_explicit_keys_require_supported_protection(self):
        with patch("studio_secrets.supports_key_protection", return_value=False):
            with self.assertRaises(KeyProtectionError) as error:
                protect_key("example-sensitive-text")
            self.assertNotIn("example-sensitive-text", str(error.exception))
            with self.assertRaises(KeyProtectionError):
                unprotect_key("dpapi-v1:" + base64.b64encode(b"unavailable").decode("ascii"))

    def test_invalid_input_is_rejected_before_native_call(self):
        with patch("studio_secrets._dpapi") as native:
            for key in ("", "中文", "line\nbreak", "x" * 513, None):
                with self.assertRaises(KeyProtectionError):
                    protect_key(key)
            native.assert_not_called()

    @unittest.skipUnless(supports_key_protection(), "requires Windows user DPAPI")
    def test_dpapi_reopens_saved_key_in_fresh_process_and_rejects_truncation(self):
        key = "test-" + uuid.uuid4().hex
        envelope = protect_key(key)
        scheme, payload = envelope.split(":", 1)
        self.assertEqual(scheme, "dpapi-v1")
        self.assertNotIn(key.encode(), base64.b64decode(payload))
        self.assertNotEqual(envelope, protect_key(key))
        probe = ("import hashlib,sys; from studio_secrets import unprotect_key; "
                 "print(hashlib.sha256(unprotect_key(sys.stdin.read()).encode()).hexdigest())")
        result = subprocess.run([sys.executable, "-c", probe], input=envelope, text=True,
                                capture_output=True, check=True, timeout=10)
        self.assertEqual(result.stdout.strip(), hashlib.sha256(key.encode()).hexdigest())
        with self.assertRaises(KeyProtectionError):
            unprotect_key(scheme + ":" + base64.b64encode(base64.b64decode(payload)[:20]).decode("ascii"))


if __name__ == "__main__":
    unittest.main()
