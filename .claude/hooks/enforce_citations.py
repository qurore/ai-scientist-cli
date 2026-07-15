#!/usr/bin/env python3
"""PreToolUse(Bash) gate: every citation ships with primary-source evidence.

``aisci.citations`` maintains a per-citation evidence vault under
``projects/<id>/writeup/citations/``: registry-generated bib entries, the cited
paper's archived PDF + extracted text, a snapshot of the source webpage, and usage
records whose supporting quotes must appear verbatim in the archived text. This hook
makes that vault non-optional: the writeup stage cannot be marked ``done`` (nor the
study ``complete``) until ``citations verify`` reports a **fresh, fully clean** vault.

Fresh = the index's recorded ``bib_sha256`` matches the current ``references.bib``
        AND its ``tex_sha256`` matches the current main .tex (so you can't verify,
        then keep editing).
Clean = zero blocking issues (metadata mismatch vs the registry, missing PDF/snapshot/
        evidence, a quote that isn't really in the cited paper, an uncited entry, ...)
        and at least one entry actually verified.

Tamper resistance: the hook does not just trust ``index.json`` — it re-runs the
verification **offline** (local artifacts + the registry snapshots recorded in each
evidence.json; no network) and denies if that recheck disagrees. Hand-editing
index.json therefore achieves nothing; the only way through is a genuinely complete
vault. The hook is narrow: it only intercepts ``aisci.run set ... --status done`` /
``--complete`` for the writeup/review stages, never hard-fails, and is neutral when
the project has no ``references.bib``.
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
        from aisci import state, bibcheck, citations
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

        if stage not in ("writeup", "review"):
            neutral()

        project_dir = state.project_dir(pid)
        bib = bibcheck.find_bib(project_dir)
        if not bib:
            neutral()  # no references.bib → nothing to evidence

        index_path = citations.vault_dir(project_dir) / citations.INDEX_NAME
        run_hint = (f".venv/bin/python -m aisci.citations verify projects/{pid}\n"
                    f"(build missing evidence first: aisci.citations fetch projects/{pid} --all, "
                    f"then aisci.citations usage ... per reference)")

        if not index_path.exists():
            deny(
                f"[citations] '{stage}' can't be closed: no citation-evidence index at "
                f"projects/{pid}/writeup/citations/index.json. Every reference needs its vault "
                f"(archived PDF + page snapshot + quote-verified usage evidence). Run:\n  {run_hint}"
            )

        try:
            index = json.loads(index_path.read_text())
        except Exception:
            deny(f"[citations] index at projects/{pid}/writeup/citations/index.json is "
                 f"unreadable; regenerate it:\n  {run_hint}")

        if index.get("bib_sha256") != bibcheck.sha256_of(bib):
            deny(f"[citations] the evidence index is stale — references.bib changed since it "
                 f"was generated. Re-verify before closing '{stage}':\n  {run_hint}")
        tex = citations.find_main_tex(project_dir)
        if tex is not None and index.get("tex_sha256") != bibcheck.sha256_of(tex):
            deny(f"[citations] the evidence index is stale — the paper source changed since it "
                 f"was generated. Re-verify before closing '{stage}':\n  {run_hint}")

        if int(index.get("blocking", 0) or 0) > 0 or not index.get("ok", False):
            bad = [f"{e.get('key', '?')}: {e['blocking'][0]}"
                   for e in index.get("entries", []) if e.get("blocking")][:5]
            bad += index.get("index_blocking", [])[:2]
            deny(
                f"[citations] {index.get('blocking', '?')} blocking citation-evidence issue(s) "
                f"must be fixed before closing '{stage}':\n  - " + "\n  - ".join(bad) +
                f"\nFix the references/evidence for real (never hand-edit index.json), then:\n  {run_hint}"
            )
        if index.get("nothing_verified"):
            deny(f"[citations] the evidence index verified 0 references — that's not a real "
                 f"check. Re-run online before closing '{stage}':\n  {run_hint}")

        # Tamper resistance: recompute everything checkable offline. If this disagrees
        # with the (clean) index, the index was edited or artifacts drifted — deny.
        recheck = citations.run_verify(project_dir, offline=True, write=False)
        if not recheck.get("ok", False):
            bad = [f"{e.get('key', '?')}: {e['blocking'][0]}"
                   for e in recheck.get("entries", []) if e.get("blocking")][:5]
            deny(
                f"[citations] index.json says clean but the offline recheck found "
                f"{recheck.get('blocking', '?')} blocking issue(s):\n  - " + "\n  - ".join(bad) +
                f"\nThe vault must actually be complete — re-run:\n  {run_hint}"
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
