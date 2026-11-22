"""Local broadcast archive. The scheduler serializes use of this connection."""
import json
import os
from pathlib import Path
import sqlite3
from gift_rules import GiftCombos
from gift_wall import place_gift


def studio_path(port):
    override = os.environ.get("DOUJIE_DATA_DIR")
    if override:
        folder = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
        folder = (Path(base) if base else Path.home() / ".local" / "share") / "DoujieStudio" / "data"
    return folder / f"studio-{port}.sqlite3"


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class StudioStore:
    def __init__(self, path=None):
        if path is not None:
            Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(path or ":memory:", check_same_thread=False)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    archive_id INTEGER PRIMARY KEY, origin TEXT NOT NULL, room TEXT NOT NULL,
                    event_id TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
                    cue_id INTEGER, UNIQUE(origin, room, event_id)
                );
                CREATE INDEX IF NOT EXISTS events_by_cue ON events(cue_id);
                CREATE INDEX IF NOT EXISTS events_by_status ON events(status);
                CREATE INDEX IF NOT EXISTS archived_gifts_by_room ON events(room,archive_id)
                    WHERE origin='collector' AND json_extract(payload,'$.type')='gift';
                CREATE TABLE IF NOT EXISTS gift_walls (room TEXT PRIMARY KEY, entries TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS history (
                    archive_id INTEGER PRIMARY KEY, cue_id INTEGER NOT NULL UNIQUE,
                    payload TEXT NOT NULL, status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS history_by_status ON history(status);
                CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            with self.db:
                # A former player cannot resume or acknowledge audio in this session.
                self.db.execute("""UPDATE events SET status='interrupted' WHERE status='merged' AND
                    cue_id IN (SELECT cue_id FROM events WHERE status IN ('queued','active'))""")
                self.db.execute("UPDATE events SET status='interrupted' WHERE status IN ('queued','active')")
                self.db.execute("UPDATE history SET status='interrupted' WHERE status='playing'")
        except BaseException:
            self.db.close()
            raise

    def next_cue(self):
        last = [self.db.execute(f"SELECT MAX(cue_id) FROM {table}").fetchone()[0] or 0
                for table in ("events", "history")]
        return max(last) + 1

    def last_collector_room(self):
        row = self.db.execute("SELECT room FROM events WHERE origin='collector' ORDER BY archive_id DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def gift_wall(self, room, before=None):
        saved = self.db.execute("SELECT entries FROM gift_walls WHERE room=?", (room,)).fetchone()
        if saved:
            return json.loads(saved[0])
        # Older studios have raw gift observations but no materialized wall.
        query = """SELECT archive_id,payload FROM events WHERE room=? AND origin='collector'
                   AND json_extract(payload,'$.type')='gift'"""
        args = [room]
        if before is not None:
            query += " AND archive_id < ?"
            args.append(before)
        combos, entries = GiftCombos(), []
        for archive_id, payload in self.db.execute(query + " ORDER BY archive_id", args):
            row = json.loads(payload)
            row["archiveId"] = archive_id
            captured = row["capturedAt"] / 1000
            delta = combos.increment(room, row.get("_viewer") or row.get("nickname"), row.get("giftName"),
                                     row.get("displayCount"), captured)
            if delta:
                place_gift(entries, row, captured, delta)
        return entries

    def save_gift_wall(self, room, entries):
        self.db.execute("INSERT OR REPLACE INTO gift_walls(room,entries) VALUES (?,?)", (room, encode(entries)))

    def settings(self):
        return {key: json.loads(value) for key, value in self.db.execute("SELECT name,value FROM settings")}

    def set_setting(self, name, value):
        if value is None:
            self.db.execute("DELETE FROM settings WHERE name=?", (name,))
        else:
            self.db.execute("INSERT OR REPLACE INTO settings(name,value) VALUES (?,?)", (name, encode(value)))

    def insert_event(self, row, origin="collector"):
        payload = {k: v for k, v in row.items() if k != "_combo"}
        cur = self.db.execute("""INSERT INTO events(origin,room,event_id,payload,status)
            VALUES (?,?,?,?,'ignored') ON CONFLICT(origin,room,event_id) DO NOTHING""",
            (origin, row["roomId"], row["eventId"], encode(payload)))
        return cur.lastrowid if cur.rowcount else None

    def set_event_cue(self, row):
        self.db.execute("UPDATE events SET cue_id=?,status=? WHERE archive_id=?",
                        (row.get("cueId"), row["status"], row["archiveId"]))

    def set_cue_status(self, cue_id, status):
        self.db.execute("UPDATE events SET status=? WHERE cue_id=?", (status, cue_id))

    def save_heard(self, record):
        self.db.execute("""INSERT INTO history(cue_id,payload,status) VALUES (?,?,?)
            ON CONFLICT(cue_id) DO UPDATE SET payload=excluded.payload,status=excluded.status""",
            (record["id"], encode(record), record["status"]))
        return self.db.execute("SELECT archive_id FROM history WHERE cue_id=?", (record["id"],)).fetchone()[0]

    @staticmethod
    def _row(db_row):
        archive_id, data, status, cue_id = db_row
        row = json.loads(data)
        row.update(status=status, archiveId=archive_id)
        if "eventId" in row:
            row["cueId"] = cue_id
        return row

    def find_comment(self, event_id, room):
        if not isinstance(event_id, str) or (room is not None and not isinstance(room, str)):
            return None
        result = self.db.execute("""SELECT archive_id,payload,status,cue_id FROM events
            WHERE origin='collector' AND room=? AND event_id=?""", (room, event_id)).fetchone()
        return self._row(result) if result else None

    def page(self, kind, before=None, limit=60):
        if kind not in ("events", "history") or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("记录类型或分页数量无效")
        if before is not None and (type(before) is not int or not 1 <= before <= 2**63-1):
            raise ValueError("分页位置无效")
        where = "status != 'playing'" if kind == "history" else "1"
        args = []
        if before is not None:
            where += " AND archive_id < ?"
            args.append(before)
        args.append(limit + 1)
        rows = self.db.execute(f"""SELECT archive_id,payload,status,cue_id FROM {kind}
            WHERE {where} ORDER BY archive_id DESC LIMIT ?""", args).fetchall()
        items = [self._row(r) for r in rows[:limit]]
        return items, items[-1]["archiveId"] if len(rows) > limit else None
