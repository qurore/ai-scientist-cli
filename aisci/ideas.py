"""Human-idea inbox: a per-project markdown file where a human can drop research
ideas/hypotheses at any time. The improvement loop reads the OPEN entries at the
start of each iteration, tests them, and closes each with an outcome so it is not
re-read or re-tested in later loops (a refuted hypothesis cannot pull the research
off course again).

File: ``projects/<id>/human_ideas.md``. An OPEN entry is a heading ``## [ ] title``
followed by free-text body; closing flips it to ``## [x] title`` and appends a
``**Tested** ...`` annotation. Created empty (template only) with each project.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import state

HEADER = re.compile(r"^##\s+\[([ xX])\]\s+(.*)$")

TEMPLATE = """# Human research ideas — inbox for project: {slug}

<!--
Drop a research idea or hypothesis here AT ANY TIME (even mid-study). At the start of each
improvement-loop iteration, the AI Scientist reads every OPEN entry (unchecked box `[ ]`)
below, tests or incorporates it alongside the review-driven work, records the outcome, and
checks the box `[x]` so it is NOT re-read or re-tested in later loops. A refuted hypothesis
stays closed with its result, so it will not pull later iterations off course.

Add an idea by appending a block exactly like this (keep the "## [ ] " prefix):

## [ ] short title of the idea
What to try, the hypothesis, and why. One or more lines of free text.
-->
"""


def path(run_id: str) -> Path:
    return state.project_dir(run_id) / "human_ideas.md"


def ensure(run_id: str, slug: str = "") -> Path:
    """Create the inbox (template only, no entries) if it does not exist."""
    p = path(run_id)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(TEMPLATE.format(slug=slug or run_id))
    return p


def _blocks(text: str):
    """Find idea headings, ignoring any inside HTML comments (so the template's
    example entry is not parsed as a real idea)."""
    lines = text.splitlines()
    blocks = []
    in_comment = False
    for i, ln in enumerate(lines):
        allowed = not in_comment
        if "<!--" in ln:
            in_comment = True
        if "-->" in ln:
            in_comment = False
        if not allowed:
            continue
        m = HEADER.match(ln)
        if m:
            blocks.append({"start": i, "open": m.group(1) == " ",
                           "title": m.group(2).strip(), "body_start": i + 1, "end": None})
    for j, b in enumerate(blocks):
        b["end"] = blocks[j + 1]["start"] if j + 1 < len(blocks) else len(lines)
    return lines, blocks


def list_open(run_id: str) -> list[dict]:
    p = path(run_id)
    if not p.exists():
        return []
    lines, blocks = _blocks(p.read_text())
    out, n = [], 0
    for b in blocks:
        if b["open"]:
            n += 1
            body = "\n".join(lines[b["body_start"]:b["end"]]).strip()
            out.append({"id": n, "title": b["title"], "body": body})
    return out


def resolve(run_id: str, idea_id: int, outcome: str, note: str = "") -> dict:
    """Close the idea_id-th OPEN entry: flip [ ]->[x] and append a Tested annotation."""
    p = path(run_id)
    if not p.exists():
        raise FileNotFoundError(p)
    lines, blocks = _blocks(p.read_text())
    open_blocks = [b for b in blocks if b["open"]]
    if idea_id < 1 or idea_id > len(open_blocks):
        raise IndexError(f"open idea #{idea_id} not found (have {len(open_blocks)} open)")
    b = open_blocks[idea_id - 1]
    lines[b["start"]] = re.sub(r"\[([ xX])\]", "[x]", lines[b["start"]], count=1)
    stamp = time.strftime("%Y-%m-%d")
    annotation = f"\n**Tested** {stamp} — {outcome.upper()}: {note}".rstrip()
    lines.insert(b["end"], annotation)
    p.write_text("\n".join(lines) + "\n")
    return {"title": b["title"], "outcome": outcome}
