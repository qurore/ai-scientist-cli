# Colab GPU backend (compute only)

The Mac host has no CUDA GPU. This optional backend borrows one from **Google Colab**
to run **experiment code** (model building, training, evaluation) for the *experiment*
stage. Everything else — ideation, paper writing, review — stays with the Claude Code
agent on your machine.

> **Compute, not an LLM.** We deliberately do **not** use `google-colab-ai` / Gemini or
> any external LLM. That would break this project's core principle ("*you, the Claude
> Code agent, are the scientist; no external LLM API keys are used*"). Colab is treated
> exactly like the arxiv / semantic-scholar MCP servers: a tool/compute resource, not a
> brain.

## How it works

A plain shared folder — no Google API or OAuth code:

```
aisci.exec --backend colab            Colab runner notebook (GPU)
   │  write job + READY  ─────►  My Drive/aisci-colab/jobs/<job_id>/
   │                                         │ run script.py on GPU
   │  poll for DONE  ◄─────  My Drive/aisci-colab/results/<job_id>/  (logs, results, plots, DONE)
   ▼
projects/<id>/experiment/   ← artifacts pulled back, identical layout to local runs
```

Because the layout the backend produces is identical to the local backend
(`logs/<node>.log` + `experiment_results/<node>.json`), the journal, plotting, writeup,
and review stages don't change at all.

## One-time setup

1. **Drive folder.** In Google Drive, create `My Drive/aisci-colab/`.
2. **Local mirror.** Install *Google Drive for Desktop* so that folder syncs to your Mac.
   Find its local path, e.g.
   `~/Library/CloudStorage/GoogleDrive-<you>@gmail.com/My Drive/aisci-colab`.
3. **Point the backend at it:**
   ```bash
   export AISCI_COLAB_SYNC="$HOME/Library/CloudStorage/GoogleDrive-<you>@gmail.com/My Drive/aisci-colab"
   ```
4. **Start the runner.** Upload `colab/colab_runner.ipynb` to Colab, set
   Runtime → GPU, **Run all**, approve the Drive mount, and leave the last cell running.

## Use it

```bash
# run one experiment node on the Colab GPU instead of locally
.venv/bin/python -m aisci.exec projects/<id> code/n3.py --timeout 1800 --backend colab
```

The call blocks until the GPU result syncs back (or it times out with a clear message).
Optional env knobs:

| var | default | meaning |
|---|---|---|
| `AISCI_COLAB_SYNC` | *(required)* | local mirror of `My Drive/aisci-colab` |
| `AISCI_COLAB_POLL` | `10` | seconds between result polls |
| `AISCI_COLAB_WAIT` | `1800` | extra seconds to wait beyond the script `--timeout` |

In the experiment stage, just add `--backend colab` to the `aisci.exec` calls you want
on GPU; keep cheap/CPU steps local. The experiment skill auto-routes only *heavy* nodes
to Colab, and only when attended (not autopilot) and a runner is alive.

## Check a runner is up

The runner (notebook or local stand-in) writes a `RUNNER_ALIVE` heartbeat. Check it:

```bash
.venv/bin/python -m aisci.colab status     # {"runner_alive": true/false, ...}
```

## Dry-run without Colab

You can exercise the whole submit → run → pull-back path locally — no Drive, no GPU —
with a CPU stand-in for the notebook (same job protocol):

```bash
# terminal 1: start the local runner on any folder
.venv/bin/python -m aisci.colab serve /tmp/aisci-sync

# terminal 2: point the backend at the same folder and run a node
AISCI_COLAB_SYNC=/tmp/aisci-sync \
  .venv/bin/python -m aisci.exec projects/<id> code/n3.py --backend colab
```

This validates everything except the actual remote GPU; for that, use the notebook.

## Honest constraints

- **No headless Colab API.** The runner notebook must be **open and running**; this is a
  semi-automated handoff, not unattended automation. Don't rely on it for autopilot.
- **Session limits.** Free Colab: idle timeout (~90 min), max ~12 h, GPU not guaranteed,
  can disconnect anytime. If the runner dies, restart it and re-run the node.
- **Sync latency.** Drive ↔ Colab propagation is seconds-to-minutes; the generous
  `AISCI_COLAB_WAIT` covers it. If Colab seems blind to new jobs, remount Drive.
- **Data.** Scripts should generate their own small/synthetic data (per the repo's
  reality checks) — the backend ships only `code/`, not datasets.

## Safety

- The Colab VM is a **throwaway Google sandbox** and an **untrusted remote**. Only the
  experiment `code/` is shipped there — never secrets or credentials.
- The local `guard_experiment_exec` hook still governs orchestration on your machine.
- You are running your own experiment code on Google's hardware; review the script
  before submitting it, same as any experiment.
