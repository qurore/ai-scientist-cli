"""Execute an experiment script and capture logs + a metric record.

    python -m aisci.exec <project_id|projects/<id>> <script-rel-to-experiment> \
        [--timeout S] [--seed N] [--backend local|colab]

Two backends, identical artifact layout (so journal/plots/writeup/review never
need to know which ran):
  * ``local``  — run the script in a subprocess with cwd = ``projects/<id>/experiment``
                 (the default; only the sandboxed run dir is reachable).
  * ``colab``  — ship the script to a Colab GPU via a Google-Drive job folder and
                 pull the results back (see ``aisci/colab.py`` and ``colab/README.md``).
                 Colab is used as *compute only* — never as an LLM.

Either way: stdout+stderr go to ``logs/<node>.log``; a metric is captured from a
JSON line on stdout containing a ``"metric"`` key, or from a file
``experiment_results/<node>.json`` the script writes itself; a merged record is
written to ``experiment_results/<node>.json`` and printed as one JSON line.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import state


def _find_metric_in_stdout(text: str) -> dict | None:
    found = None
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "metric" in obj:
            found = obj  # keep the last metric line
    return found


def run_local(exp: Path, run_id: str, script: Path, node: str,
              timeout: int, seed: int | None) -> dict:
    """Run ``script`` locally, write logs + result record, return the record."""
    log_path = exp / "logs" / f"{node}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    results_path = exp / "experiment_results" / f"{node}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    if seed is not None:
        env["AISCI_SEED"] = str(seed)
    # Discourage accidental large downloads / network from inside experiments.
    env.setdefault("HF_HUB_OFFLINE", "0")  # leave configurable; skills decide

    t0 = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(exp),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        rc = proc.returncode
        out, err = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        rc = -1
        out = e.stdout or ""
        err = (e.stderr or "") + f"\n[aisci.exec] TIMEOUT after {timeout}s"
    dur = time.time() - t0

    with log_path.open("w") as f:
        f.write(f"$ {sys.executable} {script}\n# cwd={exp}\n# rc={rc} dur={dur:.1f}s\n")
        f.write("\n----- STDOUT -----\n")
        f.write(out or "")
        f.write("\n----- STDERR -----\n")
        f.write(err or "")

    metric = _find_metric_in_stdout(out or "")
    if metric is None and results_path.exists():
        try:
            metric = json.loads(results_path.read_text())
        except json.JSONDecodeError:
            metric = None

    is_buggy = rc != 0 or timed_out or metric is None
    record = {
        "node": node,
        "ok": not is_buggy,
        "is_buggy": is_buggy,
        "returncode": rc,
        "timed_out": timed_out,
        "duration_s": round(dur, 1),
        "metric": metric,
        "seed": seed,
        "log": str(log_path.relative_to(state.run_dir(run_id))),
        "stderr_tail": (err or "")[-800:],
        "backend": "local",
    }
    results_path.write_text(json.dumps(record, indent=2))
    return record


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="aisci.exec")
    p.add_argument("run", help="project id or projects/<id>")
    p.add_argument("script", help="script path relative to the experiment dir, e.g. code/n3.py")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--backend", choices=["local", "colab"], default="local",
                   help="where to run: local subprocess (default) or a Colab GPU")
    args = p.parse_args(argv)

    run_id = Path(args.run).name
    exp = state.run_dir(run_id) / "experiment"
    if not exp.exists():
        print(json.dumps({"ok": False, "error": f"experiment dir missing for run {run_id}"}))
        return 2

    script = (exp / args.script).resolve()
    if not script.exists() or exp not in script.parents:
        print(json.dumps({"ok": False, "error": f"script must live under {exp}"}))
        return 2

    node = script.stem
    if args.backend == "local":
        record = run_local(exp, run_id, script, node, args.timeout, args.seed)
    else:
        from . import colab
        # Pass the *relative* script path so the Colab runner can reconstruct it.
        record = colab.run_colab(run_id, exp, args.script, node, args.timeout, args.seed)

    print(json.dumps(record))
    return 0 if record.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
