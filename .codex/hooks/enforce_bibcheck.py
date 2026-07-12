#!/usr/bin/env python3
"""PreToolUse(Bash) gate: no hallucinated citations in a finalized paper.

Integrity requirement: every citation in the paper must be a real, findable paper.
The ``aisci.bibcheck`` helper verifies this deterministically (Crossref + arXiv APIs,
no LLM/MCP) and writes ``projects/<id>/writeup/bibcheck.json``. This hook makes acting
on that report non-optional: the writeup stage cannot be marked ``done`` (nor the study
``complete``) until a **fresh, clean** report exists.

Fresh  = the report's recorded ``bib_sha256`` matches the current ``references.bib`` (so
         you can't pass an old report and then edit the bib).
Clean  = zero blocking entries (no DOI/arXiv id that fails to resolve, no title that no
         real paper matches) AND at least one citation was actually verified (a report
         where nothing could be reached is offline noise, not a real check).

The hook never touches the network itself — it only reads the JSON the helper wrote, so
it stays fast and deterministic. It is narrow: it only intercepts the
``aisci.run set ... --status done`` / ``--complete`` command for the writeup/review
stages, and is neutral on everything else. It never hard-fails. A project with no
``references.bib`` is neutral (nothing to verify).
"""

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


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
        from aisci import state, bibcheck
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

        # Citations only become a finalized artifact at writeup; review-done is a backstop.
        if stage not in ("writeup", "review"):
            neutral()

        project_dir = state.project_dir(pid)
        bib = bibcheck.find_bib(project_dir)
        if not bib:
            neutral()  # no references.bib → nothing to verify

        report_path = project_dir / "writeup" / "bibcheck.json"
        run_hint = f".venv/bin/python -m aisci.bibcheck projects/{pid}"

        if not report_path.exists():
            deny(
                f"[bibcheck] '{stage}' can't be closed: no citation-verification report at "
                f"projects/{pid}/writeup/bibcheck.json. Every citation must be a real, findable "
                f"paper — verify them deterministically first:\n  {run_hint}\n"
                f"Fix any flagged (fabricated) references, then re-run the set command."
            )

        try:
            report = json.loads(report_path.read_text())
        except Exception:
            deny(f"[bibcheck] report at projects/{pid}/writeup/bibcheck.json is unreadable; "
                 f"regenerate it:\n  {run_hint}")

        # Stale? The report must describe the *current* references.bib.
        current_sha = bibcheck.sha256_of(bib)
        if report.get("bib_sha256") != current_sha:
            deny(
                f"[bibcheck] the citation report is stale — references.bib changed since it was "
                f"generated. Re-verify before closing '{stage}':\n  {run_hint}"
            )

        blocking = int(report.get("blocking", 0) or 0)
        if blocking > 0:
            flagged = [f"{e.get('key','?')} ({e.get('status')})"
                       for e in report.get("entries", [])
                       if e.get("status") in bibcheck.BLOCKING][:6]
            deny(
                f"[bibcheck] {blocking} citation(s) look fabricated/hallucinated and must be fixed "
                f"before closing '{stage}': {', '.join(flagged)}. A DOI/arXiv id that doesn't "
                f"resolve, or a title no real paper matches, is not acceptable. Correct or remove "
                f"them (verify the real entry via the arxiv/semantic-scholar MCP), then re-run:\n"
                f"  {run_hint}"
            )

        # A report where nothing could be reached isn't a real verification.
        if report.get("nothing_verified"):
            deny(
                f"[bibcheck] the citation report verified 0 references (looks offline/rate-limited) "
                f"— that's not a real check. Re-run while online before closing '{stage}':\n  {run_hint}"
            )
    except SystemExit:
        raise
    except Exception:
        neutral()
    neutral()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
