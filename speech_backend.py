"""Serve the Windring GPT-SoVITS voice from a single persistent local worker."""
import atexit
import base64
import binascii
from collections import OrderedDict, deque
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid
import wave


VOICE = "豆姐 · 专属音色"
_cv = threading.Condition()
_process = None
_state = "idle"
_message = "等待加载本地音色"
_reference = {}
_jobs = {}
_cancelled = {}  # A stop may arrive just before the corresponding HTTP request.
_startup_timer = None
_retry_at = 0.0
_start_timeout = 120
_job_timeout = 150
_max_audio_bytes = 12 * 1024 * 1024
_cache = OrderedDict()
_cache_clip_limit = 512 * 1024
_session_rate = None


def _speech_rate():
    if _session_rate is not None:
        return _session_rate
    try:
        rate = float(os.environ.get("DOUJIE_SPEECH_RATE", "1.18"))
    except ValueError:
        return 1.18
    return min(1.6, max(.8, rate)) if math.isfinite(rate) else 1.18


def set_rate(value):
    """Change the rate of new synthesis requests during this session."""
    if type(value) not in (int, float) or not .8 <= value <= 1.6:
        raise ValueError("语速应在 0.80 到 1.60 之间")
    global _session_rate
    with _cv:
        _session_rate = float(value)


class SpeechUnavailable(RuntimeError):
    """No complete synthesis is available, including a cancelled stream."""


def _voice_dir():
    override = os.environ.get("DOUJIE_VOICE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    project = Path(__file__).resolve().parent
    bundled = project / "voice"
    return bundled if (bundled / "worker.py").is_file() else project.parent / "windring-island" / "voice"


def status():
    with _cv:
        return {"state": _state, "message": _message, "voice": VOICE, "rate": _speech_rate()}


def _set_state(state, message):
    global _state, _message
    _state, _message = state, message
    _cv.notify_all()


def _retire(process, message):
    """Detach before killing so the old reader cannot mutate a replacement."""
    global _process, _startup_timer, _retry_at
    with _cv:
        if _process is not process:
            return
        _process = None
        _retry_at = time.monotonic() + 10
        if _startup_timer:
            _startup_timer.cancel()
            _startup_timer = None
        for job in _jobs.values():
            job["done"], job["ok"] = True, False
        _set_state("error", message)
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _read(process):
    global _startup_timer
    failure = "本地音色进程已退出，请检查 CUDA 和语音目录后重试。"
    try:
        for line in process.stdout:
            event = json.loads(line)
            kind = event.get("type")
            with _cv:
                if process is not _process:
                    return
                if kind == "ready":
                    if _startup_timer:
                        _startup_timer.cancel()
                        _startup_timer = None
                    _set_state("ready", "本地音色已就绪")
                    continue
                if kind == "error" and not event.get("request_id"):
                    failure = str(event.get("error") or failure)[:240]
                    break
                job = _jobs.get(event.get("request_id"))
                if not job or job["done"]:
                    continue
                if kind == "chunk":
                    pcm = base64.b64decode(event["audio"], validate=True)
                    if (event.get("sample_rate") != 24000 or event.get("channels") != 1 or
                            len(pcm) % 2 or job["total"] + len(pcm) > _max_audio_bytes):
                        raise ValueError("unexpected audio format")
                    if pcm:
                        job["chunks"].append(pcm)
                        job["total"] += len(pcm)
                        _cv.notify_all()
                elif kind in ("result", "cancelled", "error"):
                    job["done"] = True
                    job["ok"] = kind == "result" and bool(job["total"])
                    if kind == "error":
                        _set_state("ready", "上次合成失败：" + str(event.get("error") or "未知错误")[:180])
                    elif job["ok"]:
                        _set_state("ready", "本地音色已就绪")
                    _cv.notify_all()
    except (OSError, ValueError, KeyError, TypeError, binascii.Error):
        failure = "无法读取本地音色返回的音频。"
    finally:
        _retire(process, failure)
        for pipe in (process.stdout, process.stdin):
            try:
                pipe.close()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def warmup():
    """Launch model loading in the worker, without waiting for the GPU."""
    global _process, _reference, _startup_timer, _retry_at
    with _cv:
        if _process or time.monotonic() < _retry_at:
            return status()
        try:
            root = _voice_dir()
            python = root / "runtime" / "python" / "python.exe"
            script, reference, audio = (root / name for name in ("worker.py", "reference.json", "reference.wav"))
            if not all(path.is_file() for path in (python, script, reference, audio)):
                raise ValueError("缺少风环岛语音文件，请将 DOUJIE_VOICE_DIR 指向完整 voice 目录。")
            profile = json.loads(reference.read_text(encoding="utf-8-sig"))
            if not all(isinstance(profile.get(k), str) and profile[k].strip() for k in ("id", "transcript")):
                raise ValueError("语音参考配置缺少音色编号或参考文本。")
            _reference = {"reference_id": profile["id"], "reference_text": profile["transcript"], "reference_audio": str(audio)}
            # Numba otherwise probes the shared runtime's package directories for writable caches.
            env = os.environ.copy()
            env.setdefault("NUMBA_CACHE_DIR", str(Path(tempfile.gettempdir()) / "doujie-numba"))
            process = subprocess.Popen(
                [str(python), "-I", "-B", "-X", "utf8", "-u", str(script)],
                cwd=root / "runtime" / "upstream", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=env, encoding="utf-8", bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError) as error:
            _retry_at = time.monotonic() + 10
            _set_state("error", str(error))
            return status()
        _process = process
        _set_state("loading", "正在加载豆姐音色")
        _startup_timer = threading.Timer(_start_timeout, _retire, args=(process, "本地音色加载超时，请检查 CUDA。"))
        _startup_timer.daemon = True
        _startup_timer.start()
        threading.Thread(target=_read, args=(process,), name="doujie-voice", daemon=True).start()
        return status()


def _write(command):
    try:
        _process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
        _process.stdin.flush()
        return True
    except (OSError, ValueError):
        _retire(_process, "本地音色连接已中断。")
        return False


def cancel(request_id=None):
    """Cancel one generation or release all outstanding requests on a stage stop."""
    with _cv:
        now = time.monotonic()
        for key, expiry in list(_cancelled.items()):
            if expiry <= now:
                del _cancelled[key]
        if request_id is not None:
            if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,72}", request_id):
                return
            if len(_cancelled) >= 256:
                _cancelled.pop(next(iter(_cancelled)))
            _cancelled[request_id] = now + 30
        for key in ([request_id] if request_id is not None else list(_jobs)):
            job = _jobs.get(key)
            if job:
                if not job["done"] and job["sent"] and _process:
                    _write({"type": "cancel", "request_id": key})
                job.update(done=True, ok=False)
                job["chunks"].clear()
        _cv.notify_all()


