"""Replacement for ``ai_scientist.treesearch.backend.query`` served by Claude Code.

The tree-search experiment agent calls a single ``query()`` dispatcher. When a
``func_spec`` (function-calling spec) is supplied it expects a structured dict
back; we satisfy that with Claude Code's ``--json-schema`` structured output.
Otherwise it expects a plain string completion.
"""

from __future__ import annotations

import json

from . import claude_cli


def _coerce_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    # compile_prompt_to_md can return a list/dict for multi-modal prompts.
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Fallback: pull the first ```json ... ``` or {...} block.
    import re

    for pattern in (r"```json(.*?)```", r"```(.*?)```", r"\{.*\}"):
        for match in re.findall(pattern, text, re.DOTALL):
            try:
                obj = json.loads(match.strip())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse structured output from Claude: {text[:500]!r}")


def query(
    system_message=None,
    user_message=None,
    model=None,
    temperature=None,
    max_tokens=None,
    func_spec=None,
    **model_kwargs,
):
    # Prompts arrive uncompiled (dict/list/str); compile them as upstream does.
    from ai_scientist.treesearch.backend.utils import compile_prompt_to_md

    model = model or model_kwargs.get("model")

    sys_md = compile_prompt_to_md(system_message) if system_message is not None else None
    user_md = compile_prompt_to_md(user_message) if user_message is not None else None

    sys_text = _coerce_text(sys_md)
    user_text = _coerce_text(user_md) or ""

    json_schema = None
    if func_spec is not None:
        json_schema = getattr(func_spec, "json_schema", None)
        # Nudge the model toward the function's intent in the system prompt.
        intent = getattr(func_spec, "description", "") or ""
        if intent:
            sys_text = (sys_text + "\n\n" if sys_text else "") + (
                f"Respond by producing the structured output for: {intent}"
            )

    result = claude_cli.complete(
        user_text,
        system_message=sys_text,
        model=model,
        json_schema=json_schema,
        label="treesearch.query",
    )

    if func_spec is not None:
        return _extract_json(result.text)
    return result.text
