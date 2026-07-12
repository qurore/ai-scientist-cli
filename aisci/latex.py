"""Compile a LaTeX paper to PDF (pdflatex -> bibtex -> pdflatex x2).

    python -m aisci.latex <latex-dir> <main.tex>

Prints a JSON summary {ok, pdf, errors[], log}. Captures the full log to
``<latex-dir>/compile.log``. Surfaces the first few LaTeX errors so the calling
skill can fix them without reading the whole log.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


def _run(cmd, cwd) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=300)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "[aisci.latex] TIMEOUT"
    except FileNotFoundError:
        return 127, f"[aisci.latex] command not found: {cmd[0]}"


def _extract_errors(log: str) -> list[str]:
    errs = []
    for m in re.finditer(r"^! (.+)$", log, re.MULTILINE):
        errs.append(m.group(1).strip())
    # Undefined references / citations are warnings but worth surfacing.
    for m in re.finditer(r"(Citation `[^']+' undefined|Reference `[^']+' undefined|Undefined control sequence)", log):
        errs.append(m.group(1))
    seen, uniq = set(), []
    for e in errs:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq[:15]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="aisci.latex")
    p.add_argument("latex_dir")
    p.add_argument("main_tex", help="e.g. paper.tex")
    args = p.parse_args(argv)

    d = Path(args.latex_dir).resolve()
    stem = Path(args.main_tex).stem
    if not (d / args.main_tex).exists():
        print(json.dumps({"ok": False, "errors": [f"{args.main_tex} not found in {d}"]}))
        return 2

    if shutil.which("pdflatex") is None:
        print(json.dumps({
            "ok": False,
            "errors": ["pdflatex not installed — install MacTeX/BasicTeX (see scripts/doctor.sh)"],
        }))
        return 2

    pdflatex = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", args.main_tex]
    full_log = []
    for step in (pdflatex, ["bibtex", stem], pdflatex, pdflatex):
        rc, out = _run(step, d)
        full_log.append(f"$ {' '.join(step)}  (rc={rc})\n{out}")

    log_text = "\n\n".join(full_log)
    (d / "compile.log").write_text(log_text)

    pdf = d / f"{stem}.pdf"
    errors = _extract_errors(log_text)
    ok = pdf.exists() and not any(e for e in errors if "undefined" not in e.lower())

    print(json.dumps({
        "ok": ok,
        "pdf": str(pdf) if pdf.exists() else None,
        "errors": errors,
        "log": str(d / "compile.log"),
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
