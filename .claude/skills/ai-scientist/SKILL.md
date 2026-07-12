---
name: ai-scientist
description: Orchestrate an end-to-end automated research study — research idea → experiments → written paper → peer review — natively inside Claude Code, in the style of Sakana AI's AI-Scientist-v2. Use when the user wants to "run the AI Scientist", do an autonomous ML research project, or go from a topic to a written, reviewed paper. Delegates to the ai-scientist-ideate / -experiment / -writeup / -review stage skills.
---

# AI Scientist (Claude Code-native orchestrator)

You are driving an autonomous research pipeline modeled on **AI-Scientist-v2**, but
re-implemented to run **entirely inside Claude Code** using Skills (the stages) and
Hooks (automation + safety). **You — the Claude Code agent — are the scientist.** You
generate hypotheses, write and run experiment code, analyze results, write the paper,
and review it, using your native tools (Edit/Write, Bash, Read for PDFs & images,
WebSearch). No external LLM API keys are involved.

## The stages

| Stage | Skill | Output |
|------:|-------|--------|
| 1. Ideation  | `ai-scientist-ideate`     | `projects/<id>/idea.json` (+ `idea.md`, `topic.md`) |
| 2. Experiments | `ai-scientist-experiment` | `projects/<id>/experiment/` results, metrics, plots |
| 3. Writeup   | `ai-scientist-writeup`    | `projects/<id>/writeup/paper.pdf` (top-journal quality, no page limit) |
| 4. Review    | `ai-scientist-review`     | `projects/<id>/review.json` |
| 5. Improve (loop) | `ai-scientist-improve` | revise → re-review until honest Overall ≥ 8; `reviews/` history |
| 6. Publish (opt.) | `ai-scientist-publish` | deposit `paper.pdf` to Zenodo + DOI (sandbox/draft by default; publish only on confirmation) |

Invoke a stage with its slash command (e.g. `/ai-scientist-ideate`) or just follow its
SKILL.md. This umbrella skill coordinates them.

**Record decisions as you go (enforced).** At each major decision — idea pivots, experiment
redesigns, framing calls, the review verdict — append it to the project's append-only log:
`aisci.run decide --decision "<what>" --why "<why>"`. The `enforce_decision_log` hook
**blocks** closing a stage (`set --status done`/`--complete`) until its key decision is
logged, so a human can later reconstruct how the result was produced.

## Run layout

Every study is one self-contained project directory: `projects/<slug>/`

```
projects/<id>/
  state.json        # {stage, status, rubric, idea_slug, created, updated} — the source of truth
  idea.md/json      # stage 1
  experiment/
    code/           # experiment scripts you write
    logs/           # run logs
    experiment_results/   # metrics.json, arrays, raw outputs
    plots/          # figures (png/pdf)
    journal.jsonl   # tree-search journal: one line per node {id,parent,stage,plan,metric,buggy}
  writeup/
    latex/  paper.pdf  citations.bib
  review.json
  study.md          # human-readable running log of decisions
```

`state.json` is authoritative. The Stop hook reads it for optional autopilot; always
keep it current as you advance.

## How to start a study

1. Confirm the environment is ready: run `bash scripts/doctor.sh` (the SessionStart hook
   prints a short status banner too). If deps are missing, point the user to
   `scripts/setup.sh`.
2. Get the research **topic** from the user (a sentence or a `.md` topic file under
   `ideas/`). If vague, ask 1–2 clarifying questions (domain, dataset constraints,
   compute budget).
3. Create the run dir and `state.json` with `stage: "ideate", status: "pending"`. Use
   the helper:
   ```bash
   .venv/bin/python -m aisci.run new --slug "<slug>" --topic "<topic>" [--rubric <name>]
   ```
   (prints the new run id; also writes `.aisci_cache/current_run`). Pick the **review
   rubric** by genre at creation — `aisci.run rubrics` lists the registry in
   `config/rubrics/` (default `neurips-ml` for ML papers; `aamas-agentic` for
   agentic-AI / multiagent-systems papers). It can be changed later with
   `aisci.run set --rubric <name>`.
4. Run the stages in order, updating `state.json` after each. Stop and summarize for the
   user between stages unless they asked for **autopilot**.

## Autopilot (optional, opt-in)

If the user wants the whole pipeline to run hands-off, set `AISCI_AUTOPILOT=1` (the Stop
hook will then re-prompt you to advance to the next stage automatically until the study
is `complete`). Default is **off** — you pause between stages for the user to review.
Tell the user the autopilot toggle exists; don't enable it silently.

## Compute & scope reality check

- This machine (macOS) has **no CUDA GPU**. Keep experiments small: tiny/synthetic
  datasets, small models, CPU or Apple MPS, short training. Prefer toy problems that
  still test the hypothesis. Say so to the user up front for ambitious ideas.
- Respect the user's budget. Each stage costs Claude Code tokens; the
  `log-token-usage` hook tracks spend into `projects/<id>/experiment/token_log.jsonl` and
  `.aisci_cache/bridge_calls.jsonl`. Summarize cost when you finish a study.

## Safety (enforced by hooks, but stay alert)

Stage 2 executes code. The `guard-experiment-exec` PreToolUse hook blocks obviously
dangerous shell (network installs of untrusted code, `rm -rf` outside the run dir,
fork bombs, credential exfiltration). If the hook blocks a command, **do not** try to
route around it — fix the experiment so it doesn't need the dangerous action. The
upstream project warns that LLM-written code is risky; we contain it to the run dir.

## Relationship to upstream AI-Scientist-v2

- Upstream lives (gitignored) in `vendor/AI-Scientist-v2/`. Treat it as the **reference
  spec**: read its prompts, schemas, and LaTeX templates and follow them faithfully.
- The stage skills point you at the exact upstream files to mirror.
- If a stage is easier to run as upstream Python unmodified (e.g. Semantic Scholar
  citation gathering), use the **bridge**: `python -m bridge.run <vendor script> ...`
  routes its LLM calls back through Claude Code. See `bridge/README` notes in `CLAUDE.md`.

## Your operating principles

- **Be a rigorous scientist:** state the hypothesis, design controls/ablations, use
  seeds, report honest metrics (including failures). Never fabricate results — if an
  experiment didn't run or a number is missing, say so in `study.md` and the paper.
- **Keep `study.md` updated** like a lab notebook — it's how the user follows along.
- **Checkpoint state** after every stage so a crash/resume can continue.
