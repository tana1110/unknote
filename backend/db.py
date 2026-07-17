"""SQLite storage for notes and their analysis history.

One table. Each row is a note plus the structured analysis Claude produced for
it. `analysis` is stored as a JSON string so the frontend can render each
section separately without a second table.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "smart_notes.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                content     TEXT    NOT NULL,
                analysis    TEXT    NOT NULL,   -- JSON blob of the 4 sections
                created_at  TEXT    NOT NULL,
                folder      TEXT,            -- user's own folder label; NULL = unfiled
                pinned      INTEGER NOT NULL DEFAULT 0   -- 1 = kept at the top
            )
            """
        )
        # migrate older databases that predate these columns
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(notes)")}
        if "folder" not in cols:
            conn.execute("ALTER TABLE notes ADD COLUMN folder TEXT")
        if "pinned" not in cols:
            conn.execute("ALTER TABLE notes ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")


def save_note(content: str, analysis: dict | None = None,
              folder: str | None = None, pinned: bool = False) -> dict:
    """Save a note. `analysis` may be None for a plain, un-analyzed note.
    `folder`/`pinned` are normally defaults; restore passes them to bring a
    deleted note back exactly as it was."""
    created_at = datetime.now(timezone.utc).isoformat()
    folder = (folder or "").strip() or None
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO notes (content, analysis, created_at, folder, pinned) "
            "VALUES (?, ?, ?, ?, ?)",
            (content, json.dumps(analysis), created_at, folder, 1 if pinned else 0),
        )
        note_id = cur.lastrowid
    return get_note(note_id)


def update_content(note_id: int, content: str) -> dict | None:
    """Rewrite a note's text in place (autosave). Analysis is left alone."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE notes SET content = ? WHERE id = ?", (content, note_id)
        )
        if cur.rowcount == 0:
            return None
    return get_note(note_id)


def set_pinned(note_id: int, pinned: bool) -> dict | None:
    """Pin a note to the top (or unpin it)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE notes SET pinned = ? WHERE id = ?", (1 if pinned else 0, note_id)
        )
        if cur.rowcount == 0:
            return None
    return get_note(note_id)


def set_folder(note_id: int, folder: str | None) -> dict | None:
    """File a note into a folder the user named (or clear it with None)."""
    folder = (folder or "").strip() or None
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE notes SET folder = ? WHERE id = ?", (folder, note_id)
        )
        if cur.rowcount == 0:
            return None
    return get_note(note_id)


def update_analysis(note_id: int, analysis: dict) -> dict | None:
    """Attach an analysis to an existing note (analyze-later)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE notes SET analysis = ? WHERE id = ?",
            (json.dumps(analysis), note_id),
        )
        if cur.rowcount == 0:
            return None
    return get_note(note_id)


_COLS = "id, content, analysis, created_at, folder, pinned"


def list_notes() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM notes ORDER BY pinned DESC, id DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_note(note_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {_COLS} FROM notes WHERE id = ?", (note_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_note(note_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    return cur.rowcount > 0


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "content": row["content"],
        "analysis": json.loads(row["analysis"]),
        "created_at": row["created_at"],
        "folder": row["folder"],
        "pinned": bool(row["pinned"]),
    }
