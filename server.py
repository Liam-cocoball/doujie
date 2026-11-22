"""Loopback-only live-event receiver and cue scheduler. Python 3.10+, stdlib only."""
import argparse
from collections import OrderedDict, deque
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import itertools
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
from threading import BoundedSemaphore, Condition, Event, Thread
import time
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID, uuid4
from audience_invites import append_gift_invite, make_gift_invite, mentions_gifts
from gift_wall import place_gift
from gift_rules import GiftCombos, can_merge_gift, contextual_gift, gift_merge_key, gift_script, live_gift_variant, merge_gift
from host_dialogue import (DEFAULT_PERSONA, Dialogue, EXPRESSIONS, GESTURES, beat, is_generic_reply, like_beat, local_reply,
                           on_air_history, quick_reply, validate_persona)
from social_replies import social_beat
import speech_backend
from studio_secrets import KeyProtectionError, protect_key, unprotect_key
from studio_store import StudioStore, studio_path
import mimetypes

WEB = Path(__file__).resolve().with_name("web")
MAX_BODY = 64 * 1024
MAX_BATCH = 100
MAX_QUEUE = 32
MAX_NICKNAME = 160
MAX_TTS_TEXT = MAX_NICKNAME + len("欢迎")
WELCOME_LIFETIME = 15
TYPES = {"gift", "like", "room_join", "comment", "follow", "fans_club_join", "unknown"}
PRIORITY = {"manual": 0, "topic": 1, "selected": 1, "gift": 2, "comment": 3, "gift_invite": 3,
            "follow": 4, "fans_club_join": 4, "like": 5, "room_join": 6}
READY_TIMEOUT = 90
PLAY_TIMEOUT = 150
COMMENT_PLAN_BUDGET = 5.0
COMMENT_BURST_THRESHOLD = 4
COMMENT_BURST_GAP = 6
BURST_GIFT_INVITE_GAP = 25
# A full ten contested turns has seven comments and three welcomes, interleaved.
AUDIENCE_MIX = ("comment", "room_join", "comment", "comment", "room_join",
                "comment", "comment", "room_join", "comment", "comment")
GIFT_REWRITE_BUDGET = 1.8
PCM_MEDIA_TYPE = "application/x-doujie-pcm"
CROWD_GAP = {"like": 8, "follow": 6, "fans_club_join": 6}


def bounded_string(value, length):
    return isinstance(value, str) and len(value) <= length and not any(0xD800 <= ord(c) <= 0xDFFF for c in value)


def validate(payload):
    strict = isinstance(payload, dict) and "schemaVersion" in payload
    if strict and (type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1):
        raise ValueError("schemaVersion must be 1")
    if isinstance(payload, dict) and ("events" in payload or strict):
        rows = payload.get("events")
    else:
        rows = payload if isinstance(payload, list) else [payload]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_BATCH:
        raise ValueError("events must contain 1–100 items")
    return [parse_event(row, strict) for row in rows]


def parse_event(event, strict):
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    room, event_id = event.get("roomId"), event.get("eventId")
    if strict:
        try:
            event_id = str(UUID(event_id))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("eventId must be a UUID") from None
        if not isinstance(room, str) or not re.fullmatch(r"[0-9]{1,32}", room):
            raise ValueError("invalid roomId")
    elif not bounded_string(event_id, 160) or not event_id.strip() or not bounded_string(room, 128) or not room.strip():
        raise ValueError("invalid roomId or eventId")
    kind = event.get("type")
    if not isinstance(kind, str) or kind not in TYPES:
        raise ValueError("invalid event type")
    if not strict and "capturedAt" not in event:
        stamp = time.time()
    else:
        captured = event.get("capturedAt")
        try:
            if not bounded_string(captured, 48) or "T" not in captured:
                raise ValueError
            dt = datetime.fromisoformat(captured.replace("Z", "+00:00"))
            if dt.utcoffset() is None:
                raise ValueError
            stamp = dt.timestamp()
        except (OverflowError, OSError, ValueError):
            raise ValueError("capturedAt must be a timezone-aware ISO timestamp") from None
    if strict and "actor" not in event:
        raise ValueError("actor must be provided")
    actor = event.get("actor")
    if actor is not None and (not isinstance(actor, dict) or not bounded_string(actor.get("nickname"), MAX_NICKNAME)):
        raise ValueError("invalid actor")
    data = event.get("data") if strict else event.get("data", {})
    if not isinstance(data, dict) or not bounded_string(event.get("rawText", None if strict else ""), 4096):
        raise ValueError("invalid data or rawText")
    for field, limit in (("content", 2048), ("giftName", 120), ("countText", 120)):
        if (field in data or kind == "comment" and field == "content") and not bounded_string(data.get(field), limit):
            raise ValueError("invalid " + field)
    if "displayCount" in data and (type(data["displayCount"]) is not int or not 1 <= data["displayCount"] <= 10**9):
        raise ValueError("invalid displayCount")
    # Only approved display fields reach the stage. Viewer IDs stay inside the local scheduler.
    display = {"nickname": actor["nickname"]} if actor else {}
    if actor:
        for field in ("secUid", "openId", "userId"):
            viewer = actor.get(field)
            if bounded_string(viewer, 256) and viewer.strip():
                display["_viewer"] = hashlib.sha256((room + "\0" + field + ":" + viewer.strip()).encode()).hexdigest()
                break
    if kind == "gift" and bounded_string(data.get("comboId"), 160):
        display["_combo"] = data["comboId"]
    fields = {"like": ("displayCount",), "comment": ("content",), "gift": ("giftName", "displayCount"),
              "room_join": ("countText", "displayCount")}
    for field in fields.get(kind, ()):
        if field in data:
            display[field] = data[field]
    return event_id, room, kind, stamp, display


def install_segments(task, segments):
    task["segments"] = segments
    task["text"] = "".join(segment["text"] for segment in segments)
    task["cue"] = task["gesture"] = segments[0]["gesture"]
    task["expression"] = segments[0]["expression"]
    # Duration is for operator display and gesture-only animation. Spoken cues use player acknowledgements.
    task["durationMs"] = max(1800, sum(len(s["text"]) * 200 + s.get("pauseMs", 0) for s in segments))


def public_item(task):
    return {k: v for k, v in task.items() if not k.startswith("_") and k != "audience"}


class PreviewBusy(Exception):
    pass


def model_gift_segments(dialogue, task, history):
    """Use exactly the same closing-line rewrite in the booth and on the live stage."""
    mode = "fallback"
    def rewrite(row, line):
        nonlocal mode
        setup = gift_script(task["giftName"], task["giftCount"], variant=task.get("giftVariant", 0))
        replacement = dialogue.gift_line(task["giftName"], row, line, setup["segments"][0]["text"])
        if replacement:
            mode = "deepseek"
        return replacement
    return contextual_gift(task, history, rewrite), mode


