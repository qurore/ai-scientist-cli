---
name: ai-scientist-ideate
description: Stage 1 of the AI Scientist pipeline — generate and refine novel ML research ideas from a topic, with novelty-checking against the literature, and emit them as an AI-Scientist-v2-compatible idea JSON. Use when starting a study or when the user asks for research ideas / hypotheses on a topic.
---

# Stage 1 — Ideation

Generate **novel, feasible** research ideas for a topic and write them out in the exact
AI-Scientist-v2 idea schema so the experiment stage can consume them.

## Inputs
- A **topic** (a sentence) or a workshop-description markdown file staged under `ideas/`.
  Template: `ideas/TEMPLATE_topic.md` (see `ideas/README.md`). `ideas/` is only a
  *staging* area for drafting topics — the project itself is the home for everything,
  so the topic gets copied into the project (below). The example
  `vendor/AI-Scientist-v2/ai_scientist/ideas/i_cant_believe_its_not_better.md` shows the
  expected style/length.
- Optional: `--num <N>` ideas to generate (default 3), `--reflections <R>` refinement
  rounds (default 3).

## Authoritative reference
Mirror upstream prompts and the FinalizeIdea schema:
`vendor/AI-Scientist-v2/ai_scientist/perform_ideation_temp_free.py`
(read `idea_generation_prompt` and the `FinalizeIdea` tool description before writing).

## Idea JSON schema (one object per idea, output a JSON list)
```json
{
  "Name": "lowercase_with_underscores",
  "Title": "Catchy, informative title",
  "Short Hypothesis": "The core hypothesis and why this is the right way to test it.",
  "Related Work": "Most relevant prior work and how this clearly differs (not a trivial extension).",
  "Abstract": "~250-word conference-style abstract.",
  "Experiments": ["Specific, feasible experiment 1 with metrics", "Experiment 2", "..."],
  "Risk Factors and Limitations": ["risk 1", "risk 2"]
}
```

## Aim for a breakthrough (swing for the fences)
Prefer a **bold, novel leap** over a safe increment. The best outcome is a *surprising,
field-relevant insight* — a falsifiable claim that, if it holds, changes how people think, or
that cleanly overturns a common intuition. Ambition here is about the **idea**, not raw scale:
a sharp angle can land a home run even on a laptop (e.g. "the Hessian *trace* is the wrong
curvature scalar for the learning rate — the top eigenvalue is right", or "sharpness governs
learning-rate stability yet is *irrelevant* to grokking timing"). Generate at least one
genuinely high-risk / high-reward candidate every time, and push each idea for the most
non-obvious, load-bearing claim it can make. Honesty is the guardrail, not timidity: a boldly
tested idea that partly fails, reported truthfully, beats a timid sure thing — but never trade
rigor or truthfulness for ambition.

## Procedure
1. **Understand the topic.** If it's a file, read it. If it's a sentence and ambiguous,
   ask 1–2 clarifying questions (domain, datasets allowed, compute budget).
2. **Brainstorm** `N` candidate directions (include ≥1 breakthrough swing). For each, draft a
   Short Hypothesis.
3. **Novelty check** each candidate against the literature so you don't reinvent known
   results. **Parallelize the legwork with sub-agents:** spawn one `Explore` (or
   general-purpose) sub-agent *per candidate*, each running the arxiv / semantic-scholar
   searches for its idea and returning the closest prior work + a novelty verdict; then you
   merge the findings and judge. (Sub-agents start cold, so use them for genuinely independent,
   parallel searches — not for one quick lookup.) To do the checks yourself instead:
   - Preferred: the `mcp__semantic-scholar__*` and `mcp__arxiv__*` MCP tools (paper
     search, citation graph, recommendations), configured in `.mcp.json`. Check `/mcp`
     if they don't show up as available tools — `scripts/doctor.sh` reports their
     status under `[mcp]`. Set `SEMANTIC_SCHOLAR_API_KEY` in the shell env if the user
     has one (higher rate limits); both servers work fine without a key.
   - Fallback if the MCP servers aren't connected: your **WebSearch** tool, or call the
     Semantic Scholar API directly with `curl`
     (`https://api.semanticscholar.org/graph/v1/paper/search?query=...`).
   - Drop or sharpen ideas that already exist; note the closest prior work in
     "Related Work".
4. **Reflect** `R` times: for each surviving idea, critique feasibility on *this* machine
   (no GPU — see the umbrella skill's compute reality check), tighten the experiments to
   be small and concrete, and ensure metrics are specified.
5. **Feasibility gate:** every idea's `Experiments` must be runnable on CPU/MPS with
   tiny/synthetic data in minutes-to-an-hour. Rewrite anything that needs a cluster.
6. **Write outputs** into the project dir (create one if none is active):
   - `projects/<id>/topic.md` — copy the topic description in (from the `ideas/` draft
     or the sentence you were given) so the project is self-contained and portable.
   - `projects/<id>/idea.json` — the JSON list (validate it parses).
   - `projects/<id>/idea.md` — human-readable version (use
     `aisci.run` helper or mirror upstream `idea_to_markdown`).
   - Update `projects/<id>/state.json`: `stage="ideate"`, `status="done"`, `idea_slug=<Name of chosen idea>`.
   - Append a short note to `projects/<id>/study.md`.

## Output to the user
Present the ideas as a short ranked list (Title + one-line hypothesis + novelty note +
feasibility). Recommend one to take forward, and offer to proceed to
`/ai-scientist-experiment`.

## Bridge fallback
To reproduce upstream ideation exactly (Semantic Scholar loop + reflections, unmodified):
```bash
python -m bridge.run vendor/AI-Scientist-v2/ai_scientist/perform_ideation_temp_free.py \
  --workshop-file ideas/<topic>.md --model gpt-4o-2024-11-20 \
  --max-num-generations 3 --num-reflections 3
```
This writes `ideas/<topic>.json`. Copy it to `projects/<id>/idea.json`. Use this if the user
wants strict upstream parity; otherwise the native procedure above is preferred.
