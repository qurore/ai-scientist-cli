"""Colab GPU backend for ``aisci.exec`` — compute only, never an LLM.

The Mac host has no CUDA GPU, so this backend borrows one from Google Colab to run
*experiment code* (model building, training, evaluation). The intelligence of the
pipeline (ideation, writing, review) stays with the Claude Code agent — we never
call ``google-colab-ai`` / Gemini or any external LLM.

Two sides, one shared folder (no Google API / OAuth code):

* **client** — ``run_colab`` writes a job (the experiment ``code/`` + ``job.json``)
  into ``$AISCI_COLAB_SYNC/jobs/<job_id>/``, touches ``READY`` last, then polls for
  ``$AISCI_COLAB_SYNC/results/<job_id>/DONE`` and pulls the artifacts back into the
  local run dir (identical layout to the local backend).
* **runner** — on Colab, ``colab/colab_runner.ipynb`` mounts the *same* Drive folder
  and executes jobs on the GPU. ``serve()`` here is a local CPU stand-in for that
  notebook: same protocol, no GPU — handy for dry-running the whole path
  (``python -m aisci.colab serve``) and for the test suite. Both write a
  ``RUNNER_ALIVE`` heartbeat so callers can check a runner is actually up before
  routing heavy nodes to it (``python -m aisci.colab status``).

``$AISCI_COLAB_SYNC`` is the *local* mirror (e.g. via Google Drive for Desktop) of
the Drive folder the notebook mounts — typically ``My Drive/aisci-colab``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import state
from .exec import _find_metric_in_stdout

ALIVE_FILE = "RUNNER_ALIVE"


def _sync_root() -> Path | None:
    root = os.environ.get("AISCI_COLAB_SYNC")
    if not root:
        return None
    return Path(root).expanduser()


# --------------------------------------------------------------------------- #
# Runner liveness (heartbeat)                                                  #
# --------------------------------------------------------------------------- #
def runner_alive(sync_root: Path | str | None = None, max_age: int = 180) -> bool:
    """True if a runner wrote a ``RUNNER_ALIVE`` heartbeat within ``max_age`` s."""
    root = Path(sync_root).expanduser() if sync_root else _sync_root()
    if root is None:
        return False
    hb = root / ALIVE_FILE
    if not hb.exists():
        return False
    try:
        ts = float(hb.read_text().strip())
    except (ValueError, OSError):
        try:
            ts = hb.stat().st_mtime
        except OSError:
            return False
    return (time.time() - ts) <= max_age


# --------------------------------------------------------------------------- #
# Client side: submit a job and pull results back                             #
# --------------------------------------------------------------------------- #
def _err_record(exp: Path, run_id: str, node: str, seed: int | None, msg: str) -> dict:
    """Write a buggy record (+ a log explaining why) so callers get clean JSON."""
    log_path = exp / "logs" / f"{node}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(f"# colab backend error\n{msg}\n")
    rec = {
        "node": node,
        "ok": False,
        "is_buggy": True,
        "returncode": -1,
        "timed_out": False,
        "duration_s": 0.0,
        "metric": None,
        "seed": seed,
        "log": str(log_path.relative_to(state.run_dir(run_id))),
        "stderr_tail": msg[-800:],
        "backend": "colab",
    }
    rp = exp / "experiment_results" / f"{node}.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(rec, indent=2))
    return rec


def run_colab(run_id: str, exp: Path, script_rel: str, node: str,
              timeout: int, seed: int | None) -> dict:
    """Submit a job to the Colab runner over Drive and pull the results back."""
    root = _sync_root()
    if root is None or not root.exists():
        return _err_record(
            exp, run_id, node, seed,
            "AISCI_COLAB_SYNC is not set or does not exist. Point it at your local "
            "Google Drive mirror of 'My Drive/aisci-colab' — the same folder the "
            "Colab runner notebook mounts. See colab/README.md.",
        )

    code_dir = exp / "code"
    if not code_dir.exists():
        return _err_record(exp, run_id, node, seed,
                           f"expected experiment code dir at {code_dir}")

    job_id = f"{run_id}__{node}__{int(time.time())}"
    jobs = root / "jobs" / job_id
    results = root / "results" / job_id
    jobs.mkdir(parents=True, exist_ok=True)

    # Bundle the experiment code (scripts are expected to generate their own
    # small/synthetic data, per the repo's reality checks — we don't ship datasets).
    dst = jobs / "code"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(code_dir, dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (jobs / "job.json").write_text(json.dumps({
        "job_id": job_id,
        "project_id": run_id,
        "node": node,
        "script": script_rel,
        "timeout": timeout,
        "seed": seed,
        "created": time.time(),
    }, indent=2))
    # Give Drive time to upload the code/ files before signaling READY, so the runner
    # never sees READY before the script has synced (a Drive sync race, not atomic).
    time.sleep(int(os.environ.get("AISCI_COLAB_SYNC_WAIT", "10")))
    (jobs / "READY").write_text(str(time.time()))  # written last → atomic-ish handoff

    poll = int(os.environ.get("AISCI_COLAB_POLL", "10"))
    extra = int(os.environ.get("AISCI_COLAB_WAIT", "1800"))
    deadline = time.time() + timeout + extra
    done = results / "DONE"
    while time.time() < deadline:
        if done.exists():
            break
        time.sleep(poll)

    if not done.exists():
        hint = "" if runner_alive(root) else " No runner heartbeat — is the notebook running?"
        return _err_record(
            exp, run_id, node, seed,
            f"No result from Colab within {timeout + extra}s.{hint} "
            f"Watching {root}/jobs; job_id={job_id}",
        )

    # Pull artifacts back into the local run dir (identical layout to local backend).
    (exp / "logs").mkdir(parents=True, exist_ok=True)
    (exp / "experiment_results").mkdir(parents=True, exist_ok=True)
    src_log = results / "logs" / f"{node}.log"
    if src_log.exists():
        shutil.copy(src_log, exp / "logs" / f"{node}.log")
    for f in (results / "experiment_results").glob("*"):
        if f.is_file():
            shutil.copy(f, exp / "experiment_results" / f.name)
    pdir = results / "plots"
    if pdir.exists():
        (exp / "plots").mkdir(parents=True, exist_ok=True)
        for f in pdir.glob("*"):
            if f.is_file():
                shutil.copy(f, exp / "plots" / f.name)

    rp = exp / "experiment_results" / f"{node}.json"
    try:
        rec = json.loads(rp.read_text())
    except Exception:
        return _err_record(exp, run_id, node, seed,
                           f"colab result record missing/corrupt at {rp} (job_id={job_id})")

    # The local run dir is authoritative for the log path; tag the backend.
    rec["log"] = f"experiment/logs/{node}.log"
    rec["backend"] = "colab"
    rp.write_text(json.dumps(rec, indent=2))
    return rec


# --------------------------------------------------------------------------- #
# Runner side: execute a job (local CPU stand-in for the Colab notebook)       #
# --------------------------------------------------------------------------- #
def process_job(job_dir: Path, results_root: Path, workspace: Path) -> dict:
    """Run one job's script and write results + DONE, mirroring the notebook."""
    job = json.loads((job_dir / "job.json").read_text())
    node = job["node"]
    script = job["script"]
    timeout = int(job.get("timeout", 1800))
    seed = job.get("seed")

    work = workspace / job["job_id"]
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copytree(job_dir / "code", work / "code")
    for d in ("experiment_results", "plots", "logs"):
        (work / d).mkdir(exist_ok=True)

    env = dict(os.environ)
    if seed is not None:
        env["AISCI_SEED"] = str(seed)

    t0 = time.time()
    timed_out = False
    try:
        proc = subprocess.run([sys.executable, str(work / script)], cwd=str(work),
                              env=env, capture_output=True, text=True, timeout=timeout)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        rc = -1
        out = e.stdout or ""
        err = (e.stderr or "") + f"\n[aisci.colab] TIMEOUT after {timeout}s"
    dur = time.time() - t0

    (work / "logs" / f"{node}.log").write_text(
        f"$ {sys.executable} {work / script}\n# cwd={work}\n# rc={rc} dur={dur:.1f}s\n"
        "\n----- STDOUT -----\n" + (out or "") + "\n----- STDERR -----\n" + (err or ""))

    metric = _find_metric_in_stdout(out or "")
    rp = work / "experiment_results" / f"{node}.json"
    if metric is None and rp.exists():
        try:
            metric = json.loads(rp.read_text())
        except json.JSONDecodeError:
            metric = None

    is_buggy = rc != 0 or timed_out or metric is None
    record = {
        "node": node, "ok": not is_buggy, "is_buggy": is_buggy, "returncode": rc,
        "timed_out": timed_out, "duration_s": round(dur, 1), "metric": metric,
        "seed": seed, "log": f"experiment/logs/{node}.log",
        "stderr_tail": (err or "")[-800:], "backend": "colab",
    }
    (work / "experiment_results" / f"{node}.json").write_text(json.dumps(record, indent=2))

    res = results_root / job["job_id"]
    if res.exists():
        shutil.rmtree(res)
    (res / "logs").mkdir(parents=True)
    (res / "experiment_results").mkdir(parents=True)
    (res / "plots").mkdir(parents=True)
    shutil.copy(work / "logs" / f"{node}.log", res / "logs" / f"{node}.log")
    for f in (work / "experiment_results").glob("*"):
        if f.is_file():
            shutil.copy(f, res / "experiment_results" / f.name)
    for f in (work / "plots").glob("*"):
        if f.is_file():
            shutil.copy(f, res / "plots" / f.name)
    (res / "DONE").write_text(str(time.time()))  # written last
    return record


