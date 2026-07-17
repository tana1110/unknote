"""Unknot backend — multi-user.

FastAPI app that:
  - lets people sign up / log in (token auth),
  - stores each account's notes separately,
  - sends a note to a free model (Groq or Ollama) for the critical read-back,
  - serves the single-page frontend.

Run:  uvicorn main:app --reload   (from the backend/ directory)
"""

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import llm
from prompts import SYSTEM_PROMPT, THREADS_PROMPT, TOPICS_PROMPT

# A pattern needs repetition to be real; below this it would be guessing.
MIN_NOTES_FOR_THREADS = 3
MAX_NOTES_FOR_THREADS = 24
MIN_NOTES_FOR_TOPICS = 4
MAX_NOTES_FOR_TOPICS = 60

app = FastAPI(title="Unknot")


# ---- auth ----------------------------------------------------------------

class Credentials(BaseModel):
    """Signup: enforce a minimum password so accounts aren't trivially weak."""
    username: str = Field(..., min_length=1, max_length=40)
    password: str = Field(..., min_length=6, max_length=200)


class LoginIn(BaseModel):
    """Login: accept any length so a wrong password returns 401, not a 422."""
    username: str = Field(..., min_length=1, max_length=40)
    password: str = Field(..., min_length=1, max_length=200)


def require_user(authorization: str | None = Header(default=None)) -> dict:
    """Resolve the Bearer token to the logged-in user, or 401.

    Every note route depends on this, so an unauthenticated request can never
    reach anyone's data."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = db.user_for_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user


@app.post("/api/signup")
def signup(creds: Credentials) -> dict:
    user = db.create_user(creds.username, creds.password)
    if user is None:
        raise HTTPException(status_code=409, detail="That username is taken.")
    return {"token": db.create_session(user["id"]), "username": user["username"]}


@app.post("/api/login")
def login(creds: LoginIn) -> dict:
    user = db.verify_user(creds.username, creds.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    return {"token": db.create_session(user["id"]), "username": user["username"]}


@app.post("/api/logout")
def logout(authorization: str | None = Header(default=None)) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        db.delete_session(authorization[7:].strip())
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(require_user)) -> dict:
    return {"username": user["username"]}


# ---- note models ---------------------------------------------------------

class NoteIn(BaseModel):
    content: str = Field(..., min_length=1, description="The raw note")
    analysis: dict | None = Field(None, description="Only used by undo/restore.")
    folder: str | None = Field(None, description="Only used by restore.")
    pinned: bool = Field(False, description="Only used by restore.")


class FolderIn(BaseModel):
    folder: str | None = Field(None, description="Folder label, or null to unfile.")


class PinIn(BaseModel):
    pinned: bool = Field(..., description="True to pin to the top, false to unpin.")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---- notes (all scoped to the logged-in user) ----------------------------

@app.post("/api/notes")
def create_note(note: NoteIn, user: dict = Depends(require_user)) -> dict:
    return db.save_note(user["id"], note.content, note.analysis, note.folder, note.pinned)


@app.put("/api/notes/{note_id}/pin")
def pin_note(note_id: int, body: PinIn, user: dict = Depends(require_user)) -> dict:
    updated = db.set_pinned(user["id"], note_id, body.pinned)
    if updated is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return updated


@app.put("/api/notes/{note_id}/folder")
def file_note(note_id: int, body: FolderIn, user: dict = Depends(require_user)) -> dict:
    updated = db.set_folder(user["id"], note_id, body.folder)
    if updated is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return updated


@app.put("/api/notes/{note_id}")
def edit_note(note_id: int, note: NoteIn, user: dict = Depends(require_user)) -> dict:
    updated = db.update_content(user["id"], note_id, note.content)
    if updated is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return updated


@app.post("/api/analyze")
def analyze(note: NoteIn, user: dict = Depends(require_user)) -> dict:
    try:
        analysis = llm.analyze(SYSTEM_PROMPT, note.content)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return db.save_note(user["id"], note.content, analysis.model_dump())


@app.post("/api/notes/{note_id}/analyze")
def analyze_existing(note_id: int, user: dict = Depends(require_user)) -> dict:
    note = db.get_note(user["id"], note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    try:
        analysis = llm.analyze(SYSTEM_PROMPT, note["content"])
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return db.update_analysis(user["id"], note_id, analysis.model_dump())


@app.get("/api/threads")
def get_threads(user: dict = Depends(require_user)) -> dict:
    """What keeps coming up across everything this user has unknotted."""
    unknotted = [n for n in db.list_notes(user["id"]) if n["analysis"]]
    if len(unknotted) < MIN_NOTES_FOR_THREADS:
        raise HTTPException(
            status_code=409,
            detail=(f"Unknot a few more notes first — patterns need something to "
                    f"repeat across. {len(unknotted)} of {MIN_NOTES_FOR_THREADS} so far."),
        )
    digest = "\n\n".join(_digest(n) for n in unknotted[:MAX_NOTES_FOR_THREADS])
    try:
        threads = llm.find_threads(THREADS_PROMPT, digest)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"threads": threads.model_dump()["threads"],
            "closing": threads.closing,
            "note_count": len(unknotted[:MAX_NOTES_FOR_THREADS])}


def _digest(note: dict) -> str:
    a = note["analysis"]
    lines = [f'NOTE ({note["created_at"][:10]}): {note["content"][:400]}']
    if a.get("hidden_assumptions"):
        lines.append("  assumed: " + "; ".join(a["hidden_assumptions"]))
    if a.get("weaknesses"):
        lines.append("  weak: " + "; ".join(a["weaknesses"]))
    if a.get("strengths"):
        lines.append("  strong: " + "; ".join(a["strengths"]))
    return "\n".join(lines)


@app.get("/api/topics")
def get_topics(user: dict = Depends(require_user)) -> dict:
    """Sort this user's notes into topic groups by what they're about."""
    notes = db.list_notes(user["id"])
    if len(notes) < MIN_NOTES_FOR_TOPICS:
        raise HTTPException(
            status_code=409,
            detail=(f"Write a few more notes first — there's not much to organise "
                    f"yet ({len(notes)} of {MIN_NOTES_FOR_TOPICS})."),
        )
    subset = notes[:MAX_NOTES_FOR_TOPICS]
    by_id = {n["id"]: n for n in subset}
    digest = "\n".join(f'#{n["id"]}: {n["content"][:200]}' for n in subset)
    try:
        topics = llm.group_topics(TOPICS_PROMPT, digest)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    groups, placed = [], set()
    for g in topics.groups:
        ids = [i for i in g.note_ids if i in by_id and i not in placed]
        if not ids:
            continue
        placed.update(ids)
        groups.append({"topic": g.topic, "note_ids": ids})
    leftover = [n["id"] for n in subset if n["id"] not in placed]
    if leftover:
        groups.append({"topic": "Loose notes", "note_ids": leftover})
    return {"groups": groups, "note_count": len(subset)}


@app.get("/api/notes")
def get_notes(user: dict = Depends(require_user)) -> list[dict]:
    return db.list_notes(user["id"])


@app.get("/api/notes/{note_id}")
def get_note(note_id: int, user: dict = Depends(require_user)) -> dict:
    note = db.get_note(user["id"], note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@app.delete("/api/notes/{note_id}")
def remove_note(note_id: int, user: dict = Depends(require_user)) -> dict:
    if not db.delete_note(user["id"], note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": note_id}


# ---- Frontend ------------------------------------------------------------
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/")
def landing() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "landing.html")


@app.get("/app")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
