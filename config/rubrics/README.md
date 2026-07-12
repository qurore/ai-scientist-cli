# Review-rubric registry

One file per **genre** of paper: `<name>.md` is a complete LLM-as-judge rubric that the
review stage (`/ai-scientist-review`) and the improvement loop (`/ai-scientist-improve`)
score against. The rubric is a **per-project setting** stored as the `rubric` key in
`projects/<id>/state.json`:

```bash
.venv/bin/python -m aisci.run rubrics                          # list available rubrics
.venv/bin/python -m aisci.run new --slug s --topic t --rubric aamas-agentic
.venv/bin/python -m aisci.run set  --rubric neurips-ml         # change for current project
```

A missing `rubric` key means the default, **`neurips-ml`**.

## Available rubrics

| Name | Genre |
|------|-------|
| `neurips-ml` (default) | Machine-learning research papers — NeurIPS review form, mirrored from upstream AI-Scientist-v2 |
| `aamas-agentic` | Agentic-AI / autonomous-agents / multiagent-systems papers — AAMAS-style review (AAMAS 2026 CFP criteria) |

## The contract every rubric must honor

So that the improve loop, `reviews/score_history.jsonl`, and the publish gate
(`Decision == "Accept"`) work unchanged for every genre:

1. **Core schema is invariant.** Every rubric emits at least these fields, with these
   scales: `Summary`, `Strengths`, `Weaknesses`, `Originality`/`Quality`/`Clarity`/
   `Significance` (1–4), `Questions`, `Limitations`, `Ethical Concerns` (bool),
   `Soundness`/`Presentation`/`Contribution` (1–4), `Overall` (1–10), `Confidence` (1–5),
   `Decision` (`Accept`/`Reject` only), `Figure_Review`, `Integrity_Flags`.
2. **Genre-specific items are additive.** A rubric may add scored items, but only inside
   one extra top-level block named after the genre (e.g. `"AAMAS": {...}`) plus optional
   extra advisory fields. Never remove, rename, or re-scale a core field.
3. **Same severity.** The `Overall` 1–10 ladder keeps the same meaning across genres
   (10 award quality … 6 weak accept … 1 very strong reject), and every rubric applies
   the review skill's shared calibration rules: critical-and-cautious persona, never
   inflate, ICBINB ~6.3/10 is a floor to clear, and **never** penalize length or venue
   formatting (this pipeline imposes none).
4. **Comparable within a project.** A project keeps one rubric across improvement
   iterations so its score history stays meaningful; switching rubric mid-study resets
   comparability (note it in `decisions.jsonl` if you ever do).

## Adding a new genre

Copy the structure of an existing rubric file: reviewer persona → core-item definitions
(re-worded for the genre, scales unchanged) → genre-specific block (additive items with
1–4 anchors) → the same 1–10 `Overall` ladder re-worded for the genre → Decision rule →
output JSON template. Ground genre-specific criteria in the target venue's actual review
criteria / call for papers (primary source), then register the file here and in the table
above.
