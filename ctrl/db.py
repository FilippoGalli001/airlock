"""SQLite state on ctrl: documents, the event timeline, and the daily LLM budget. ctrl is never restored."""
import json
import os
import sqlite3
import threading
import time
from datetime import date

from . import config

_lock = threading.RLock()  # one shared connection: every read and write goes through it
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, ext TEXT NOT NULL, source TEXT NOT NULL,
  box_file_id TEXT UNIQUE, sha256 TEXT, size INTEGER, status TEXT NOT NULL,
  proposal TEXT, decision TEXT, review TEXT, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL, data TEXT);
CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY, llm_calls INTEGER NOT NULL DEFAULT 0);
"""


def connect():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(os.path.join(config.DATA_DIR, "airlock.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


CONN = None


def db():
    global CONN
    if CONN is None:
        CONN = connect()
    return CONN


def _row(r):
    if r is None:
        return None
    d = dict(r)
    for k in ("proposal", "decision", "review"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    return d


def add_document(name, ext, source, sha256, size, box_file_id=None):
    now = time.time()
    with _lock, db():
        cur = db().execute(
            "INSERT INTO documents(name, ext, source, box_file_id, sha256, size, status, created, updated)"
            " VALUES (?,?,?,?,?,?,?,?,?)", (name, ext, source, box_file_id, sha256, size, "queued", now, now))
        return cur.lastrowid


def known_box_ids():
    with _lock:
        return {r[0] for r in db().execute("SELECT box_file_id FROM documents WHERE box_file_id IS NOT NULL")}


def update(doc_id, **fields):
    for k in ("proposal", "decision", "review"):
        if k in fields and fields[k] is not None:
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    fields["updated"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, db():
        db().execute(f"UPDATE documents SET {cols} WHERE id=?", (*fields.values(), doc_id))


def claim(doc_id, from_status, to_status):
    """Atomically move a document from one status to another. False if someone else got there first."""
    with _lock, db():
        cur = db().execute("UPDATE documents SET status=?, updated=? WHERE id=? AND status=?",
                           (to_status, time.time(), doc_id, from_status))
        return cur.rowcount == 1


def get(doc_id):
    with _lock:
        return _row(db().execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())


def documents(limit=100):
    with _lock:
        return [_row(r) for r in db().execute("SELECT * FROM documents ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def active_drill():
    """The id of a red-team drill that is queued or running, else None."""
    with _lock:
        r = db().execute("SELECT id FROM documents WHERE source='redteam' AND status IN ('queued','processing')"
                         " ORDER BY id LIMIT 1").fetchone()
    return r[0] if r else None


def prune_drills(keep_id):
    """Delete every finished red-team drill except keep_id, so public drills never push real documents
    off the queue. Returns the deleted ids (the caller removes their files)."""
    with _lock, db():
        ids = [r[0] for r in db().execute(
            "SELECT id FROM documents WHERE source='redteam' AND id != ? AND status NOT IN ('queued','processing')",
            (keep_id,))]
        for i in ids:
            db().execute("DELETE FROM events WHERE document_id=?", (i,))
            db().execute("DELETE FROM documents WHERE id=?", (i,))
    return ids


def next_queued():
    with _lock:
        r = db().execute("SELECT id FROM documents WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
    return r[0] if r else None


def event(doc_id, kind, **data):
    with _lock, db():
        db().execute("INSERT INTO events(document_id, ts, kind, data) VALUES (?,?,?,?)",
                     (doc_id, time.time(), kind, json.dumps(data, ensure_ascii=False, default=str)))


def events(doc_id):
    with _lock:
        rows = db().execute("SELECT * FROM events WHERE document_id=? ORDER BY id", (doc_id,)).fetchall()
    return [{"ts": r["ts"], "kind": r["kind"], **json.loads(r["data"] or "{}")} for r in rows]


def today_llm_calls():
    with _lock:
        r = db().execute("SELECT llm_calls FROM budget WHERE day=?", (date.today().isoformat(),)).fetchone()
    return r[0] if r else 0


def spend_llm_call():
    """Count one LLM call against today's cap. Returns False when the cap is reached."""
    day = date.today().isoformat()
    with _lock, db():
        db().execute("INSERT OR IGNORE INTO budget(day, llm_calls) VALUES (?, 0)", (day,))
        n = db().execute("SELECT llm_calls FROM budget WHERE day=?", (day,)).fetchone()[0]
        if n >= config.DAILY_LLM_CALLS:
            return False
        db().execute("UPDATE budget SET llm_calls = llm_calls + 1 WHERE day=?", (day,))
        return True