class Scheduler:
    def __init__(self, dialogue=None, data_path=None):
        self.cv = Condition()
        self.store = StudioStore(data_path)
        self.storage_failed = False
        self.dialogue = dialogue or Dialogue()
        self.persona_version = 0
        self.preview_slot = BoundedSemaphore(1)
        saved = self.store.settings()
        self.stopped = saved.get("stopped", False)
        self.auto = saved.get("auto", True) and not self.stopped
        self.key_saved = bool(saved.get("protectedKey"))
        self.key_notice = ""
        saved_key = None
        if self.key_saved:
            try:
                saved_key = unprotect_key(saved["protectedKey"])
            except KeyProtectionError:
                self.key_notice = "此 Windows 账户无法读取已保存的密钥，可重新输入。"
        if saved_key is not None or "model" in saved or "persona" in saved:
            self.dialogue.configure(saved_key, saved.get("model"), saved.get("persona"))
        if "rate" in saved:
            speech_backend.set_rate(saved["rate"])
        self.stop_serial = 0
        self.active = None
        self.deadline = 0
        self.queue = []
        events, self.more_events = self.store.page("events", limit=60)
        history, _ = self.store.page("history", limit=100)
        self.recent = deque(events, maxlen=60)
        self.history = deque(reversed(history), maxlen=28)
        self.more_history = len(history) > len(self.history)
        self.like_history = deque((row for row in reversed(history) if row["source"] == "like"), maxlen=32)
        self.gift_invites = deque((row for row in reversed(history) if row.get("giftInvite")), maxlen=24)
        self.invite_after = {}
        self.mix_position = 0
        for row in reversed(history):
            if row["source"] != "gift" and not row.get("giftInvite"):
                continue
            left = BURST_GIFT_INVITE_GAP - max(0, time.time() - row["at"] / 1000)
            if left > 0:
                self.invite_after[row["roomId"]] = time.monotonic() + left
        self.gift_effects = deque(maxlen=12)
        self.combos = GiftCombos()
        self.wall_room = None
        self.wall_entries = []
        previous_room = self.store.last_collector_room()
        if previous_room is not None:
            self._load_gift_wall(previous_room)
        self.gift_streaks = OrderedDict()
        self.crowd_next = {}
        self.comment_arrivals = OrderedDict()
        self.latest_burst_comment = {}
        self.ids = itertools.count(self.store.next_cue())
        self.stage_count = 0
        self.planning = None
        self.refining_gift = None
        self.received = None
        self.revision = 0
        self.closed = False
        self.thread = Thread(target=self._run, name="broadcast", daemon=True)
        self.thread.start()

    def close(self):
        with self.cv:
            if self.closed:
                return
            self.closed = True
            self._changed()
        self.thread.join(timeout=2)
        with self.cv:
            self.store.db.close()

    @contextmanager
    def _write(self):
        # A batch and all queue/history changes it causes share a single SQLite transaction.
        with self.cv:
            if self.closed or self.storage_failed:
                raise sqlite3.OperationalError("studio storage unavailable")
            try:
                with self.store.db:
                    yield
            except sqlite3.Error:
                self.storage_failed = True
                self.stopped, self.auto = True, False
                self.queue.clear()
                self.active = None
                self.wall_entries = []
                self.gift_effects.clear()
                self.stop_serial += 1
                self._changed()
                speech_backend.cancel()
                raise

    def archive(self, kind, before=None, limit=60):
        with self.cv:
            if self.closed:
                raise sqlite3.OperationalError("studio closed")
            rows, cursor = self.store.page(kind, before, limit)
            return {"items": [public_item(row) for row in rows], "nextCursor": cursor}

    def preview(self, message):
        if not isinstance(message, dict) or message.get("source") not in ("comment", "gift"):
            raise ValueError("请选择试评弹幕或试接礼物")
        source = message["source"]
        persona = validate_persona(message["persona"]) if "persona" in message else None
        dialogue = self.dialogue.for_preview(persona)
        status = dialogue.status()
        if source == "comment":
            prompt = message.get("text")
            if not bounded_string(prompt, 800) or not prompt.strip():
                raise ValueError("请输入 1 至 800 字的试评弹幕")
            task = {"source": "comment", "roomId": "preview", "name": "", "prompt": prompt.strip()}
            quick = quick_reply(task)
            if quick:
                return {"source": source, "model": status["model"], "mode": "local", "segments": quick}
            local = local_reply(task, [])
            def generate():
                return dialogue.plan(task, [])
        else:
            name, count, variant = message.get("giftName"), message.get("giftCount", 1), message.get("variant", 0)
            if not bounded_string(name, 120) or not name.strip() or type(count) is not int or not 1 <= count <= 9999:
                raise ValueError("请输入礼物名称和 1 至 9999 之间的数量")
            if type(variant) is not int or variant < 0:
                raise ValueError("试词版本无效")
            task = gift_script(name.strip(), count, variant=variant)
            local = contextual_gift(task, [])
            def generate():
                return model_gift_segments(dialogue, task, [])
        result = {"source": source, "model": status["model"], "mode": "local", "segments": local}
        if not status["configured"]:
            return result
        if not self.preview_slot.acquire(blocking=False):
            raise PreviewBusy("已有一次试词正在生成，请稍后重试")
        result["mode"] = "fallback"
        finished = Event()
        outcome = []
        def work():
            try:
                outcome.append(generate())
            finally:
                self.preview_slot.release()
                finished.set()
        # A stalled provider holds just the preview slot, never the scheduler lock or a live worker.
        try:
            Thread(target=work, name="persona-preview", daemon=True).start()
        except RuntimeError:
            self.preview_slot.release()
            return result
        if finished.wait(GIFT_REWRITE_BUDGET if source == "gift" else COMMENT_PLAN_BUDGET) and outcome:
            result["segments"], result["mode"] = outcome[0]
        return result

    def _state(self, stage=False):
        active = public_item(self.active) if self.active else None
        preparing = None
        if not active and self.queue and not self.stopped:
            now = time.monotonic()
            next_cue = next((t for t in self._scheduled() if t["_readyAt"] <= now), None)
            if next_cue and next_cue["source"] in {"topic", "comment"} and not next_cue["segments"]:
                preparing = {key: next_cue[key] for key in ("id", "source", "name", "prompt", "replyTarget")}
        state = {"revision": self.revision, "autoEnabled": self.auto, "stopped": self.stopped,
                 "active": active, "queueDepth": len(self.queue), "stageCount": self.stage_count,
                 "preparing": preparing, "received": self.received,
                 "stageConnected": bool(self.stage_count), "recent": [],
                 "giftFx": self.gift_effects[-1] if self.gift_effects else None,
                 "giftFlash": self.gift_effects[-1] if self.gift_effects else None,
                 "giftEffects": list(self.gift_effects),
                 "giftWall": [public_item(item) for item in self.wall_entries]}
        if not stage:
            state.update(queue=[public_item(t) for t in self._scheduled()],
                         recent=[public_item(r) for r in self.recent],
                         history=[public_item(r) for r in reversed(self.history)],
                         archiveBefore={"events": self.recent[-1]["archiveId"] if self.more_events else None,
                                        "history": self.history[0]["archiveId"] if self.more_history else None},
                         llm={**self.dialogue.status(), "keySaved": self.key_saved, "keyNotice": self.key_notice},
                         voice=speech_backend.status())
        return state

    def state(self, stage=False):
        with self.cv:
            return self._state(stage)

    def speech_allowed(self, stop_serial=None):
        with self.cv:
            return None if self.stopped or (stop_serial is not None and self.stop_serial != stop_serial) else self.stop_serial

    def wait(self, revision, stage=False):
        with self.cv:
            if not self.cv.wait_for(lambda: self.closed or self.revision != revision, timeout=5) or self.closed:
                return None
            return self._state(stage)

    def stage_change(self, delta):
        with self.cv:
            self.stage_count += delta
            self._changed()

    def _changed(self):
        self.revision += 1
        self.cv.notify_all()

    @staticmethod
    def _order(task):
        return task["_priority"], task["_stamp"], task["id"]

    def _scheduled(self):
        preferred = AUDIENCE_MIX[self.mix_position]
        def order(task):
            rank, stamp, cue_id = self._order(task)
            if not task.get("_operator") and task["source"] in ("comment", "room_join"):
                return (3, task["source"] != preferred, stamp, cue_id)
            return (rank, False, stamp, cue_id)
        return sorted(self.queue, key=order)

    def _task(self, source, room="", name="", prompt="", segments=None, **fields):
        task = {"id": next(self.ids), "source": source, "roomId": room, "name": name, "prompt": prompt,
                "text": "", "cue": "look", "expression": "neutral", "segments": [],
                "_priority": PRIORITY[source], "_stamp": time.time(), "_readyAt": 0,
                "status": "queued", **fields}
        if source in ("comment", "topic") and not segments:
            segments = quick_reply(task, self.history)
            if segments:
                task.update(_quick=True, planner="local")
        if segments:
            install_segments(task, segments)
        return task

    def _event_status(self, task, status):
        self.store.set_cue_status(task["id"], status)
        for row in self.recent:
            if row.get("cueId") == task["id"]:
                row["status"] = status

    def _enqueue(self, task):
        if len(self.queue) >= MAX_QUEUE:
            # For welcomes and automatic comments of equal priority, make room for recent arrivals.
            def eviction_order(cue):
                priority, captured, ordinal = self._order(cue)
                if cue["source"] == "room_join" or (cue["source"] == "comment" and not cue.get("_operator")):
                    return priority, -captured, -ordinal
                return priority, captured, ordinal
            worst = max(self.queue, key=eviction_order)
            if eviction_order(task) >= eviction_order(worst):
                return False
            self._event_status(worst, "busy")
            self.queue.remove(worst)
        self.queue.append(task)
        return True

    def _receipt(self, cue_id, source, name):
        self.received = {"id": next(self.ids), "cueId": cue_id, "source": source, "name": name,
                         "at": int(time.time() * 1000)}

    def _load_gift_wall(self, room, before=None):
        self.wall_room = room
        self.wall_entries = self.store.gift_wall(room, before)
        self.gift_effects.clear()
        for entry in reversed(self.wall_entries):
            if entry["_counted"]:
                self.combos.increment(room, entry["_viewer"], entry["giftName"], entry["count"],
                                      entry["_captured"], entry["_combo"])

    def _gift(self, row, room, viewer, captured):
        name = row.get("giftName") or "礼物"
        delta = self.combos.increment(room, viewer, name, row.get("displayCount"), captured, row.get("_combo"))
        if not delta:
            return "merged", None
        place_gift(self.wall_entries, row, captured, delta)
        self.store.save_gift_wall(room, self.wall_entries)
        if self.stopped:
            return "ignored", None
        who = row.get("nickname", "")
        script = gift_script(name, delta, [who])
        now = int(time.time() * 1000)
        count = row.get("displayCount", delta)
        self.gift_effects.append({"id": next(self.ids), "eventId": row["eventId"], "giftName": script["giftName"],
                                  "effect": script["effect"], "giftId": script["giftId"], "giftCount": count,
                                  "count": count, "name": who, "nickname": who, "timestamp": now, "at": now})
        if not self.auto:
            return "ignored", None
        merge_key = ("gift", room, gift_merge_key(name))
        streak_key = (room, viewer, merge_key[2], row.get("_combo"))
        last_id = self.gift_streaks.get(streak_key)
        if viewer and delta < count and last_id:
            if self.active and self.active["id"] == last_id:
                active = self.active
                active["giftCount"] += delta
                if active["status"] == "ready":
                    fresh = gift_script(name, active["giftCount"], active["giftViewers"],
                                        variant=active.get("giftVariant", 0))
                    install_segments(active, [fresh["segments"][0], *active["segments"][1:]])
                return "merged", last_id
            if any(r["id"] == last_id and r["status"] == "played" for r in self.history):
                return "merged", last_id
        groups = [t for t in self.queue if t.get("_merge") == merge_key and can_merge_gift(t, script)]
        queued = next((t for t in groups if t["id"] == last_id), groups[0] if groups else None)
        if queued is not None:
            merged = merge_gift(queued, script)
            queued.update(merged)
            queued["name"] = "、".join(merged["giftViewers"])
            install_segments(queued, merged["segments"])
            status, cue_id = "merged", queued["id"]
        else:
            task = self._task("gift", room, who, **script)
            task.update(_merge=merge_key, _stamp=captured,
                        _priority=PRIORITY["gift"] - min(script["giftPrice"], 99999) / 100000)
            if not self._enqueue(task):
                return "busy", None
            status, cue_id = "queued", task["id"]
        self._yield_to_gift()
        if viewer:
            self.gift_streaks[streak_key] = cue_id
            self.gift_streaks.move_to_end(streak_key)
            if len(self.gift_streaks) > 4096:
                self.gift_streaks.popitem(last=False)
        return status, cue_id

    def _yield_to_gift(self):
        cue = self.active
        if not cue or cue["status"] != "ready" or cue["source"] == "gift" or cue.get("_operator"):
            return
        if cue["source"] == "gift_invite":
            self._finish("superseded")
            return
        # No stage has claimed this cue. Put it back with its original event and expiry.
        self.active = None
        self.deadline = 0
        cue.pop("startedAt", None)
        cue.pop("_mixTurn", None)
        if cue.pop("giftInvite", None):
            install_segments(cue, cue.pop("_originalSegments"))
        cue["status"] = "queued"
        if cue["source"] in CROWD_GAP:
            self.crowd_next.pop(cue["_merge"], None)
            pending = next((t for t in self.queue if t.get("_merge") == cue["_merge"]), None)
            if pending:
                pending["_readyAt"] = 0
                self._event_status(cue, "superseded")
                return
        if cue["source"] == "comment" and any(t.get("_burstWinner") and t["roomId"] == cue["roomId"] and
                                              not t.get("_operator") and self._order(t) > self._order(cue)
                                              for t in self.queue):
            self._event_status(cue, "superseded")
            return
        self._event_status(cue, "queued" if self._enqueue(cue) else "superseded")

    def _welcome(self, row, now):
        name = row.get("nickname", "").strip()
        if not name and (row.get("displayCount", 1) > 1 or
                         ("displayCount" not in row and row.get("countText", "").strip())):
            return "ignored", None
        task = self._task("room_join", row["roomId"], name, segments=[beat("欢迎" + name, "neutral", "nod")],
                          eventId=row["eventId"], _stamp=row["capturedAt"] / 1000, _expiresAt=now + WELCOME_LIFETIME)
        return ("queued", task["id"]) if self._enqueue(task) else ("busy", None)

    def _crowd(self, row, room, captured):
        kind = row["type"]
        if kind == "like" and self._room_busy(room, time.monotonic()):
            return "superseded", None
        key = (kind, room)
        count = row.get("displayCount", 1)
        name = row.get("nickname", "")
        task = next((t for t in self.queue if t.get("_merge") == key), None)
        new = task is None
        if new:
            task = self._task(kind, room, name, _merge=key, _count=0, _stamp=captured,
                              _readyAt=self.crowd_next.get(key, 0))
        task["_count"] += count
        number = task["_count"]
        if kind == "like":
            if "displayCount" not in row:
                task["_unknownLikeCount"] = True
            segment = like_beat(task, None if task.get("_unknownLikeCount") else number, self.like_history, self.active)
        else:
            segment = social_beat(task, self.history, self.active)
        install_segments(task, [segment])
        if new and not self._enqueue(task):
            return "busy", None
        return ("queued" if new else "merged"), task["id"]

    def _room_busy(self, room, now):
        return room in self.latest_burst_comment and now < self.comment_arrivals[room][-1] + COMMENT_BURST_GAP

    def _drop_unclaimed_likes(self, room):
        dropped = set()
        for cue in self.queue[:]:
            if cue["source"] == "like" and cue["roomId"] == room:
                dropped.add(cue["id"])
                self._event_status(cue, "superseded")
                self.queue.remove(cue)
        if (self.active and self.active["source"] == "like" and self.active["roomId"] == room
                and self.active["status"] == "ready"):
            # The stage must claim a cue before it can start its audio.
            self.crowd_next.pop(self.active["_merge"], None)
            dropped.add(self.active["id"])
            self._finish("superseded")
        if self.received and self.received["cueId"] in dropped:
            self.received = None

    def _keep_latest_comment(self, task):
        """While chat outruns the mic, keep one unclaimed automatic reply in capture order."""
        room = task["roomId"]
        waiting = [cue for cue in self.queue if cue["roomId"] == room and cue["source"] == "comment"
                   and not cue.get("_operator")]
        now = time.monotonic()
        task["_arrivedAt"] = now
        # Windows are ordered by their last arrival; a quiet room needs no ongoing timer.
        while self.comment_arrivals:
            oldest = next(iter(self.comment_arrivals))
            full = len(self.comment_arrivals) >= 1024 and room not in self.comment_arrivals
            if self.comment_arrivals[oldest][-1] > now - COMMENT_BURST_GAP and not full:
                break
            self.comment_arrivals.pop(oldest)
            self.latest_burst_comment.pop(oldest, None)
        window = self.comment_arrivals.get(room)
        if window is None:
            window = self.comment_arrivals[room] = deque(maxlen=COMMENT_BURST_THRESHOLD)
        self.comment_arrivals.move_to_end(room)
        window.append(now)
        entering_burst = room not in self.latest_burst_comment
        if entering_burst:
            rapid = len(window) >= COMMENT_BURST_THRESHOLD and window[0] >= now - COMMENT_BURST_GAP
            if not rapid and len(waiting) + 1 < COMMENT_BURST_THRESHOLD:
                return True
            self._drop_unclaimed_likes(room)
            active = self.active
            self.latest_burst_comment[room] = (self._order(active) if active and active["roomId"] == room
                                               and active["source"] == "comment" and not active.get("_operator") else None)
        watermark = self.latest_burst_comment[room]
        eligible = [cue for cue in [*waiting, task]
                    if (cue.get("_burstWinner") and not entering_burst) or watermark is None or self._order(cue) >= watermark]
        latest = max(eligible, key=self._order, default=None)
        if latest:
            order = self._order(latest)
            self.latest_burst_comment[room] = max(order, watermark) if watermark else order
            # A short laugh right behind a real question need not drown it out. Only favor fresh material.
            if latest.get("_quick"):
                questions = (cue for cue in eligible if not cue.get("_quick") and cue["_stamp"] >= latest["_stamp"] - 2
                             and cue["_arrivedAt"] >= now - 2 and re.search(r"[?？]|为啥|为什么|怎么|如何|能不能|要不要|该不该|吗$", cue["prompt"]))
                latest = max(questions, key=self._order, default=latest)
            latest["_burstWinner"] = True
        for cue in waiting:
            if cue is latest:
                continue
            if latest and "_planUntil" in cue:
                # Replacing a planning cue must not restart the model wait on every new comment.
                latest["_planUntil"] = min(latest.get("_planUntil", cue["_planUntil"]), cue["_planUntil"])
            self._event_status(cue, "superseded")
            self.queue.remove(cue)
        return latest is task

    def _comment(self, row, selected=False, captured=None):
        if not row.get("content", "").strip():
            return "ignored", None
        task = self._task("comment", row["roomId"], row.get("nickname", ""), row["content"].strip()[:800],
                          eventId=row["eventId"], audience=row.get("_viewer") or row.get("nickname") or None,
                          replyTarget={"name": row.get("nickname", ""), "text": row["content"]},
                          _stamp=captured if captured is not None else row["capturedAt"] / 1000, _operator=selected)
        if selected:
            task["_priority"] = PRIORITY["selected"]
        elif not self._keep_latest_comment(task):
            return "superseded", None
        return ("queued", task["id"]) if self._enqueue(task) else ("busy", None)

    def ingest(self, events):
        with self._write():
            now = time.monotonic()
            self.crowd_next = {k: t for k, t in self.crowd_next.items() if t > now}
            for event_id, room, kind, captured, display in sorted(events, key=lambda event: event[3]):
                row = {"eventId": event_id, "roomId": room, "type": kind, "capturedAt": int(captured * 1000), **display}
                row["archiveId"] = self.store.insert_event(row)
                if row["archiveId"] is None:
                    continue
                if room != self.wall_room:
                    self._load_gift_wall(room, before=row["archiveId"])
                status, cue_id = "ignored", None
                if kind == "gift":
                    status, cue_id = self._gift(row, room, row.get("_viewer") or row.get("nickname"), captured)
                elif self.auto and not self.stopped:
                    if kind == "comment":
                        status, cue_id = self._comment(row, captured=captured)
                    elif kind == "room_join":
                        status, cue_id = self._welcome(row, now)
                    elif kind in CROWD_GAP:
                        status, cue_id = self._crowd(row, room, captured)
                row.update(status=status, cueId=cue_id)
                self._remember_event(row)
                if kind != "gift" and cue_id:
                    self._receipt(cue_id, kind, row.get("nickname", ""))
            self._changed()

    def _remember_event(self, row):
        self.store.set_event_cue(row)
        self.more_events = self.more_events or len(self.recent) == self.recent.maxlen
        self.recent.appendleft(row)

    def _heard_record(self, task, status):
        heard = task.get("_heard", 0)
        aired = task["segments"][:heard]
        text = "".join(segment["text"] for segment in aired)
        if not text:
            return None
        record = {"id": task["id"], "source": task["source"], "roomId": task["roomId"],
                  "name": task["name"], "prompt": task["prompt"], "audience": task.get("audience"),
                  "text": text,
                  "status": status, "at": int(time.time() * 1000)}
        if task.get("giftInvite") and heard == len(task["segments"]):
            record["giftInvite"] = task["giftInvite"]
        for segment in reversed(aired):
            if segment.get("focusItem"):
                record["focusItem"] = segment["focusItem"]
                break
        record["archiveId"] = self.store.save_heard(record)
        return record

    def _finish(self, status):
        task = self.active
        if not task:
            return
        # Keep only segment text that the player confirmed as delivered.
        heard = self._heard_record(task, status)
        if heard:
            if task.get("_mixTurn"):
                self.mix_position = (self.mix_position + 1) % len(AUDIENCE_MIX)
            self.more_history = self.more_history or len(self.history) == self.history.maxlen
            self.history.append(heard)
            if heard["source"] == "like":
                self.like_history.append(heard)
            if heard.get("giftInvite"):
                self.gift_invites.append(heard)
        self._event_status(task, status)
        self.active = None
        self.deadline = 0
        self.stop_serial += 1

    @staticmethod
    def _gift_tail(task, message, response):
        accept = message.get("acceptNextSegment") is True
        if task.get("tailPending"):
            draft = task.get("_tailDraft")
            defer = accept and message["phase"] == "segment" and message.get("deferNextSegment") is True
            if draft or not defer:
                task.pop("_tailDraft", None)
                if draft and accept:
                    install_segments(task, [task["segments"][0], draft])
                task["tailPending"] = False
        if response is not None and (accept or message["phase"] == "segment_end"):
            response.update(nextSegment=task["segments"][1].copy(), tailPending=bool(task.get("tailPending")))

    def playback(self, message, response=None):
        if not isinstance(message, dict) or type(message.get("id")) is not int:
            raise ValueError("invalid cue id")
        player, phase = message.get("player"), message.get("phase")
        if not bounded_string(player, 128) or not player or phase not in ("start", "segment", "segment_end", "complete", "error"):
            raise ValueError("invalid playback acknowledgement")
        with self._write():
            task = self.active
            if not task or task["id"] != message["id"] or self.stopped:
                return False
            if phase == "start":
                if task["status"] != "ready":
                    return task.get("_player") == player
                if "_expiresAt" in task and time.monotonic() >= task["_expiresAt"]:
                    self._finish("expired")
                    self._changed()
                    return False
                if task["source"] == "gift_invite" and not self._room_busy(task["roomId"], time.monotonic()):
                    self._finish("expired")
                    self._changed()
                    return False
                task.update(status="playing", _player=player)
                if task.get("giftInvite") or task["source"] == "gift":
                    now = time.monotonic()
                    self.invite_after = {room: until for room, until in self.invite_after.items() if until > now}
                    self.invite_after[task["roomId"]] = now + BURST_GIFT_INVITE_GAP
            elif task.get("_player") != player:
                return False
            elif phase in ("segment", "segment_end"):
                previous_heard = task.get("_heard", 0)
                index = message.get("index")
                current = task.get("currentSegment", -1)
                if type(index) is not int or not 0 <= index < len(task["segments"]):
                    return False
                if phase == "segment":
                    if index < current or index > current + 1:
                        return False
                    if index > 0 and task.get("tailPending"):
                        # A player may omit segment_end. Its next line is already in playback.
                        task.pop("_tailDraft", None)
                        task["tailPending"] = False
                    task.update(currentSegment=index, _heard=max(task.get("_heard", 0), index))
                    duration = message.get("durationMs")
                    if index != current:
                        task["segmentStartedAt"] = int(time.time() * 1000)
                        if type(duration) is int and 0 < duration <= 180000:
                            task["segmentDurationMs"] = duration
                        else:
                            task.pop("segmentDurationMs", None)
                else:
                    if index != current:
                        return False
                    task["_heard"] = index + 1
                if index == 0 and task["source"] == "gift" and len(task["segments"]) > 1:
                    self._gift_tail(task, message, response)
                if task.get("_heard", 0) > previous_heard:
                    self._heard_record(task, "playing")
            elif phase == "complete":
                if task["text"] and task.get("currentSegment") != len(task["segments"]) - 1:
                    return False
                task["_heard"] = len(task["segments"])
                self._finish("played")
            else:
                self._finish("error")
            if self.active:
                self.deadline = time.monotonic() + PLAY_TIMEOUT
            self._changed()
            return True

    def _select(self, message):
        row = next((r for r in self.recent if r["eventId"] == message.get("eventId") and
                    ("roomId" not in message or r["roomId"] == message["roomId"])), None)
        if not row and "roomId" in message:
            row = self.store.find_comment(message.get("eventId"), message["roomId"])
        if not row or row["type"] != "comment":
            raise ValueError("评论已移出列表或不存在")
        pending = next((t for t in self.queue if t["id"] == row.get("cueId")), None)
        if pending:
            pending.update(_priority=PRIORITY["selected"], _operator=True)
        elif (not self.active or self.active["id"] != row.get("cueId")) and row["status"] != "played":
            status, cid = self._comment(row, selected=True)
            if not cid:
                raise ValueError("队列已满或评论为空")
            row.update(status=status, cueId=cid)
            self.store.set_event_cue(row)
            self._receipt(cid, "comment", row.get("nickname", ""))

    def _configure(self, message):
        key, model = message.get("apiKey"), message.get("model")
        persona = validate_persona(message["persona"]) if "persona" in message else None
        previous_persona = self.dialogue.status()["persona"] if persona is not None else None
        self.dialogue.configure(key, model, persona)
        if persona is not None:
            self.store.set_setting("persona", None if persona == DEFAULT_PERSONA else persona)
            if persona != previous_persona:
                self.persona_version += 1
                for task in self.queue:
                    if task["source"] in ("topic", "comment") and not task.get("_quick"):
                        task.update(segments=[], text="", status="queued")
                        task.pop("_planUntil", None)
                if self.active:
                    self.active.pop("_tailDraft", None)
        if model is not None:
            self.store.set_setting("model", model.strip())
        if key is None:
            return
        self.key_notice = ""
        if not key.strip():
            self.store.set_setting("protectedKey", None)
            self.key_saved = False
            self.dialogue.configure(os.environ.get("DEEPSEEK_API_KEY", "").strip(), None)
            return
        try:
            encrypted = protect_key(key.strip())
        except KeyProtectionError:
            self.key_notice = "输入的密钥仅在本次运行有效。"
            if self.key_saved:
                self.key_notice += "下次启动将尝试使用原先保存的密钥。"
        else:
            self.store.set_setting("protectedKey", encrypted)
            self.key_saved = True

    def control(self, message):
        if not isinstance(message, dict):
            raise ValueError("control must be an object")
        action = message.get("action")
        with self._write():
            if action == "auto":
                enabled = message.get("enabled")
                if type(enabled) is not bool:
                    raise ValueError("enabled must be boolean")
                if self.stopped and enabled:
                    raise ValueError("请先解除急停")
                self.auto = enabled
                if not enabled:
                    for t in self.queue[:]:
                        if not t.get("_operator"):
                            self._event_status(t, "cancelled")
                            self.queue.remove(t)
            elif action == "stop":
                self.auto = False
                self.stopped = True
                self.stop_serial += 1
                for t in self.queue:
                    self._event_status(t, "stopped")
                self.queue.clear()
                self.gift_effects.clear()
                self.received = None
                self._finish("stopped")
                speech_backend.cancel()
            elif action == "reset":
                self.stopped = False
                self.auto = False
            elif action in ("settings", "configure"):
                self._configure(message)
            elif action == "speech_rate":
                speech_backend.set_rate(message.get("rate"))
                self.store.set_setting("rate", message["rate"])
            elif self.stopped:
                raise ValueError("请先解除急停")
            elif action == "skip":
                expected = message.get("id")
                current_id = self.active["id"] if self.active else self.planning
                if expected is not None and expected != current_id:
                    return self._state()
                if self.active:
                    self._finish("skipped")
                    speech_backend.cancel()
                elif self.planning is not None:
                    t = next((t for t in self.queue if t["id"] == self.planning), None)
                    if t:
                        self._event_status(t, "skipped")
                        self.queue.remove(t)
            elif action in ("reply", "select"):
                self._select(message)
            elif action in ("submit", "topic", "manual"):
                text = message.get("text", "")
                name = message.get("name", message.get("nickname", ""))
                manual = action == "manual"
                if not bounded_string(text, 120 if manual else 800) or not bounded_string(name, 80):
                    raise ValueError("台词、投稿或称呼过长")
                text, name = text.strip(), name.strip()
                if manual:
                    cue, exp = message.get("cue", "talk"), message.get("expression", "neutral")
                    if not isinstance(cue, str) or cue not in GESTURES or not isinstance(exp, str) or exp not in EXPRESSIONS:
                        raise ValueError("动作或表情无效")
                    if cue == "talk" and not text:
                        raise ValueError("请输入要播出的台词")
                    task = self._task("manual", name=name, segments=[beat(text, exp, cue)], _operator=True)
                else:
                    if not text:
                        raise ValueError("请输入投稿正文")
                    room = next((r["roomId"] for r in self.recent if r["roomId"]), "studio")
                    task = self._task("topic", room, name, text, audience=name or None, _operator=True,
                                      replyTarget={"name": name, "text": text})
                if not self._enqueue(task):
                    raise ValueError("播出队列已满")
                row = {"eventId": str(uuid4()), "roomId": task["roomId"], "type": task["source"],
                       "capturedAt": int(time.time() * 1000), "nickname": name, "content": text}
                if manual:
                    row.update(gesture=cue, expression=exp)
                row["archiveId"] = self.store.insert_event(row, origin="director")
                row.update(status="queued", cueId=task["id"])
                self._remember_event(row)
                if not manual:
                    self._receipt(task["id"], "topic", name)
            else:
                raise ValueError("unknown action")
            if action in ("auto", "stop", "reset"):
                if not self.auto:
                    self.comment_arrivals.clear()
                    self.latest_burst_comment.clear()
                self.store.set_setting("auto", self.auto)
                self.store.set_setting("stopped", self.stopped)
            self._changed()
            return self._state()

    def _plan(self, task, history, version):
        try:
            segments, mode = self.dialogue.plan(task, history)
        except Exception:
            segments, mode = local_reply(task, history), "fallback"
        with self.cv:
            self.planning = None
            if (version == self.persona_version and task in self.queue and not self.closed and not task["segments"]
                    and time.monotonic() <= task["_planUntil"]):
                install_segments(task, segments)
                task.update(status="queued", planner=mode)
            self._changed()

    def _prepare_gift(self, task, now):
        history = on_air_history(task, self.history)
        variant = live_gift_variant(task, history)
        if variant != task["giftVariant"]:
            task.update(gift_script(task["giftName"], task["giftCount"], task["giftViewers"], variant=variant))
        original = {**task, "segments": task["segments"]}
        fallback = contextual_gift(original, history)
        install_segments(task, fallback)
        if self.refining_gift is not None or not self.dialogue.status()["configured"]:
            return
        # The original closing line is fully playable even if the service never returns.
        # The stage may accept a draft only before it requests audio for that closing line.
        self.refining_gift = task["id"]
        task["tailPending"] = True
        version = self.persona_version
        def refine():
            try:
                draft, mode = model_gift_segments(self.dialogue, original, history)
                with self.cv:
                    if (mode == "deepseek" and version == self.persona_version and self.active is task
                            and task["tailPending"] and time.monotonic() <= now + GIFT_REWRITE_BUDGET):
                        task["_tailDraft"] = draft[-1]
            finally:
                with self.cv:
                    self.refining_gift = None
                    self.cv.notify_all()
        Thread(target=refine, name="gift-closing-line", daemon=True).start()

    def _run(self):
        try:
            self._broadcast()
        except sqlite3.Error:
            # The write guard has paused this session. A restart recovers committed data.
            return

    @staticmethod
    def _queued_quick_reply(scheduled, priority):
        # Use the idle mic while a peer waits for the model. Keep each viewer's turn order.
        waiting = set()
        for task in scheduled:
            if task["_priority"] != priority:
                continue
            viewer = (task["roomId"], task.get("audience"))
            if task.get("_quick") and viewer not in waiting:
                return task
            if viewer[1]:
                waiting.add(viewer)
        return None

    def _busy_comment(self, task, now):
        return task.get("_burstWinner") and not task.get("_operator") and self._room_busy(task["roomId"], now)

    def _prepare_comment(self, task, now, has_welcome):
        """Choose the on-air cue. A standalone invitation has no link to the viewer's comment."""
        room = task["roomId"]
        busy = self._busy_comment(task, now)
        if task.get("_quick"):
            install_segments(task, quick_reply(task, self.history))
        if task.get("_operator"):
            return task
        room_turn = bool(task.get("_quick"))
        repeated = False
        if task.get("planner") == "deepseek":
            def spoken_key(text):
                return "".join(c for c in text.casefold() if c.isalnum())
            reply = spoken_key(task["text"])
            recent = [row for row in self.history if row["roomId"] == room and row["source"] == "comment"][-8:]
            if len(reply) >= 8 and any(
                    spoken_key(row["text"].removesuffix(row.get("giftInvite") or "")) == reply and
                    spoken_key(row["prompt"]) != spoken_key(task["prompt"]) for row in recent):
                alternative = local_reply(task, self.history)
                local_text = spoken_key("".join(part["text"] for part in alternative))
                if local_text != reply and not is_generic_reply(alternative):
                    install_segments(task, alternative)
                    task["planner"] = "fallback"
                elif busy:
                    room_turn = True
                    repeated = True
        if not busy:
            return task
        parts = task["segments"]
        generic = task.get("planner") in ("local", "fallback") and is_generic_reply(parts)
        invite_due = now >= self.invite_after.get(room, 0) and not mentions_gifts(task["prompt"])
        if invite_due:
            recent = [row["giftInvite"] for row in self.gift_invites if row["roomId"] == room]
            if (room_turn or generic) and not has_welcome:
                line = make_gift_invite(recent)
                return self._task("gift_invite", room, segments=[line], planner="local", giftInvite=line["text"],
                                  _expiresAt=now + COMMENT_BURST_GAP)
            invited = parts if generic or repeated else append_gift_invite(parts, recent, max_chars=MAX_TTS_TEXT)
            if invited is not parts:
                task["_originalSegments"] = parts
                task["giftInvite"] = invited[-1]["text"][len(parts[-1]["text"]):].lstrip("。")
                install_segments(task, invited)
        return None if generic or repeated else task

    def _broadcast(self):
        with self.cv:
            while not self.closed and not self.storage_failed:
                now = time.monotonic()
                if self.active and self.deadline <= now:
                    with self._write():
                        self._finish("expired")
                    self._changed()
                next_expiry = min((t["_expiresAt"] for t in self.queue if "_expiresAt" in t), default=None)
                if next_expiry is not None and next_expiry <= now:
                    with self._write():
                        for cue in self.queue[:]:
                            if "_expiresAt" in cue and cue["_expiresAt"] <= now:
                                self._event_status(cue, "expired")
                                self.queue.remove(cue)
                    self._changed()
                    continue
                if self.active:
                    wake = self.deadline if next_expiry is None else min(self.deadline, next_expiry)
                    self.cv.wait(max(.01, wake - now))
                    continue
                scheduled = self._scheduled()
                welcome = next((t for t in scheduled if t["source"] == "room_join" and t["_readyAt"] <= now), None)
                for task in scheduled:
                    if task["_readyAt"] > now:
                        continue
                    if not task["segments"]:
                        deadline = task.setdefault("_planUntil", now + COMMENT_PLAN_BUDGET)
                        exhausted_worker = self.planning is not None and not any(
                            t["id"] == self.planning for t in self.queue)
                        if now >= deadline or exhausted_worker:
                            install_segments(task, local_reply(task, list(self.history)))
                            task.update(status="queued", planner="fallback")
                        else:
                            starting = self.planning is None
                            if starting:
                                self.planning = task["id"]
                                task["status"] = "planning"
                                Thread(target=self._plan, args=(task, list(self.history), self.persona_version),
                                       name="dialogue", daemon=True).start()
                                self._changed()
                            quick = self._queued_quick_reply(scheduled, task["_priority"])
                            if quick is None:
                                if welcome and task["source"] == "comment" and not task.get("_operator"):
                                    if starting:
                                        # The local planner can finish before this ready welcome takes the mic.
                                        self.cv.wait(.02)
                                        break
                                    quick = welcome
                                else:
                                    self.cv.wait(max(.001, deadline - now))
                                    break
                            task = quick
                    self.queue.remove(task)
                    if task["source"] in ("comment", "topic"):
                        on_air = self._prepare_comment(task, now, welcome is not None)
                        if on_air is not task:
                            with self._write():
                                self._event_status(task, "superseded")
                            if on_air is None:
                                self._changed()
                                break
                            task = on_air
                    # Borrow unused turns freely. Advance only when the intended choice was
                    # contested and the stage later confirms it actually delivered some audio.
                    if task["source"] == AUDIENCE_MIX[self.mix_position] and not task.get("_operator"):
                        other = "room_join" if task["source"] == "comment" else "comment"
                        task["_mixTurn"] = any(t["source"] == other and not t.get("_operator") and t["_readyAt"] <= now
                                               for t in self.queue)
                    if task["source"] == "gift":
                        self._prepare_gift(task, now)
                    task.update(status="ready", startedAt=int(time.time() * 1000))
                    self.active = task
                    self.deadline = task.get("_expiresAt", now + READY_TIMEOUT)
                    if task["source"] in CROWD_GAP:
                        self.crowd_next[task["_merge"]] = now + CROWD_GAP[task["source"]]
                    with self._write():
                        self._event_status(task, "active")
                    self._changed()
                    break
                else:
                    wake = min((t["_readyAt"] for t in self.queue if t["_readyAt"] > now), default=None)
                    self.cv.wait(max(.001, wake - now) if wake is not None else None)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _from_stage(self, url):
        referrer = self.headers.get("Referer", "").partition("?")[0].partition("#")[0]
        return "stage" in parse_qs(url.query).get("view", ()) or referrer.endswith("/stage.html")

    def _valid_origin(self):
        valid_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.server.server_port == 80:
            valid_hosts.update(("127.0.0.1", "localhost"))
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        if len(hosts) != 1 or hosts[0].lower() not in valid_hosts or len(origins) > 1:
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            return False
        return not origins or origins[0].lower() == f"http://{hosts[0].lower()}"

    def _response(self, code, data=None, content_type=None):
        self.send_response(code)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        if content_type:
            self.send_header("Content-Type", content_type)
        if code != 204:
            self.send_header("Content-Length", str(len(data or b"")))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _json(self, code, payload):
        self._response(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _reject(self, code, reason):
        self.close_connection = True
        self._json(code, {"error": reason})

    def do_OPTIONS(self):
        self._reject(403, "cross-origin access is not permitted")

    def do_POST(self):
        if not self._valid_origin():
            return self._reject(403, "invalid host or origin")
        url = urlsplit(self.path)
        path = url.path
        if path not in ("/live-events", "/api/control", "/api/playback", "/api/tts", "/api/tts/cancel", "/api/persona/preview"):
            return self._reject(404, "not found")
        if path in ("/api/control", "/api/persona/preview") and self._from_stage(url):
            return self._reject(403, "此操作仅在导播台提供")
        if self.headers.get("Transfer-Encoding"):
            return self._reject(400, "transfer encoding not supported")
        if self.headers.get_content_type() != "application/json":
            return self._reject(415, "expected application/json")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch("[0-9]{1,12}", lengths[0]):
            return self._reject(411, "content length required")
        length = int(lengths[0])
        if length > MAX_BODY:
            return self._reject(413, "request body too large")
        try:
            self.connection.settimeout(5)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete body")
            message = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON")))
            if path == "/live-events":
                self.server.scheduler.ingest(validate(message))
                self._response(204)
            elif path == "/api/control":
                self._json(200, self.server.scheduler.control(message))
            elif path == "/api/persona/preview":
                self._json(200, self.server.scheduler.preview(message))
            elif path == "/api/playback":
                result = {}
                result["accepted"] = self.server.scheduler.playback(message, result)
                self._json(200, result)
            elif path == "/api/tts/cancel":
                request_id = message.get("requestId") if isinstance(message, dict) else None
                if not bounded_string(request_id, 180) or not request_id:
                    raise ValueError("requestId is required")
                speech_backend.cancel(request_id)
                self._response(204)
            else:
                self._tts(message)
        except (ValueError, RecursionError, TimeoutError) as error:
            self._reject(400, str(error) if isinstance(error, ValueError) else "invalid request")
        except PreviewBusy as error:
            self._reject(429, str(error))
        except sqlite3.Error:
            self._reject(503, "本机记录无法写入，播出已暂停。请检查数据目录后重启。")

    def _tts(self, message):
        text = message.get("text") if isinstance(message, dict) else None
        if not bounded_string(text, MAX_TTS_TEXT) or not text.strip():
            raise ValueError(f"text must contain 1–{MAX_TTS_TEXT} characters")
        request_id = message.get("requestId")
        if request_id is not None and (not bounded_string(request_id, 180) or not request_id):
            raise ValueError("invalid requestId")
        stop_serial = self.server.scheduler.speech_allowed()
        if stop_serial is None:
            self._json(503, {"error": "cue playback is stopped"})
            return
        if not self.server.tts_slots.acquire(blocking=False):
            self._json(503, {"error": "speech backend is busy"})
            return
        try:
            accepts = self.headers.get("Accept", "").lower().split(",")
            if PCM_MEDIA_TYPE in (item.strip() for item in accepts):
                self._tts_stream(text, request_id, stop_serial)
                return
            try:
                audio = speech_backend.wav(text, request_id)
            except Exception:
                audio = None
        finally:
            self.server.tts_slots.release()
        if not isinstance(audio, bytes) or not audio or self.server.scheduler.speech_allowed(stop_serial) is None:
            self._json(503, {"error": "local speech backend not available"})
            return
        self._response(200, audio, "audio/wav")

    def _tts_stream(self, text, request_id, stop_serial):
        chunks = speech_backend.pcm_chunks(text, request_id)
        started = False
        try:
            first = next(chunks)
            if not first or self.server.scheduler.speech_allowed(stop_serial) is None:
                self._json(503, {"error": "speech unavailable"})
                return
            self.send_response(200)
            self.send_header("Content-Type", PCM_MEDIA_TYPE)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Transfer-Encoding", "chunked")
            started = True
            self.end_headers()
            for block in itertools.chain((first,), chunks):
                if self.server.scheduler.speech_allowed(stop_serial) is None:
                    self.close_connection = True
                    return
                if block:
                    self.wfile.write(f"{len(block):x}\r\n".encode("ascii") + block + b"\r\n")
                    self.wfile.flush()
            if self.server.scheduler.speech_allowed(stop_serial) is None:
                self.close_connection = True
                return
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (RuntimeError, StopIteration, OSError):
            if started:
                # No terminating zero chunk: the browser must discard an incomplete generation.
                self.close_connection = True
            else:
                self._json(503, {"error": "local speech backend not available"})
        finally:
            chunks.close()

    def do_GET(self):
        if not self._valid_origin():
            return self._reject(403, "invalid host or origin")
        url = urlsplit(self.path)
        path = url.path
        query = parse_qs(url.query)
        stage = self._from_stage(url)
        if path == "/api/archive":
            if stage:
                return self._reject(403, "记录仅在导播台提供")
            try:
                kind = query.get("kind", ["events"])[0]
                before = int(query["before"][0]) if "before" in query else None
                limit = int(query.get("limit", ["60"])[0])
                return self._json(200, self.server.scheduler.archive(kind, before, limit))
            except ValueError:
                return self._reject(400, "记录类型或分页参数无效")
            except sqlite3.Error:
                return self._reject(503, "无法读取本机记录")
        if path == "/api/state":
            return self._json(200, self.server.scheduler.state(stage))
        if path == "/api/voice/status":
            return self._json(200, speech_backend.status())
        if path == "/api/stream":
            return self._stream(stage)
        candidate = (WEB / unquote(path).lstrip("/")).resolve()
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_relative_to(WEB) or not candidate.is_file():
            return self._reject(404, "not found")
        content_type = {".js": "text/javascript", ".css": "text/css",
                        ".glb": "model/gltf-binary"}.get(candidate.suffix.lower())
        content_type = content_type or mimetypes.guess_type(candidate)[0] or "application/octet-stream"
        self._response(200, candidate.read_bytes(), content_type)

    def _stream(self, stage):
        self.close_connection = True
        self.connection.settimeout(10)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Connection", "close")
        self.end_headers()
        if stage:
            self.server.scheduler.stage_change(1)
        try:
            revision = -1
            while not self.server.scheduler.closed:
                state = self.server.scheduler.wait(revision, stage)
                if state is None:
                    self.wfile.write(b": heartbeat\n\n")
                else:
                    revision = state["revision"]
                    raw = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"event: state\nid: {revision}\ndata: {raw}\n\n".encode())
                self.wfile.flush()
        except (OSError, TimeoutError):
            pass
        finally:
            if stage:
                self.server.scheduler.stage_change(-1)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows SO_REUSEADDR permits two listeners to accept traffic on the same live port.
    allow_reuse_address = os.name != "nt" and ThreadingHTTPServer.allow_reuse_address

    def __init__(self, port, data_path=None):
        self.scheduler = None
        super().__init__(("127.0.0.1", port), Handler)
        try:
            self.tts_slots = BoundedSemaphore(2)
            if data_path is None and port:
                data_path = studio_path(port)
            self.scheduler = Scheduler(data_path=data_path)
        except BaseException:
            super().server_close()
            raise

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def server_close(self):
        try:
            # TCPServer calls this override on bind/activate failure, before we own those resources.
            if self.scheduler is not None:
                self.scheduler.close()
                speech_backend.shutdown()
        finally:
            super().server_close()


def main():
    parser = argparse.ArgumentParser(description="豆姐锐评室本地控制台")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1", help=argparse.SUPPRESS)
    parser.add_argument("--strictPort", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    with LocalServer(args.port) as server:
        speech_backend.warmup()
        print(f"豆姐锐评室：http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
