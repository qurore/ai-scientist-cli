"""Launcher: run an upstream AI-Scientist script with the Claude Code bridge active.

Usage::

    python -m bridge.run <script.py> [args...]

It makes ``ai_scientist`` importable, installs the bridge (so every LLM/VLM/
tree-search call is served by Claude Code), switches into the script's directory
so the upstream relative paths resolve, then executes the script as ``__main__``.

Environment:
    AISCI_VENDOR_DIR   path to the AI-Scientist-v2 checkout
                       (default: <repo>/vendor/AI-Scientist-v2)
    AISCI_WORKDIR      directory to run the script from
                       (default: the script's own directory)
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _vendor_dir() -> Path:
    return Path(os.environ.get("AISCI_VENDOR_DIR", REPO_ROOT / "vendor" / "AI-Scientist-v2"))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2

    script = Path(argv[0]).resolve()
    if not script.exists():
        print(f"[bridge.run] script not found: {script}", file=sys.stderr)
        return 2

    vendor = _vendor_dir().resolve()
    if not vendor.exists():
        print(f"[bridge.run] vendor dir not found: {vendor}\n"
              f"             run scripts/setup.sh first.", file=sys.stderr)
        return 2

    # Make `ai_scientist` importable and the bridge package available.
    sys.path.insert(0, str(vendor))
    sys.path.insert(0, str(REPO_ROOT))

    from bridge.install import install
    install()

    workdir = Path(os.environ.get("AISCI_WORKDIR", script.parent)).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(workdir)

    # Hand the remaining args to the target script as if invoked directly.
    sys.argv = [str(script), *argv[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
