"""Run the local broadcast service for the lifetime of its native desktop shell."""

import argparse
import errno
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

from server import LocalServer
from speech_backend import warmup
from studio_store import studio_path


PROJECT = Path(__file__).resolve().parent


def electron_executable():
    override = os.environ.get("DOUJIE_ELECTRON")
    if override:
        return Path(override) if Path(override).is_file() else None
    relative = Path("node_modules/electron/dist/electron.exe")
    for candidate in (PROJECT / relative, PROJECT.parent / "windring-island" / relative):
        if candidate.is_file():
            return candidate
    return None


def desktop_hosts():
    electron = electron_executable()
    if electron:
        yield "Electron", [str(electron), str(PROJECT)]
    native = PROJECT / "desktop" / "webview" / "DoujieStudio.exe"
    if sys.platform == "win32" and native.is_file():
        yield "WebView2", [str(native)]


def report(message):
    """Persist launcher diagnostics only. Never log API data, arguments, or environment."""
    print(message, flush=True)
    log_path = os.environ.get("DOUJIE_START_LOG")
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as log:
                print(message, file=log)
        except OSError:
            pass


def launch_shell(command, port, *, focus_only=False, ready_file=None):
    environment = os.environ.copy()
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    switch = "--studio-focus" if focus_only else "--studio-parent"
    args = [*command, f"--studio-port={port}", switch]
    if not focus_only:
        args.append(f"--studio-owner={os.getpid()}")
    if ready_file:
        args.append(f"--studio-ready-file={ready_file}")
    return subprocess.Popen(
        args,
        cwd=PROJECT, env=environment, stdin=subprocess.DEVNULL if focus_only else subprocess.PIPE,
    )


def close_shell(child):
    if child.stdin and not child.stdin.closed:
        try:
            if child.poll() is None:
                child.stdin.write(b"quit\n")
        except OSError:
            pass
        try:
            child.stdin.close()
        except OSError:
            pass
    try:
        child.wait(timeout=4)
    except subprocess.TimeoutExpired:
        child.terminate()
        child.wait()


def focus_existing(hosts, port):
    with tempfile.TemporaryDirectory(prefix="doujie-launch-") as temp:
        for name, command in hosts:
            ack = Path(temp) / name
            try:
                child = launch_shell(command, port, focus_only=True, ready_file=ack)
            except OSError:
                continue
            try:
                if child.wait(timeout=8) == 0:
                    # Electron delivers second-instance to the owner asynchronously.
                    deadline = time.monotonic() + 1.5
                    while time.monotonic() < deadline:
                        if ack.is_file() and ack.read_bytes() == b"focused":
                            return True
                        time.sleep(0.05)
            except subprocess.TimeoutExpired:
                child.terminate()
            finally:
                close_shell(child)
    return False


def wait_for_windows(child, ready_file, timeout=30):
    deadline = time.monotonic() + timeout
    while not ready_file.exists():
        if child.poll() is not None:
            return ready_file.exists()
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def run_desktop(hosts, port):
    with tempfile.TemporaryDirectory(prefix="doujie-launch-") as temp:
        for name, command in hosts:
            ready_file = Path(temp) / name
            report(f"正在启动 {name} 桌面窗口…")
            try:
                child = launch_shell(command, port, ready_file=ready_file)
            except OSError as error:
                report(f"{name} 无法启动（系统错误 {error.errno}）。")
                continue
            try:
                if wait_for_windows(child, ready_file):
                    report(f"{name} 导播台和舞台已就绪。")
                    code = child.wait()
                    if code:
                        report(f"{name} 运行中退出，代码 0x{code & 0xffffffff:08x}。")
                    return int(code != 0)
                code = child.poll()
                reason = "等待窗口就绪超时" if code is None else f"窗口就绪前退出，代码 0x{code & 0xffffffff:08x}"
                report(f"{name} {reason}。")
            finally:
                close_shell(child)
    report("桌面窗口启动失败。请检查 Microsoft Edge WebView2 运行时，或设置 DOUJIE_ELECTRON 指向可用的 Electron。")
    return 1


def main():
    parser = argparse.ArgumentParser(description="豆姐锐评室")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true", help="仅启动本地服务")
    args = parser.parse_args()
    hosts = [] if args.no_browser else list(desktop_hosts())
    if not args.no_browser and not hosts:
        report("缺少桌面启动文件。请完整解压项目，或在项目目录运行 npm ci 安装 Electron。")
        return 1
    try:
        server = LocalServer(args.port)
    except sqlite3.Error as error:
        report(f"无法打开直播记录 {studio_path(args.port)}（{error}）。请检查数据目录和磁盘空间。")
        return 1
    except (OSError, OverflowError) as error:
        if getattr(error, "filename", None):
            report(f"无法访问直播数据目录 {studio_path(args.port).parent}（{error}）。")
            return 1
        in_use = getattr(error, "errno", None) in (errno.EADDRINUSE, 10048)
        if in_use and focus_existing(hosts, args.port):
            report("已调出正在运行的豆姐导播台。")
            return 0
        report(f"无法监听 127.0.0.1:{args.port}（{error}）。可用 --port 指定其他端口。")
        return 1

    with server:
        base = f"http://127.0.0.1:{server.server_port}"
        print(f"豆姐锐评室\n导播台  {base}/\n直播舞台  {base}/stage.html\n采集入口  {base}/live-events", flush=True)
        try:
            warmup()
            if args.no_browser:
                server.serve_forever()
            else:
                serving = threading.Thread(target=server.serve_forever, name="desktop-http", daemon=True)
                serving.start()
                try:
                    return run_desktop(hosts, server.server_port)
                finally:
                    server.shutdown()
                    serving.join()
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
