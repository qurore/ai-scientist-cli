#!/usr/bin/env python3
"""Stop hook: optional, bounded autopilot for the AI-Scientist pipeline.

When ``AISCI_AUTOPILOT=1`` and a study is in progress (not yet ``complete``),
this blocks the agent from stopping and re-prompts it to advance to the next
stage, so a full study can run hands-off. It is **off by default** — without the
env var the agent pauses between stages for the user to review.

Safety: a counter in ``.aisci_cache/autopilot_count`` caps the number of
auto-advances (default 8) so a misbehaving loop can't run forever.
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
CACHE = REPO / ".aisci_cache"
MAX_ADVANCES = int(os.environ.get("AISCI_AUTOPILOT_MAX", "8"))
STAGES = ["ideate", "experiment", "writeup", "review"]


def _count() -> int:
    p = CACHE / "autopilot_count"
    try:
        return int(p.read_text().strip())
    except Exception:
        return 0


def _set_count(n: int) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "autopilot_count").write_text(str(n))


def _allow_stop():
    _set_count(0)
    sys.exit(0)


def main():
    if os.environ.get("AISCI_AUTOPILOT", "0") != "1":
        _allow_stop()

    try:
        payload = json.load(sys.stdin)
    except Exception:
        _allow_stop()

    # Avoid tight loops: if we're already continuing from a stop hook, be cautious.
    if payload.get("stop_hook_active") and _count() >= MAX_ADVANCES:
        _allow_stop()

    try:
        sys.path.insert(0, str(REPO))
        from aisci import state
        rid = state.current_run()
        if not rid:
            _allow_stop()
        st = state.load_state(rid)
    except Exception:
        _allow_stop()

    if st.get("status") == "complete":
        _allow_stop()

    n = _count()
    if n >= MAX_ADVANCES:
        # Hit the safety cap — stop and let the user check in.
        _set_count(0)
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"[autopilot] Reached the {MAX_ADVANCES}-step safety cap for run "
                f"{rid}. Pausing. Summarize progress for the user and ask whether "
                f"to continue (they can raise AISCI_AUTOPILOT_MAX)."
            ),
        }))
        sys.exit(0)

    stage = st.get("status_stage", st.get("stage", "ideate"))
    status = st.get("status", "pending")
    # Decide the next concrete action.
    if status == "done" and stage in STAGES and stage != STAGES[-1]:
        nxt = STAGES[STAGES.index(stage) + 1]
        action = f"stage '{stage}' is done — start the next stage '{nxt}' using /ai-scientist-{nxt}"
    elif stage == "review" and status == "done":
        action = "review is done — set the study status to 'complete' (aisci.run set --complete)"
    else:
        action = f"continue working stage '{stage}' (status={status}) using /ai-scientist-{stage}"

    _set_count(n + 1)
    print(json.dumps({
        "decision": "block",
        "reason": (
            f"[autopilot {n+1}/{MAX_ADVANCES}] Study {rid}: {action}. "
            f"Keep `projects/{rid}/state.json` and study.md updated. When the whole "
            f"pipeline is finished, run `aisci.run set --complete` so autopilot stops."
        ),
    }))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
