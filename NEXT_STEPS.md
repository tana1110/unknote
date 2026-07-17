# Handoff — where this project stands

_Last worked: 2026-07-15. Written 2026-07-16._

## What this is
An AI note-taker that **thinks about your idea instead of agreeing with it**. The user
writes a note; "Analyze" sends it to an open-source model that returns:

[Original Note] → [Understanding] → [Hidden Assumptions] → [Problems] → [What's Solid] → [Suggested Correction]

The core value is **anti-sycophancy** — it praises only what's genuinely strong and pushes
back where pushback is warranted. That principle lives in `backend/prompts.py`. If you
change one thing carefully, make it that file.

## Stack
- **Backend:** Python + FastAPI (`backend/main.py`)
- **Model:** free/open-source — Ollama (local, default, no key) or Groq (hosted, free key)
- **DB:** SQLite — `backend/smart_notes.db`
- **Frontend:** single self-contained `frontend/index.html`, no build step

See `README.md` for full setup. The venv is already created at `backend/.venv` with
dependencies installed.

## State: working
The app was built and run successfully — `smart_notes.db` contains saved notes.
The last line of `backend/server.log` is a port-8000 bind conflict, which just means a
server was **already running** on that port. It is not a bug to fix. If you hit it, either
reuse the running server or start on another port: `uvicorn main:app --reload --port 8001`.

**Not independently verified in this handoff session:** the end-to-end Analyze flow
(note in → model → six-section result out). Worth driving once before building on top.

## Where work stopped: the name
Not a code problem. The project is currently named **Unknot** throughout (README, UI),
but that domain is taken.

- The user wants a name that **means something, feels something, and relates to the user** —
  not a functional description of what the app does.
- **Untwine** was the leading candidate (domain available) but the user felt it was boring,
  and agreed with the read that "un-" prefixes make it sound like a feature, not a name.
- Direction that resonated: inward, personal names about the user's own mind and the
  feeling of being understood (e.g. the *Inkling* flavor) — not knot/thread metaphors.

**Do not rename any files or code until the user picks a name.** When they do, it needs
updating in `README.md` and `frontend/index.html`.

## Suggested next steps
1. **Settle the name** — this is the actual open question and the user's current focus.
2. Drive the Analyze flow end-to-end once to confirm it still works.
3. Only then: rename across README + frontend, and move on to features.

## Note for whoever picks this up
The user is new to Claude Code and to this kind of tooling. Earlier in the project they
cancelled some tool calls without meaning to and said so. Explain what you're about to do
before doing it, avoid jargon, and don't assume a slash command or terminal convention is
obvious. They also value honest pushback over agreement — which is, fittingly, the whole
premise of the app.
