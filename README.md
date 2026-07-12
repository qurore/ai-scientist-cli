# AI-Scientist on Claude Code

Run [Sakana AI's **AI-Scientist-v2**](https://github.com/SakanaAI/AI-Scientist-v2)
research pipeline — *idea → experiments → paper → peer review* — **entirely inside
Claude Code**, with **no external LLM API keys**. The Claude Code agent itself is the
scientist; the pipeline is implemented natively with Claude Code **Skills** (the stages)
and **Hooks** (automation + safety).

> Status: **base scaffolding**. The bridge, skills, hooks, helpers, setup, and docs are
> in place and verified. Each stage skill is a working v1 procedure to iterate on.

## Why this design

AI-Scientist-v2 normally calls OpenAI/Anthropic/Gemini APIs for every decision. Here,
every stage maps onto something Claude Code already does well — writing & running code,
reading PDFs and images, web search, agentic iteration — so we let **Claude Code be the
brain** and use the native ecosystem instead of recursive API calls. A thin optional
*bridge* can still run the upstream Python unmodified by routing its LLM calls back
through the `claude` CLI in headless mode.

## Layout

| Path | What |
|------|------|
| `.claude/skills/` | `ai-scientist` orchestrator + `ideate` / `experiment` / `writeup` / `review` stages |
| `.claude/hooks/` | `session_start` (status), `guard_experiment_exec` (safety), `log_tool_use` (provenance), `stop_autopilot` (autonomy) |
| `.claude/settings.json` | wires hooks; autopilot off by default; minimal permissions |
| `aisci/` | thin Python helpers (`run`, `exec`, `latex`, `state`) the skills call |
| `config/` | `model_map.json` (bridge model overrides) + `rubrics/` (per-genre review rubrics; a project picks one via `state.json`) |
| `bridge/` | optional `claude -p` adapter for running upstream stages unmodified |
| `scripts/` | `setup.sh`, `doctor.sh` |
| `ideas/` | topic *staging* area (drafts + template); gitignored except the template |
| `vendor/AI-Scientist-v2/` | upstream clone — the reference spec (gitignored) |
| `projects/<slug>/` | one self-contained study per folder — **your projects** (gitignored by default) |

## Quick start

```bash
# 1. Set up (clones upstream into vendor/, builds .venv, installs deps)
bash scripts/setup.sh
bash scripts/doctor.sh          # verify

# 2. In Claude Code, start a study:
#    /ai-scientist  "compositional generalization in small MLPs"
#    …then run the stages, or set AISCI_AUTOPILOT=1 to run hands-off.
```

Stages can also be invoked directly: `/ai-scientist-ideate`,
`/ai-scientist-experiment`, `/ai-scientist-writeup`, `/ai-scientist-review`.

## Projects & privacy

Each study is a **self-contained project** under `projects/<slug>/` — idea, experiment
code, logs, results, plots, paper, and review all live in that one folder (see
[`projects/README.md`](./projects/README.md)). Nothing project-specific is scattered
elsewhere; even the topic is copied in from its `ideas/` draft.

Your projects (and `ideas/` topic drafts) are **gitignored by default**, so you can push
the integration layer to a **public** remote without shipping your studies. Keeping this
as a **private** repo and want to version your studies too? Comment out the `/projects/*`
(and `/ideas/*`) line in [`.gitignore`](./.gitignore) — the toggle is documented inline
there. A single `projects/<slug>/` is portable: copy it out and `git init` it as its own
private repo.

## Requirements

- **Claude Code** logged in (`claude` CLI on PATH) — this powers everything.
- **Python 3.11** (upstream requires it).
- For the writeup stage: a LaTeX toolchain (`basictex`/MacTeX), `poppler`, `chktex`
  (`brew install basictex chktex poppler`).
- This is a **macOS / no-GPU** setup: experiments are intentionally small (CPU/MPS,
  tiny/synthetic data). Scale up on a CUDA box via the bridge launcher if needed.

## Safety

Experiments execute model-written code. A `PreToolUse` hook blocks destructive,
credential-stealing, and sandbox-escaping shell, and confines all experiment I/O to the
run directory. Review `.claude/hooks/guard_experiment_exec.py` for the policy. Use at
your own discretion — see upstream's caution about autonomous code execution.

## How it maps to upstream

| Upstream | Here |
|----------|------|
| `perform_ideation_temp_free.py` | `ai-scientist-ideate` skill (native) / bridge for parity |
| `launch_scientist_bfts.py` (BFTS tree search) | `ai-scientist-experiment` skill (native) / bridge launcher |
| `perform_writeup.py` / `perform_icbinb_writeup.py` | `ai-scientist-writeup` skill |
| `perform_llm_review.py` / `perform_vlm_review.py` | `ai-scientist-review` skill |
| `ai_scientist/llm.py`, `vlm.py`, `treesearch/backend` | `bridge/*_backend.py` (Claude-Code-served) |

See [`CLAUDE.md`](./CLAUDE.md) for the full operating guide.

## License / attribution

Upstream AI-Scientist-v2 is © Sakana AI, under its own license (see
`vendor/AI-Scientist-v2/LICENSE` after setup). This repo contains only the Claude Code
integration layer; the upstream code is fetched locally and never committed.
