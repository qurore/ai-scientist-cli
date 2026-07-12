"""aisci — small helpers that the AI-Scientist Claude Code skills shell out to.

These are deliberately thin: the *intelligence* lives in the skills (i.e. in you,
the Claude Code agent). These modules just do the mechanical bookkeeping —
creating project directories, executing experiment scripts with capture/timeout,
and compiling LaTeX — so the workflow is reproducible and resumable.

Run them as modules from the repo root, e.g.::

    .venv/bin/python -m aisci.run new --slug my_study --topic "..."
    .venv/bin/python -m aisci.exec projects/<id> code/n1.py --timeout 1800
    .venv/bin/python -m aisci.latex projects/<id>/writeup/latex paper.tex
"""

__all__ = ["state", "run", "exec", "latex"]
