"""Shared analysis schema — used by both the API layer and the LLM layer.

Kept in its own module so `main.py` and `llm.py` can both import it without a
circular dependency.
"""

from typing import List

from pydantic import BaseModel, Field


class Analysis(BaseModel):
    """The structured critique the model must return.

    Field order mirrors the reasoning flow the system prompt asks for:
    understand -> surface assumptions -> find weaknesses -> judge -> fix.
    """

    understanding: str = Field(
        ..., description="A faithful restatement of what the person is actually "
                         "claiming, proposing, or trying to achieve."
    )
    hidden_assumptions: List[str] = Field(
        ..., description="Unstated things that must be true for the idea to work."
    )
    weaknesses: List[str] = Field(
        ..., description="Genuine flaws, contradictions, faulty logic, ignored "
                         "trade-offs, or a solution aimed at the wrong problem."
    )
    strengths: List[str] = Field(
        ..., description="What is genuinely solid — only real strengths, no filler."
    )
    suggested_correction: str = Field(
        ..., description="A concrete, actionable fix or stronger alternative "
                         "grounded in this exact note."
    )
    verdict: str = Field(
        ..., description="One or two blunt sentences: is the core idea sound, "
                         "flawed-but-salvageable, or misguided — and why."
    )


class Thread(BaseModel):
    """One habit of thought that shows up across many notes.

    This is the thing no ordinary notes app can do: it needs to have actually
    read everything you wrote, and understood it.
    """

    pattern: str = Field(
        ..., description="The recurring habit, said to them as 'you' — e.g. "
                         "'You keep treating other people's enthusiasm as proof.'"
    )
    seen_in: List[str] = Field(
        ..., description="Short, concrete pointers to the notes where it showed "
                         "up, so the claim is evidenced rather than asserted."
    )
    nudge: str = Field(
        ..., description="One concrete thing to try differently next time."
    )


class Threads(BaseModel):
    """What keeps coming up across everything they've written."""

    threads: List[Thread] = Field(
        ..., description="The recurring patterns. Only real ones — no filler."
    )
    closing: str = Field(
        ..., description="One or two warm, honest sentences tying it together."
    )


class TopicGroup(BaseModel):
    """One cluster of notes that belong together by subject."""

    topic: str = Field(..., description="A short, human label for the theme "
                                        "(2-4 words), in the notes' language.")
    note_ids: List[int] = Field(..., description="The ids of the notes in this group.")


class Topics(BaseModel):
    """Every note sorted into topic groups. No note left out."""

    groups: List[TopicGroup]


def analysis_schema() -> dict:
    """JSON Schema for the model to fill in (additionalProperties disabled)."""
    schema = Analysis.model_json_schema()
    schema["additionalProperties"] = False
    return schema


def topics_schema() -> dict:
    schema = Topics.model_json_schema()
    schema["additionalProperties"] = False
    return schema


TOPICS_JSON_INSTRUCTIONS = """\
Respond with ONLY a single JSON object — no prose before or after, no markdown
code fences. It must have exactly this shape:

- "groups": array of objects, each with:
    - "topic": string — a short label (2-4 words) for what these notes share
    - "note_ids": array of integers — the ids of the notes in this group

Rules:
- Group by what the notes are ABOUT — the underlying subject, not surface words.
  A note about a job offer and a note about quitting belong together (work).
- Every note id you were given must appear in exactly ONE group. Don't drop any,
  don't invent ids that weren't given.
- Prefer a few meaningful groups over many tiny ones. A group can have one note
  if it truly stands alone.
- Write the topic labels in the same language the notes are mostly written in.
- Put genuinely random or contentless notes together in one group labelled
  "Loose notes" (or its natural equivalent in the notes' language).
"""


def threads_schema() -> dict:
    schema = Threads.model_json_schema()
    schema["additionalProperties"] = False
    return schema


THREADS_JSON_INSTRUCTIONS = """\
Respond with ONLY a single JSON object — no prose before or after, no markdown
code fences. It must have exactly these keys:

- "threads": array of objects (at most 4), each with:
    - "pattern": string (1-2 sentences) — the recurring habit, said as "you"
    - "seen_in": array of strings (2-4), each a short concrete pointer to a note
      where it showed up (paraphrase it — don't quote whole notes)
    - "nudge": string (1-2 sentences) — one concrete thing to try instead
- "closing": string (1-2 sentences)

VOICE: Speak directly TO the person as "you" — warm, personal, like a friend
who has been listening for a while and has noticed something. Never say "the
user" or "the writer."

LANGUAGE: Write in the same language their notes are in. Arabic notes get an
entirely Arabic answer (natural and warm, not stiff formal translation). The
JSON keys stay in English; only the values follow their language.

Only report patterns that genuinely repeat across MULTIPLE notes. If you can
only find one real pattern, return one. Do not invent patterns to fill space —
a made-up pattern is worse than a short list.
"""


# A plain-English description of the required JSON, appended to the prompt so
# even models without hard schema enforcement produce the right shape.
# Kept tight on length — smaller local models generate slowly, so brevity here
# directly cuts response time without losing the substance of the critique.
JSON_INSTRUCTIONS = """\
Respond with ONLY a single JSON object — no prose before or after, no markdown
code fences. It must have exactly these keys:

- "understanding": string (1-2 sentences) — "Here's what I'm hearing…"
- "hidden_assumptions": array of strings (at most 3, one sentence each)
- "weaknesses": array of strings (at most 3, one sentence each)
- "strengths": array of strings (at most 2, one sentence each)
- "suggested_correction": string (2-3 sentences)
- "verdict": string (1-2 sentences)

VOICE: Write every field speaking directly TO the person as "you" — warm,
personal, like a friend who gets them. Never say "the writer," "the user," or
"the author." Say "you." Be sharp and concise, no padding, and make every point
specific to this exact note.

LANGUAGE: Write every field in the SAME language the note is written in. An
Arabic note gets an entirely Arabic response (natural, warm, spoken Arabic —
not stiff formal translation). An English note gets English. The JSON keys stay
in English; only the values follow the note's language.
"""
