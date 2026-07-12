"""Claude Code bridge for AI-Scientist-v2.

Routes AI-Scientist's LLM/VLM/tree-search calls through the locally installed
`claude` CLI in headless mode, so the upstream Python pipeline can run with no
external API keys - "on Claude Code only".

This bridge is the *optional programmatic adapter*. The primary way to drive
AI-Scientist in this repo is the native Claude Code Skills + Hooks layer under
``.claude/``. Use the bridge when you want to run an upstream stage unmodified
(e.g. citation gathering, the BFTS bookkeeping loop).

Typical use::

    python -m bridge.run vendor/AI-Scientist-v2/launch_scientist_bfts.py --help
"""

from .install import install  # noqa: F401

__all__ = ["install"]
