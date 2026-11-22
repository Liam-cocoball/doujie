"""Exercise the desktop handshake with short-lived child processes on the actual OS."""
from contextlib import redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest import TestCase
from unittest.mock import MagicMock, patch

import launch


# The executable and existing args lead each command. The launcher appends its switches.
HOST = """
from pathlib import Path
import json, os, sys, time

trace, name, behavior = sys.argv[1:4]
switches = sys.argv[4:]
def record(event, **extra):
    with open(trace, 'a', encoding='utf-8') as log:
        print(json.dumps(dict(host=name, event=event, **extra)), file=log, flush=True)
record('start', args=switches, cwd=os.getcwd(), electron_node=os.getenv('ELECTRON_RUN_AS_NODE'))
marker = next((Path(arg.split('=', 1)[1]) for arg in switches if arg.startswith('--studio-ready-file=')), None)
if behavior.startswith('focus'):
    record('stdin', eof=(sys.stdin.buffer.read(1) == b''))
    if behavior == 'focus-success' and marker is not None:
        marker.write_text('focused', encoding='utf-8')
    if behavior == 'focus-wrong' and marker is not None:
        marker.write_text('ready', encoding='utf-8')
    sys.exit(7 if behavior == 'focus-fail' else 0)
if behavior.startswith('ready-'):
    marker.write_text('ready', encoding='utf-8')
    record('ready')
elif behavior == 'wait-quit':
    record('command', line=sys.stdin.buffer.readline().decode().strip())
elif behavior == 'ignore-quit':
    time.sleep(35)
record('exit')
sys.exit(7 if behavior.endswith('-crash') else 0)
"""


