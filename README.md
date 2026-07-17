# Unknot

An AI note-taker that **thinks about your idea instead of agreeing with it.**
Save a thought like a normal note, or hit **Analyze** and a friendly-but-honest
"friend" reads it back — surfacing the assumptions you didn't state, pointing
out real flaws, and proposing a concrete fix — presented as:

**[Original Note] → [Understanding] → [Hidden Assumptions] → [Problems] → [What's Solid] → [Suggested Correction]**

The whole point is anti-sycophancy: it praises only what's actually strong and
pushes back where pushing back is warranted.

## Stack
- **Backend:** Python + FastAPI
- **Model:** free / open-source, via one of two providers (pick either):
  - **Ollama** — an open model running **locally** on your machine. No API key,
    no cost. *(default)*
  - **Groq** — open models (Llama, etc.) on a free hosted API. Needs a free key,
    but no local compute and much faster.
- **DB:** SQLite (notes + analysis history)
- **Frontend:** one self-contained `index.html` (no build step), served by the backend

## Project layout
```
smart-notes/
├── backend/
│   ├── main.py           # FastAPI app + routes
│   ├── llm.py            # open-source model layer (Ollama / Groq)
│   ├── prompts.py        # the critical-thinking system prompt (the core)
│   ├── schema.py         # the shared 4-section analysis schema
│   ├── db.py             # SQLite storage
│   └── requirements.txt
├── frontend/
│   ├── landing.html      # the front door: what Unknot is, and why  (served at /)
│   └── index.html        # the app: notes list, editor, unknot view (served at /app)
└── README.md
```

## Setup (common to both providers)
```powershell
cd smart-notes\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt
```
(macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`)

---

## Option A — Ollama (fully local, no key)  ← default

1. **Install Ollama:** download from https://ollama.com and install it.
2. **Pull a model** (one time, a few GB):
   ```bash
   ollama pull llama3.1:8b
   ```
   Ollama runs a local server automatically at `http://localhost:11434`.
3. **Start the backend** (from `backend/`):
   ```bash
   uvicorn main:app --reload
   ```
4. Open **http://127.0.0.1:8000**, type a note, hit **Analyze**.

Want a different local model? Pull it and point the app at it:
```powershell
ollama pull qwen2.5:7b
$env:OLLAMA_MODEL = "qwen2.5:7b"
```

> Tip: an 8B model needs ~8 GB RAM and responses take a few seconds. If your
> machine is slow, use Option B instead — it needs no local compute.

---

## Option B — Groq (free hosted key, fast)  ← currently configured

Configuration lives in `backend/.env` (auto-loaded on startup, and gitignored
so your key is never committed):

```ini
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

1. Get a free API key at https://console.groq.com (already set up here).
2. **Start the backend** (from `backend/`):
   ```bash
   uvicorn main:app --reload
   ```
3. Open **http://127.0.0.1:8000** — no env vars to set, `.env` handles it.

To switch back to local Ollama, just change `LLM_PROVIDER=ollama` in `.env`.

---

## How it works
1. The frontend POSTs your note to `/api/analyze`.
2. `llm.py` sends it to the configured provider with the critical-thinking
   system prompt from `prompts.py`, requiring the six-section JSON shape from
   `schema.py`. Ollama enforces the schema natively; Groq is put in JSON mode.
3. The response is validated with Pydantic, then note + analysis are saved to
   SQLite and returned.
4. Past notes appear under **History**; click one to re-open it, `×` to delete.

## Configuration (env vars)
| Variable        | Default                      | Meaning |
|-----------------|------------------------------|---------|
| `LLM_PROVIDER`  | `ollama`                     | `ollama` or `groq` |
| `OLLAMA_MODEL`  | `llama3.1:8b`                | local model name |
| `OLLAMA_HOST`   | `http://localhost:11434`     | Ollama server URL |
| `GROQ_API_KEY`  | *(none)*                     | required for Groq |
| `GROQ_MODEL`    | `llama-3.3-70b-versatile`    | Groq model name |

## API
| Method | Route | Purpose |
|--------|-------|---------|
| GET    | `/`                      | Landing page — the pitch, the why, an example read-back |
| GET    | `/app`                   | The notes app itself |
| POST   | `/api/notes`              | **Save** a plain note `{ "content": "..." }`, no analysis |
| PUT    | `/api/notes/{id}`        | Update a note's text (the editor autosaves as you type) |
| POST   | `/api/analyze`           | Save **and** analyze a new note in one step |
| POST   | `/api/notes/{id}/analyze`| Analyze a note you saved earlier (analyze-later) |
| GET    | `/api/notes`             | List all notes (newest first) |
| GET    | `/api/notes/{id}`        | Fetch one note + its analysis (may be `null`) |
| DELETE | `/api/notes/{id}`        | Delete a note |

## Note on quality
Smaller open models (like an 8B running locally) give solid but less incisive
critiques than a large one. If the pushback feels too soft, either use a bigger
model on Groq (Option B) or lower the temperature in `backend/llm.py`.