def pcm_chunks(text: str, request_id=None):
    """Yield mono 24 kHz signed little-endian PCM as the worker produces it."""
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
        raise SpeechUnavailable("invalid text")
    key = uuid.uuid4().hex if request_id is None else request_id
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,72}", key):
        raise SpeechUnavailable("invalid request id")
    text = text.strip()
    rate = _speech_rate()
    cache_key = (_voice_dir(), rate, text)
    with _cv:
        if key in _jobs or _cancelled.get(key, 0) > time.monotonic() or len(_jobs) >= 8:
            raise SpeechUnavailable("request busy or cancelled")
        cached = _cache.get(cache_key)
        if cached:
            _cache.move_to_end(cache_key)
        else:
            warmup()
            if not _process:
                raise SpeechUnavailable("voice unavailable")
        process = _process
        job = _jobs[key] = {"chunks": deque(cached or ()), "total": 0, "sent": False,
                            "done": bool(cached), "ok": bool(cached)}
    try:
        with _cv:
            if not cached:
                _cv.wait_for(lambda: _state != "loading" or job["done"], timeout=_start_timeout + 1)
                if process is not _process or _state != "ready" or job["done"]:
                    raise SpeechUnavailable("voice unavailable")
                job["sent"] = _write({"type": "synthesize", "request_id": key, "text": text,
                                      "speed": rate, "stream": True, **_reference})
                if not job["sent"]:
                    raise SpeechUnavailable("worker disconnected")
        saved = None if cached else []
        deadline = time.monotonic() + _job_timeout
        while True:
            with _cv:
                if not _cv.wait_for(lambda: job["done"] or job["chunks"], timeout=max(0, deadline-time.monotonic())):
                    _retire(process, "本地语音生成超时，可稍后重试。")
                    raise SpeechUnavailable("timed out")
                if job["done"] and not job["ok"]:
                    raise SpeechUnavailable("cancelled or incomplete")
                if not job["chunks"]:
                    if saved:
                        _cache[cache_key] = tuple(saved)
                        _cache.move_to_end(cache_key)
                        if len(_cache) > 32:
                            _cache.popitem(last=False)
                    return
                chunk = job["chunks"].popleft()
                if saved is not None:
                    if job["total"] <= _cache_clip_limit:
                        saved.append(chunk)
                    else:
                        saved = None
            yield chunk
    finally:
        with _cv:
            if not job["done"] and job["sent"] and _process is process:
                _write({"type": "cancel", "request_id": key})
            _jobs.pop(key, None)


def wav(text: str, request_id=None) -> bytes | None:
    try:
        pcm = b"".join(pcm_chunks(text, request_id))
    except SpeechUnavailable:
        return None
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        stream.writeframes(pcm)
    return output.getvalue()


def shutdown():
    global _retry_at, _session_rate
    with _cv:
        process = _process
        if process:
            _retire(process, "本地音色已关闭")
        _cache.clear()
        _session_rate = None
        _retry_at = 0
        _set_state("idle", "本地音色已关闭")
    if process:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


atexit.register(shutdown)