class DesktopLauncherTest(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="doujie-host-test-")
        self.addCleanup(self.temp.cleanup)
        self.trace = Path(self.temp.name) / "events.jsonl"
        log_env = patch.dict(os.environ, {"DOUJIE_START_LOG": "", "ELECTRON_RUN_AS_NODE": "1"})
        log_env.start()
        self.addCleanup(log_env.stop)
        quiet = redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def host(self, name, behavior):
        return name, [sys.executable, "-I", "-S", "-c", HOST, str(self.trace), name, behavior]

    def events(self):
        if not self.trace.exists():
            return []
        return [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]

    def starts(self):
        return [row for row in self.events() if row["event"] == "start"]

    def check_parent(self, row, port):
        args = row["args"]
        self.assertIn("--studio-parent", args)
        self.assertIn(f"--studio-port={port}", args)
        self.assertIn(f"--studio-owner={os.getpid()}", args)
        self.assertNotIn("--studio-focus", args)
        self.assertIsNone(row["electron_node"])
        self.assertEqual(Path(row["cwd"]), launch.PROJECT)
        marker = next(Path(s.split("=", 1)[1]) for s in args if s.startswith("--studio-ready-file="))
        self.assertFalse(marker.parent.exists(), "launcher left its private ready directory behind")
        return marker

    def test_pre_ready_crash_and_silent_zero_fall_through_in_order(self):
        hosts = [self.host("one", "before-crash"), self.host("two", "before-zero"), self.host("three", "ready-ok")]
        self.assertEqual(launch.run_desktop(hosts, 8100), 0)
        self.assertEqual([(r["host"], r["event"]) for r in self.events()],
                         [("one", "start"), ("one", "exit"), ("two", "start"), ("two", "exit"),
                          ("three", "start"), ("three", "ready"), ("three", "exit")])
        markers = [self.check_parent(row, 8100) for row in self.starts()]
        self.assertEqual(len(set(markers)), 3)
        self.assertEqual(len({path.parent for path in markers}), 1)

    def test_exiting_after_ready_never_opens_a_second_window(self):
        for behavior, exit_status in (("ready-ok", 0), ("ready-crash", 1)):
            with self.subTest(behavior=behavior):
                self.trace.unlink(missing_ok=True)
                hosts = [self.host("first", behavior), self.host("unexpected", "ready-ok")]
                self.assertEqual(launch.run_desktop(hosts, 8110), exit_status)
                self.assertEqual([r["host"] for r in self.starts()], ["first"])
                self.check_parent(self.starts()[0], 8110)

    def test_slow_host_receives_quit_before_next_host_starts(self):
        wait = launch.wait_for_windows
        def short_first(child, marker):
            return wait(child, marker, timeout=.65 if marker.name == "slow" else 5)
        with patch.object(launch, "wait_for_windows", side_effect=short_first):
            self.assertEqual(launch.run_desktop([
                self.host("slow", "wait-quit"), self.host("fallback", "ready-ok")], 8120), 0)
        self.assertEqual([(r["host"], r["event"]) for r in self.events()],
                         [("slow", "start"), ("slow", "command"), ("slow", "exit"),
                          ("fallback", "start"), ("fallback", "ready"), ("fallback", "exit")])
        self.assertEqual(self.events()[1]["line"], "quit")

    def test_hung_child_is_terminated_and_reaped(self):
        _, command = self.host("hung", "ignore-quit")
        child = launch.launch_shell(command, 8130)
        try:
            launch.close_shell(child)
            self.assertIsNotNone(child.poll())
            self.assertTrue(child.stdin.closed)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    def test_missing_executable_and_no_ready_host_return_failure(self):
        missing = ("missing", [str(Path(self.temp.name) / "missing-executable")])
        self.assertEqual(launch.run_desktop([missing, self.host("silent", "before-zero")], 8140), 1)
        self.assertEqual([r["host"] for r in self.starts()], ["silent"])
        self.check_parent(self.starts()[0], 8140)

    def test_secondary_launch_requires_positive_focus_acknowledgement(self):
        hosts = [self.host("first", "focus-fail"), self.host("silent", "focus-no-ack"),
                 self.host("focused", "focus-success"), self.host("unexpected", "focus-success")]
        occupied = OSError(errno.EADDRINUSE, "test port already in use")
        with patch.object(sys, "argv", ["launch.py", "--port", "8150"]), \
             patch.object(launch, "desktop_hosts", return_value=hosts), \
             patch.object(launch, "LocalServer", side_effect=occupied), patch.object(launch, "warmup") as warm:
            self.assertEqual(launch.main(), 0)
        warm.assert_not_called()
        starts = self.starts()
        self.assertEqual([r["host"] for r in starts], ["first", "silent", "focused"])
        for row in starts:
            args = row["args"]
            self.assertIn("--studio-focus", args)
            self.assertIn("--studio-port=8150", args)
            self.assertNotIn("--studio-parent", args)
            self.assertFalse(any(arg.startswith("--studio-owner=") for arg in args))
            marker = next(Path(s.split("=", 1)[1]) for s in args if s.startswith("--studio-ready-file="))
            self.assertFalse(marker.parent.exists())
        self.assertTrue(all(r["eof"] for r in self.events() if r["event"] == "stdin"))

    def test_unrelated_occupied_port_without_focus_ack_is_an_error(self):
        with patch.object(sys, "argv", ["launch.py"]), \
             patch.object(launch, "desktop_hosts", return_value=[self.host("wrong-token", "focus-wrong")]), \
             patch.object(launch, "LocalServer", side_effect=OSError(errno.EADDRINUSE, "in use")), \
             patch.object(launch, "warmup") as warm:
            self.assertEqual(launch.main(), 1)
        warm.assert_not_called()
        self.assertEqual(len(self.starts()), 1)

    def test_existing_owner_can_ack_after_focus_helper_exits(self):
        original = launch.launch_shell
        writers = []
        def start_helper(command, port, **options):
            child = original(command, port, **options)
            def owner_ack():
                child.wait(timeout=5)
                time.sleep(.12)
                try:
                    options["ready_file"].write_bytes(b"focused")
                except FileNotFoundError:
                    # A launcher that gave up too early already deleted the directory.
                    pass
            writer = threading.Thread(target=owner_ack)
            writer.start()
            writers.append(writer)
            return child
        try:
            with patch.object(launch, "launch_shell", side_effect=start_helper):
                self.assertTrue(launch.focus_existing([self.host("async", "focus-no-ack")], 8151))
        finally:
            for writer in writers:
                writer.join(timeout=5)

    def test_no_browser_mode_serves_without_discovering_or_spawning_windows(self):
        server = MagicMock()
        server.server_port = 8160
        server.serve_forever.side_effect = KeyboardInterrupt
        with patch.object(sys, "argv", ["launch.py", "--no-browser"]), \
             patch.object(launch, "desktop_hosts") as discover, patch.object(launch, "LocalServer", return_value=server), \
             patch.object(launch, "warmup") as warm, patch.object(launch, "launch_shell") as spawn:
            self.assertEqual(launch.main(), 0)
        discover.assert_not_called()
        spawn.assert_not_called()
        warm.assert_called_once()
        server.serve_forever.assert_called_once()
        server.__exit__.assert_called_once()

    def test_server_shuts_down_after_run_time_crash(self):
        server = MagicMock()
        server.server_port = 8170
        shutdown = threading.Event()
        stopped = threading.Event()
        def serve():
            shutdown.wait(5)
            stopped.set()
        server.serve_forever.side_effect = serve
        server.shutdown.side_effect = shutdown.set
        with patch.object(sys, "argv", ["launch.py"]), \
             patch.object(launch, "desktop_hosts", return_value=[self.host("native", "ready-crash")]), \
             patch.object(launch, "LocalServer", return_value=server), patch.object(launch, "warmup"):
            self.assertEqual(launch.main(), 1)
        self.assertTrue(stopped.is_set())
        server.shutdown.assert_called_once()
        server.__exit__.assert_called_once()
