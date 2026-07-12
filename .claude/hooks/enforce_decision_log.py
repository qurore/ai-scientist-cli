#!/usr/bin/env python3
"""PreToolUse(Bash) gate: enforce decision provenance per pipeline stage.

Observability requirement: a human should later be able to see *which decisions*
produced the current artifact. We keep an append-only log at
``projects/<id>/decisions.jsonl``. This hook makes recording it non-optional:
a stage cannot be marked ``done`` (or the study ``complete``) until at least one
decision has been logged for that stage via ``aisci.run decide``.

The hook is narrow: it only intercepts the ``aisci.run set ... --status done`` /
``--complete`` command and is neutral on everything else, so normal work is
unaffected. It never hard-fails.
"""

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()


def neutral():
    sys.exit(0)


def deny(reason: str):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        neutral()

    if payload.get("tool_name") != "Bash":
        neutral()
    cmd = (payload.get("tool_input") or {}).get("command", "")

    # Only gate the stage-completion command.
    if "aisci.run" not in cmd or not re.search(r"\bset\b", cmd):
        neutral()
    marks_done = re.search(r"--status\s+done\b", cmd) is not None
    marks_complete = "--complete" in cmd
    if not (marks_done or marks_complete):
        neutral()

    try:
        sys.path.insert(0, str(REPO))
        from aisci import state
        pid = state.current_project()
        if not pid:
            neutral()
        st = state.load_state(pid)
        m = re.search(r"--stage\s+(\w+)", cmd)
        if m:
            stage = m.group(1)
        elif marks_complete:
            stage = "review"  # --complete is the final (review) verdict
        else:
            stage = st.get("stage", "")

        path = state.project_dir(pid) / "decisions.jsonl"
        count = 0
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("stage") == stage:
                    count += 1

        if count == 0:
            deny(
                f"[decision-log] Stage '{stage}' has no recorded decision yet, so it "
                f"cannot be closed. Log the key decision(s) that shaped this stage first:\n"
                f'  .venv/bin/python -m aisci.run decide --decision "<what you decided>" '
                f'--why "<why>" [--alternatives "a; b"] [--evidence "<file/result>"]\n'
                f"This append-only trail (projects/{pid}/decisions.jsonl) is how a human "
                f"later reconstructs how the result was produced. Then re-run the set command."
            )
    except Exception:
        neutral()
    neutral()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
