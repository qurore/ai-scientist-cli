---
name: ai-scientist-review
description: Stage 4 of the AI Scientist pipeline — produce a rigorous peer review of the generated paper (text + figures) as a structured JSON verdict, scored against the project's configured genre rubric (NeurIPS-style ML by default; AAMAS-style agents/MAS; see config/rubrics/). Use after a paper PDF exists, or when the user wants the AI Scientist to review a paper.
---

# Stage 4 — Review

Act as a critical, fair conference reviewer of `projects/<id>/writeup/paper.pdf`. You can
**read the PDF and its figures directly** (Read tool) — use that, plus the underlying
`experiment/` results, to judge whether the paper's claims are actually supported.

## Rubric — per-project, from the registry (`config/rubrics/`)
Which scoring rubric applies is a **per-project setting**: the `rubric` key in
`projects/<id>/state.json` (default **`neurips-ml`** if absent). Set it with
`aisci.run new --rubric <name>` or `aisci.run set --rubric <name>`; list the registry
with `.venv/bin/python -m aisci.run rubrics`.

**Load `config/rubrics/<name>.md` and score against exactly that rubric** — it defines
the reviewer persona, the scored items and their genre-specific definitions, the
Overall 1–10 anchors, the Decision rule, and the exact JSON to emit. Knowing the
rubric/genre does **not** breach review blindness (it is study-level configuration, not
revision history). Use the same rubric on every re-review of a project so scores stay
comparable.

## Authoritative reference
- Default text rubric (`neurips-ml`) mirrors: `vendor/AI-Scientist-v2/ai_scientist/perform_llm_review.py`
- Figure/caption/reference review (all rubrics): `vendor/AI-Scientist-v2/ai_scientist/perform_vlm_review.py`

## Review blind — no leakage
Judge the paper **fresh, on its own merits**, from only what is in front of you: the
`paper.pdf` and the `experiment/` results (to verify numbers). You are **not** told — and
must **not** assume or look up — whether this is a first submission or a revision, which
improvement iteration it is, or what any prior review or score said. Do **not** open
`reviews/`, `score_history.jsonl`, or `decisions.jsonl`. This keeps the score an unbiased
function of the paper itself (no anchoring or leniency from "it has improved").

## Procedure
1. **Read the paper.** Open `paper.pdf` with Read (you see text + figures). Also load
   `experiment/experiment_results/summary.json` so you can verify the paper's numbers
   against what was actually measured.
2. **Text review** against the project's rubric (see "Rubric" above) → produce its
   output JSON: the core schema below plus any genre block the rubric defines.
3. **Figure/caption/reference check** (mirrors the VLM review): for each figure, confirm
   it renders, the caption matches the content, and it's referenced in the text. Flag
   any figure whose claim isn't supported by `experiment_results/`.
4. **Integrity checks specific to autonomous papers:** flag (a) any number not traceable
   to `experiment/`, (b) any citation you can't verify is a real paper, (c) overclaiming
   beyond the small-scale evidence. For (b), the deterministic checker's report at
   `writeup/bibcheck.json` (from `aisci.bibcheck`) is a starting signal — confirm it is
   present, fresh (its `bib_sha256` matches the current `references.bib`), and reports
   `blocking: 0`; then still spot-check a few citations yourself, since the checker only
   proves a paper *exists*, not that it says what the text claims it says.

## Core review JSON (every rubric; write to `projects/<id>/review.json`)
Every rubric emits at least this **core schema**, unchanged in names and scales — it is
what the improve loop, `score_history.jsonl`, and the publish gate depend on:
```json
{
  "Summary": "What the paper does.",
  "Strengths": ["..."],
  "Weaknesses": ["..."],
  "Originality": 3,
  "Quality": 3,
  "Clarity": 3,
  "Significance": 2,
  "Questions": ["..."],
  "Limitations": ["..."],
  "Ethical Concerns": false,
  "Soundness": 3,
  "Presentation": 3,
  "Contribution": 2,
  "Overall": 5,
  "Confidence": 4,
  "Decision": "Reject",
  "Figure_Review": [{"figure":"fig1.png","renders":true,"caption_matches":true,"supported":true,"note":"..."}],
  "Integrity_Flags": ["any unsupported number / unverifiable citation / overclaim"]
}
```
Scales (fixed across rubrics): Originality/Quality/Clarity/Significance 1–4; Soundness/
Presentation/Contribution 1–4; Overall 1–10; Confidence 1–5; Decision ∈ {Accept, Reject}.
A rubric may **add** genre-specific scored items in one extra block named after the genre
(e.g. `"AAMAS": {...}` plus `"AAMAS_Recommendation"`) — include them exactly as its
output template specifies; never remove or re-scale a core field.

## Be honest and calibrated
Score against a **high bar** — the standard of a strong paper at a top venue — but score
**honestly**. The point of the review is a *truthful* signal that drives real improvement,
so **never inflate**: a higher score must be earned by a genuinely better paper, not by a
more generous reviewer. Both directions matter — a strong, rigorous, clearly-written study
*can* merit Accept and a high Overall; a thin one should be marked as such with concrete,
actionable weaknesses.

Calibration reference: a strong paper *accepted* to the ICLR 2025 "I Can't Believe It's Not
Better" (ICBINB) workshop averaged ~6.3/10 across three reviewers. Treat that as a floor to
clear, not a ceiling — aim the *work* (not the scoring) at Overall ≥ 8. This skill feeds the
improvement loop (`/ai-scientist-improve`): make the **Weaknesses** and **Questions**
specific and actionable so the next revision can actually close them.

**Do NOT penalize length or format.** This pipeline imposes no page/character limit (see the
writeup skill), so judge only the *content*: correctness, rigor, novelty, significance,
clarity, and how well claims are supported. Never lower `Presentation`, `Clarity`, or
`Overall` because the paper is long/short or doesn't fit a venue's page count, and never add
a "too long / exceeds page limit" weakness. A longer paper that is thorough and clear should
score *well*, not be marked down for length.

## Outputs
- `projects/<id>/review.json` (validate it parses; all schema fields present).
- Update `state.json`: `stage="review"`, `status="done"` → then set top-level study
  `status="complete"`. Append the verdict to `study.md`.

## Output to the user
Give the headline: Decision, Overall score, the 2–3 biggest strengths and weaknesses,
and any integrity flags. Then summarize the **whole study**: idea → key result → paper →
verdict, with total wall-clock and token cost (from the token log).
