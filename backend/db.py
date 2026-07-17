"""SQLite storage — now multi-user.

Three tables:
  - users:    one row per account (username + salted password hash)
  - sessions: a login token -> user_id
  - notes:    each note belongs to a user_id; every query is scoped to it, so
              one person can never see or touch another person's notes.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "smart_notes.db"

# password hashing (stdlib only — no extra dependency)
_PBKDF_ROUNDS = 200_000


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
                user_id     INTEGER,         -- owner; every query filters on this
                content     TEXT    NOT NULL,
                analysis    TEXT    NOT NULL,
                created_at  TEXT    NOT NULL,
                folder      TEXT,
                pinned      INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                pw          TEXT    NOT NULL,     -- "salt$hash", both hex
                created_at  TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token       TEXT    PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                created_at  TEXT    NOT NULL
            )
            """
        )
        # migrate older single-user databases
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(notes)")}
        if "folder" not in cols:
            conn.execute("ALTER TABLE notes ADD COLUMN folder TEXT")
        if "pinned" not in cols:
            conn.execute("ALTER TABLE notes ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        if "user_id" not in cols:
            # pre-accounts notes become ownerless (user_id NULL) — invisible to
            # every account, so no one inherits someone else's old notes.
            conn.execute("ALTER TABLE notes ADD COLUMN user_id INTEGER")


# ---- accounts ------------------------------------------------------------

def _hash_pw(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF_ROUNDS)
    return f"{salt}${dk.hex()}"


def create_user(username: str, password: str) -> dict | None:
    """Create an account. Returns the user, or None if the name is taken."""
    username = username.strip()
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, pw, created_at) VALUES (?, ?, ?)",
                (username, _hash_pw(password), created_at),
            )
            uid = cur.lastrowid
            # The very first account inherits any pre-accounts notes, so the
            # person who was using it single-user keeps their notes.
            is_first = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 1
            if is_first:
                conn.execute("UPDATE notes SET user_id = ? WHERE user_id IS NULL", (uid,))
            return {"id": uid, "username": username}
    except sqlite3.IntegrityError:
        return None


def verify_user(username: str, password: str) -> dict | None:
    """Check a login. Returns the user on success, else None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, pw FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    if not row:
        return None
    salt = row["pw"].split("$", 1)[0]
    # constant-time compare to avoid leaking timing information
    if not hmac.compare_digest(_hash_pw(password, salt), row["pw"]):
        return None
    return {"id": row["id"], "username": row["username"]}


def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, datetime.now(timezone.utc).isoformat()),
        )
    return token


def user_for_token(token: str | None) -> dict | None:
    """Resolve a session token to its user, or None."""
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.username FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
    return {"id": row["id"], "username": row["username"]} if row else None


def delete_session(token: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# ---- notes (all scoped to a user) ----------------------------------------

def save_note(user_id: int, content: str, analysis: dict | None = None,
              folder: str | None = None, pinned: bool = False) -> dict:
    """Save a note owned by user_id."""
    created_at = datetime.now(timezone.utc).isoformat()
    folder = (folder or "").strip() or None
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO notes (user_id, content, analysis, created_at, folder, pinned) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, content, json.dumps(analysis), created_at, folder, 1 if pinned else 0),
        )
        note_id = cur.lastrowid
    return get_note(user_id, note_id)


def _update(user_id: int, note_id: int, sql_set: str, params: tuple) -> dict | None:
    """Run a scoped UPDATE; returns the fresh note or None if not the user's."""
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE notes SET {sql_set} WHERE id = ? AND user_id = ?",
            (*params, note_id, user_id),
        )
        if cur.rowcount == 0:
            return None
    return get_note(user_id, note_id)


def update_content(user_id: int, note_id: int, content: str) -> dict | None:
    return _update(user_id, note_id, "content = ?", (content,))


def set_pinned(user_id: int, note_id: int, pinned: bool) -> dict | None:
    return _update(user_id, note_id, "pinned = ?", (1 if pinned else 0,))


def set_folder(user_id: int, note_id: int, folder: str | None) -> dict | None:
    folder = (folder or "").strip() or None
    return _update(user_id, note_id, "folder = ?", (folder,))


def update_analysis(user_id: int, note_id: int, analysis: dict) -> dict | None:
    return _update(user_id, note_id, "analysis = ?", (json.dumps(analysis),))


_COLS = "id, content, analysis, created_at, folder, pinned"


def list_notes(user_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM notes WHERE user_id = ? ORDER BY pinned DESC, id DESC",
            (user_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_note(user_id: int, note_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {_COLS} FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_note(user_id: int, note_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id)
        )
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
