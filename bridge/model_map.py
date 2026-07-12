"""Map AI-Scientist model strings to concrete Claude Code models.

AI-Scientist hard-codes model names like ``o1-preview-2024-09-12`` or
``gpt-4o-2024-11-20`` throughout its pipeline and config. Because every call is
ultimately served by Claude Code, we translate each of those names into a
Claude model on a *tier* basis (big / default / small) so cost and capability
stay sensible:

* **big**     - heavy reasoning & final writeup  -> Opus by default
* **default** - general purpose                  -> Sonnet by default
* **small**   - cheap/fast helper calls          -> Haiku by default

Override priority (highest first):
    1. ``config/model_map.json`` exact-key overrides   (model -> claude id)
    2. environment tier vars: ``AISCI_CLAUDE_MODEL_{BIG,DEFAULT,SMALL}``
    3. built-in substring -> tier table
Direct requests for ``opus`` / ``sonnet`` / ``haiku`` (or any ``claude-*`` id)
are passed straight through, so a skill can ask for a tier explicitly.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

# Concrete Claude model ids (overridable via env). Keep in sync with README.
_TIER_DEFAULTS = {
    "big": "claude-opus-4-8",
    "default": "claude-sonnet-4-6",
    "small": "claude-haiku-4-5-20251001",
}

_TIER_ENV = {
    "big": "AISCI_CLAUDE_MODEL_BIG",
    "default": "AISCI_CLAUDE_MODEL_DEFAULT",
    "small": "AISCI_CLAUDE_MODEL_SMALL",
}

# Short aliases a skill / user may request directly.
_ALIASES = {
    "opus": "big",
    "sonnet": "default",
    "haiku": "small",
    "big": "big",
    "default": "default",
    "small": "small",
}

# Substring (lowercased) -> tier. First match in iteration order wins, so the
# more specific entries are listed before their broader prefixes.
_SUBSTRING_TIERS = [
    ("o1", "big"),
    ("o3", "default"),
    ("gpt-4o-mini", "small"),
    ("gpt-4.1-mini", "small"),
    ("gpt-4o", "default"),
    ("gpt-4.1", "default"),
    ("gpt-4", "default"),
    ("claude-3-5-haiku", "small"),
    ("claude-3-haiku", "small"),
    ("claude-3-opus", "big"),
    ("claude-3-5-sonnet", "default"),
    ("claude-3-sonnet", "default"),
    ("deepseek", "default"),
    ("deepcoder", "default"),
    ("gemini-2.5-pro", "big"),
    ("gemini", "default"),
    ("llama", "default"),
    ("qwen", "default"),
]


def _tier_model(tier: str) -> str:
    env_var = _TIER_ENV.get(tier)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var].strip()
    return _TIER_DEFAULTS[tier]


@lru_cache(maxsize=1)
def _file_overrides() -> dict:
    path = Path(os.environ.get("AISCI_MODEL_MAP", "config/model_map.json"))
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("overrides", data) if isinstance(data, dict) else {}


def _is_claude_id(model: str) -> bool:
    m = model.lower()
    # A concrete next-gen Claude id (e.g. claude-opus-4-8, claude-sonnet-4-6).
    return m.startswith("claude-") and any(
        fam in m for fam in ("opus-4", "sonnet-4", "haiku-4", "fable-5")
    )


def resolve_model(model: str | None) -> str:
    """Return the concrete Claude model id to use for ``model``."""
    if not model:
        return _tier_model("default")

    key = model.strip()
    low = key.lower()

    # 1. Explicit per-model overrides from config file.
    overrides = _file_overrides()
    if key in overrides:
        return overrides[key]
    if low in overrides:
        return overrides[low]

    # 2. Direct tier alias or already-concrete Claude id -> pass through.
    if low in _ALIASES:
        return _tier_model(_ALIASES[low])
    if _is_claude_id(key):
        return key

    # 3. Substring -> tier table.
    for needle, tier in _SUBSTRING_TIERS:
        if needle in low:
            return _tier_model(tier)

    # 4. Fallback.
    return _tier_model("default")


def tier_model(tier: str) -> str:
    """Public helper: concrete Claude id for a tier ('big'|'default'|'small')."""
    return _tier_model(_ALIASES.get(tier, "default"))