def serve(sync_root: Path | str, once: bool = False, poll: int | None = None) -> None:
    """Watch ``jobs/`` and process jobs (local CPU stand-in for the GPU notebook)."""
    root = Path(sync_root).expanduser()
    jobs = root / "jobs"
    results = root / "results"
    workspace = root / "_work"
    for d in (jobs, results, workspace):
        d.mkdir(parents=True, exist_ok=True)
    poll = poll or int(os.environ.get("AISCI_COLAB_POLL", "10"))
    print(f"[aisci.colab serve] watching {jobs} (CPU stand-in; no GPU)")
    while True:
        (root / ALIVE_FILE).write_text(str(time.time()))  # heartbeat
        for ready in sorted(jobs.glob("*/READY")):
            job_dir = ready.parent
            if (job_dir / "PROCESSED").exists():
                continue
            (job_dir / "PROCESSED").write_text(str(time.time()))  # claim once
            try:
                rec = process_job(job_dir, results, workspace)
                print(f"[done] {job_dir.name} ok={rec['ok']} dur={rec['duration_s']}s")
            except Exception:
                import traceback
                traceback.print_exc()
        if once:
            break
        time.sleep(poll)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="aisci.colab")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run a local CPU runner (test stand-in for the notebook)")
    s.add_argument("sync_root", nargs="?", default=os.environ.get("AISCI_COLAB_SYNC"))
    s.add_argument("--once", action="store_true", help="process current jobs and exit")
    s.add_argument("--poll", type=int, default=None)

    st = sub.add_parser("status", help="report whether a runner heartbeat is fresh")
    st.add_argument("sync_root", nargs="?", default=os.environ.get("AISCI_COLAB_SYNC"))
    st.add_argument("--max-age", type=int, default=180)

    args = p.parse_args(argv)

    if args.cmd == "serve":
        if not args.sync_root:
            print(json.dumps({"ok": False, "error": "set AISCI_COLAB_SYNC or pass a path"}))
            return 2
        serve(args.sync_root, once=args.once, poll=args.poll)
        return 0

    if args.cmd == "status":
        if not args.sync_root:
            print(json.dumps({"ok": False, "error": "set AISCI_COLAB_SYNC or pass a path"}))
            return 2
        alive = runner_alive(args.sync_root, max_age=args.max_age)
        print(json.dumps({"ok": True, "runner_alive": alive, "sync_root": str(args.sync_root)}))
        return 0 if alive else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
