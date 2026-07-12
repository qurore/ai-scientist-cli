#!/usr/bin/env python3
"""SessionStart hook: print a short AI-Scientist environment status banner.

Whatever this prints on stdout is added to the session context, so it doubles as
a quick orientation for the agent: is the env ready, is a study in progress, what
to do next. Must never crash the session — everything is best-effort.
"""

import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()


def _read_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _has(cmd):
    return shutil.which(cmd) is not None


def main():
    _read_stdin()  # consume payload; we don't need fields here
    lines = ["=== AI-Scientist on Claude Code — environment ==="]

    venv = REPO / ".venv"
    vendor = REPO / "vendor" / "AI-Scientist-v2"
    lines.append(f"venv:    {'ready' if venv.exists() else 'MISSING (run scripts/setup.sh)'}")
    lines.append(f"vendor:  {'present' if vendor.exists() else 'MISSING (run scripts/setup.sh)'}")

    tools = {
        "claude": _has("claude"),
        "pdflatex": _has("pdflatex"),
        "pdftotext(poppler)": _has("pdftotext"),
        "chktex": _has("chktex"),
    }
    ready = ", ".join(k for k, v in tools.items() if v)
    missing = ", ".join(k for k, v in tools.items() if not v)
    lines.append(f"tools ok: {ready or '(none)'}")
    if missing:
        lines.append(f"tools missing: {missing}  (writeup needs pdflatex/poppler/chktex)")

    # Current study, if any.
    try:
        sys.path.insert(0, str(REPO))
        from aisci import state  # noqa: E402
        rid = state.current_run()
        if rid:
            st = state.load_state(rid)
            lines.append(
                f"current study: {rid}  (stage={st.get('stage')}, status={st.get('status')})"
            )
        else:
            lines.append("current study: none — use the `ai-scientist` skill to start one")
    except Exception:
        pass

    autopilot = os.environ.get("AISCI_AUTOPILOT", "0") == "1"
    lines.append(f"autopilot: {'ON' if autopilot else 'off (pause between stages)'}")
    lines.append("Skills: /ai-scientist, /ai-scientist-ideate, -experiment, -writeup, -review")

    print("\n".join(lines))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
