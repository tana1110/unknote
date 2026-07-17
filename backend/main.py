"""Smart Notes backend (open-source model edition).

FastAPI app that:
  - takes a note,
  - sends it to a free/open-source model (Ollama locally, or Groq) with the
    critical-thinking system prompt and a required JSON shape,
  - stores note + analysis in SQLite,
  - serves the single-page frontend.

Run:  uvicorn main:app --reload   (from the backend/ directory)
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import llm
from prompts import SYSTEM_PROMPT, THREADS_PROMPT, TOPICS_PROMPT

# A pattern needs repetition to be real; below this it would be guessing.
MIN_NOTES_FOR_THREADS = 3
# Bound the prompt: the most recent notes, not the whole archive forever.
MAX_NOTES_FOR_THREADS = 24

# Grouping only earns its keep once there's a pile worth sorting.
MIN_NOTES_FOR_TOPICS = 4
MAX_NOTES_FOR_TOPICS = 60

app = FastAPI(title="Unknot")


class NoteIn(BaseModel):
    content: str = Field(..., min_length=1, description="The raw note")
    analysis: dict | None = Field(
        None,
        description="Only used to restore a deleted note whole (undo), so its "
                    "unknot comes back with it instead of being re-run.",
    )
    folder: str | None = Field(None, description="Only used by restore, to bring "
                                                 "a note back in its folder.")
    pinned: bool = Field(False, description="Only used by restore, to bring a "
                                            "note back pinned if it was.")


class FolderIn(BaseModel):
    folder: str | None = Field(None, description="Folder label, or null to unfile.")


class PinIn(BaseModel):
    pinned: bool = Field(..., description="True to pin to the top, false to unpin.")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.post("/api/notes")
def create_note(note: NoteIn) -> dict:
    """Save a note. `analysis`/`folder`/`pinned` are normally absent; undo passes
    them to restore a deleted note exactly as it was."""
    return db.save_note(note.content, note.analysis, note.folder, note.pinned)


@app.put("/api/notes/{note_id}/pin")
def pin_note(note_id: int, body: PinIn) -> dict:
    """Pin a note to the top of the list (or unpin it)."""
    updated = db.set_pinned(note_id, body.pinned)
    if updated is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return updated


@app.put("/api/notes/{note_id}/folder")
def file_note(note_id: int, body: FolderIn) -> dict:
    """File a note into a folder the user named (or clear it)."""
    updated = db.set_folder(note_id, body.folder)
    if updated is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return updated


@app.put("/api/notes/{note_id}")
def edit_note(note_id: int, note: NoteIn) -> dict:
    """Update a saved note's text (the frontend autosaves as you type)."""
    updated = db.update_content(note_id, note.content)
    if updated is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return updated


@app.post("/api/analyze")
def analyze(note: NoteIn) -> dict:
    """Analyze a new note and persist it with the analysis."""
    try:
        analysis = llm.analyze(SYSTEM_PROMPT, note.content)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return db.save_note(note.content, analysis.model_dump())


@app.post("/api/notes/{note_id}/analyze")
def analyze_existing(note_id: int) -> dict:
    """Analyze a note that was already saved (analyze-later)."""
    note = db.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    try:
        analysis = llm.analyze(SYSTEM_PROMPT, note["content"])
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return db.update_analysis(note_id, analysis.model_dump())


@app.get("/api/threads")
def get_threads() -> dict:
    """What keeps coming up across everything they've unknotted.

    This reads the *unknots*, not the raw notes — the assumptions and weak
    joints already found. No other notes app has that data to look back over.
    """
    unknotted = [n for n in db.list_notes() if n["analysis"]]
    if len(unknotted) < MIN_NOTES_FOR_THREADS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Unknot a few more notes first — patterns need something to "
                f"repeat across. {len(unknotted)} of {MIN_NOTES_FOR_THREADS} so far."
            ),
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
    """One note boiled down to what matters for spotting a pattern."""
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
def get_topics() -> dict:
    """Sort the notes into topic groups by what they're about.

    The model does the grouping, but the server owns correctness: any note the
    model drops or mis-ids is caught and swept into a "Loose notes" group, so
    no note can ever disappear from the view.
    """
    notes = db.list_notes()
    if len(notes) < MIN_NOTES_FOR_TOPICS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Write a few more notes first — there's not much to organise "
                f"yet ({len(notes)} of {MIN_NOTES_FOR_TOPICS})."
            ),
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
def get_notes() -> list[dict]:
    return db.list_notes()


@app.get("/api/notes/{note_id}")
def get_note(note_id: int) -> dict:
    note = db.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@app.delete("/api/notes/{note_id}")
def remove_note(note_id: int) -> dict:
    if not db.delete_note(note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": note_id}


# ---- Frontend ------------------------------------------------------------
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/")
def landing() -> FileResponse:
    """The front door: what Unknot is, and why."""
    return FileResponse(FRONTEND_DIR / "landing.html")


@app.get("/app")
def index() -> FileResponse:
    """The app itself."""
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
