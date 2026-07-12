---
name: ai-scientist-experiment
description: Stage 2 of the AI Scientist pipeline — run the agentic experiment loop (a Claude-native version of AI-Scientist-v2's best-first tree search) to implement, execute, debug, and improve experiment code across preliminary → tuning → research → ablation stages, recording a journal, metrics, and plots. Use after an idea exists and the user wants to actually run experiments.
---

# Stage 2 — Experiments (agentic tree search, Claude-native)

Implement and run the experiments for the chosen idea. This mirrors AI-Scientist-v2's
**best-first tree search (BFTS)** with an experiment-manager agent, but you run it
natively: you write code, execute it with Bash (guarded by the safety hook), read
results, debug, and iterate — keeping a journal so the search is resumable.

## Authoritative reference
`vendor/AI-Scientist-v2/ai_scientist/treesearch/` — especially
`perform_experiments_bfts_with_agentmanager.py`, `agent_manager.py`,
`parallel_agent.py`, `journal.py`. `vendor/AI-Scientist-v2/bfts_config.yaml` holds the
canonical hyperparameters. Read these to stay faithful to the method.

## Inputs
- `projects/<id>/idea.json` (chosen idea; `state.idea_slug` selects which one).
- Hyperparameters (defaults mirror `bfts_config.yaml`, scaled down for a laptop):
  `num_drafts=3`, `max_debug_depth=3`, `num_seeds=3`, per-stage iteration caps
  `[stage1=20, stage2=12, stage3=12, stage4=18]`. **On this machine, cut caps to a
  few iterations** unless the user asks for more — be honest about the trade-off.

## The four progressive stages
1. **Preliminary** — get a minimal correct implementation of the idea running end-to-end
   on tiny/synthetic data; establish that the pipeline produces a metric.
2. **Tuning** — tune the baseline (hyperparameters, training length) to a sensible
   operating point. Record the baseline metric.
3. **Research** — run the actual hypothesis-testing experiments (the idea's
   `Experiments`). Compare against the baseline. Multi-seed (`num_seeds`) for variance.
4. **Ablation** — remove/vary components to isolate what matters.

## Tree-search loop (per stage)
Maintain `projects/<id>/experiment/journal.jsonl`; one JSON line per node:
```json
{"id":"n3","parent":"n1","stage":1,"plan":"...","code_path":"code/n3.py",
 "metric":0.83,"is_buggy":false,"seeds":[0,1,2],"notes":"...","ts": 0}
```
Procedure:
1. **Draft:** create `num_drafts` independent initial implementations (different
   approaches) as root nodes. Keep each script self-contained under `experiment/code/`.
   **Parallelize independent branches with sub-agents:** when several drafts/configs are
   genuinely independent, spawn one sub-agent per branch — each writes and runs its own
   script under `experiment/code/` (heavy nodes via `--backend colab`) and reports its
   metric; you then merge them into the journal and pick the best. Use this for real
   parallelism, not for sequential debugging of one branch.
2. **Execute** each via the run helper so output/metrics are captured to
   `experiment/logs/` and `experiment/experiment_results/`:
   ```bash
   .venv/bin/python -m aisci.exec projects/<id> code/n3.py --timeout 1800
   ```
   The script must print a JSON metrics line (e.g. `{"metric": 0.83, "loss": ...}`) or
   write `experiment_results/<node>.json`. Capture stdout/stderr to the log.
   - **Heavy node?** Add `--backend colab` to run it on a Colab GPU (compute only). Same
     artifact layout, so the rest of this procedure is unchanged. See *Compute routing*.
3. **Evaluate:** parse the metric. Mark `is_buggy=true` if it crashed or produced no
   metric.
4. **Best-first expand:** pick the best non-buggy node and improve it (next iteration),
   or debug a buggy node (up to `max_debug_depth` consecutive debug attempts before
   abandoning that branch).
5. **Stop the stage** when the iteration cap is hit or the metric plateaus, then advance
   to the next stage seeded from the best node.
6. **Multi-seed** the best research-stage node across `num_seeds` seeds and record
   mean ± std.

## Compute routing (heavy nodes → Colab GPU)
No CUDA GPU on this host. Decide **per node** where it runs — the artifacts come back in
the same layout either way, so journal/plots/summary don't care which ran.
- **Local (default):** preliminary, debugging, plotting, and anything that fits CPU/MPS
  within the node's timeout. Keep it tiny (see reality checks).
- **Colab GPU (`--backend colab`):** only when the node *genuinely needs* a GPU (model or
  training too big/slow for CPU/MPS) **and all** of:
  1. **Attended, not autopilot.** If `AISCI_AUTOPILOT=1`, keep the node local and small —
     the Colab runner is a human-attended notebook, so **never block unattended autopilot
     on it**.
  2. **`AISCI_COLAB_SYNC` is set**, and
  3. **a runner is alive:** `.venv/bin/python -m aisci.colab status` reports
     `runner_alive: true`. If not, ask the user to start `colab/colab_runner.ipynb` on a
     GPU runtime, or just run the node locally — don't silently hang on a dead runner.

Compute only — Colab never does ideation/writing/review (`google-colab-ai`/Gemini are off
limits). No runner handy? `python -m aisci.colab serve <dir>` is a local CPU stand-in for
dry-running the path. See `colab/README.md`.

## Execution rules (safety)
- All code, data, and outputs stay **inside `projects/<id>/experiment/`**. Never write
  outside the run dir.
- Datasets: prefer synthetic generators or tiny built-in datasets (e.g. sklearn toy
  sets, `torchvision` MNIST-scale only if small). Don't download large datasets.
- The `guard-experiment-exec` hook will block dangerous shell. If blocked, redesign —
  don't bypass.
- Set seeds everywhere; log versions. Use CPU or MPS (`torch.device("mps")` if
  available) — there is no *local* CUDA; for GPU-bound nodes use the Colab backend per
  *Compute routing* above.

## Plots
After the research/ablation stages, aggregate figures into `experiment/plots/`
(matplotlib/seaborn). Mirror the intent of
`vendor/AI-Scientist-v2/ai_scientist/perform_plotting.py`: one clear figure per claim,
with axis labels, legends, and captions saved alongside (`<fig>.caption.txt`).

## Outputs
- `experiment/experiment_results/` — metrics JSON per node + a `summary.json` with the
  best results per stage (baseline, research, ablation), seeds, and mean±std.
- `experiment/plots/*.png|pdf` (+ captions).
- `experiment/journal.jsonl` — the full search trace.
- Update `state.json`: `stage="experiment"`, `status="done"`. Append findings to
  `study.md` (what worked, what didn't, key numbers — **honestly**).

## Output to the user
Summarize: best result vs baseline, what the ablations showed, surprises/failures, and
total wall-clock + token cost. Offer to proceed to `/ai-scientist-writeup`.

## Bridge fallback (full upstream BFTS, unmodified)
Heavy and GPU-oriented, but available:
```bash
python -m bridge.run vendor/AI-Scientist-v2/launch_scientist_bfts.py \
  --load_ideas projects/<id>/idea.json --idea_idx 0 --skip_writeup --skip_review
```
Requires `torch`+`psutil` (see `scripts/setup.sh`). Routes all agent LLM calls through
Claude Code. Use only if the user explicitly wants upstream parity.
