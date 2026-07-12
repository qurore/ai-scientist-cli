"""Low-level bridge to the Claude Code CLI (`claude -p`) in headless mode.

This is the single choke point through which *every* AI-Scientist LLM call is
served. Instead of hitting the OpenAI / Anthropic HTTP APIs (which need API
keys), we shell out to the locally installed `claude` binary in
print/headless mode. That uses the user's existing Claude Code login, so the
whole AI-Scientist pipeline runs "on Claude Code only" with no extra keys.

Design notes
------------
* The *system message* is written to a temp file and passed with
  ``--system-prompt-file`` so arbitrarily large prompts never hit argv limits.
* The *user message* is fed on **stdin** for the same reason.
* ``--exclude-dynamic-system-prompt-sections`` strips Claude Code's own agentic
  system sections so the call behaves like a plain completion driven solely by
  AI-Scientist's system message.
* Tools are disabled by default (pure text generation). Callers that genuinely
  need a tool (e.g. the VLM reviewer reading image files) opt in via
  ``allowed_tools``.
* Every call is appended to a JSONL log so the token-tracker hook can report
  cost/usage.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .model_map import resolve_model

# Tools we explicitly block when the caller wants a pure text completion.
_ALL_TOOLS = [
    "Bash", "Edit", "Write", "Read", "Glob", "Grep", "WebFetch", "WebSearch",
    "NotebookEdit", "Task", "TodoWrite", "BashOutput", "KillShell",
    "SlashCommand", "MultiEdit",
]


def _cache_dir() -> Path:
    d = Path(os.environ.get("AISCI_CACHE_DIR", ".aisci_cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bin() -> str:
    return os.environ.get("AISCI_CLAUDE_BIN", "claude")


def _default_timeout() -> int:
    return int(os.environ.get("AISCI_CLAUDE_TIMEOUT", "1200"))


def _max_retries() -> int:
    return int(os.environ.get("AISCI_CLAUDE_MAX_RETRIES", "4"))


@dataclass
class ClaudeResult:
    """Parsed result of a single `claude -p` invocation."""

    text: str
    model: str
    in_tokens: int = 0
    out_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    session_id: str = ""
    raw: dict = field(default_factory=dict)


def _tool_flags(allowed_tools: Sequence[str] | None) -> list[str]:
    if allowed_tools:
        return ["--allowedTools", *allowed_tools]
    # No tools requested -> block the whole toolset for a clean completion.
    return ["--disallowedTools", *_ALL_TOOLS]


def _log_call(result: ClaudeResult, label: str) -> None:
    try:
        rec = {
            "ts": time.time(),
            "label": label,
            "model": result.model,
            "in_tokens": result.in_tokens,
            "out_tokens": result.out_tokens,
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "session_id": result.session_id,
        }
        with open(_cache_dir() / "bridge_calls.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        # Logging must never break a pipeline run.
        pass


def complete(
    user_message: str,
    system_message: str | None = None,
    model: str | None = None,
    *,
    json_schema: dict | None = None,
    allowed_tools: Sequence[str] | None = None,
    add_dirs: Sequence[str] | None = None,
    max_turns: int = 1,
    label: str = "llm",
    timeout: int | None = None,
    extra_args: Sequence[str] | None = None,
) -> ClaudeResult:
    """Run one headless Claude Code completion and return the parsed result.

    Parameters mirror a typical chat-completion call. ``model`` may be any
    AI-Scientist model string (e.g. ``"o1-preview-2024-09-12"``); it is mapped
    to a concrete Claude model via :mod:`bridge.model_map`.
    """
    claude_model = resolve_model(model)
    timeout = timeout or _default_timeout()

    base_args = [
        _bin(),
        "-p",
        "--output-format", "json",
        "--model", claude_model,
        "--exclude-dynamic-system-prompt-sections",
        "--max-turns", str(max_turns),
        # Keep these headless runs hermetic: do not pick up the surrounding
        # project's CLAUDE.md / settings, which would bias the completion.
        "--setting-sources", "",
    ]
    base_args += _tool_flags(allowed_tools)
    for d in (add_dirs or []):
        base_args += ["--add-dir", str(d)]
    if json_schema is not None:
        base_args += ["--json-schema", json.dumps(json_schema)]
    if extra_args:
        base_args += list(extra_args)

    # System prompt via temp file to dodge argv length limits.
    sys_file: str | None = None
    if system_message:
        fd, sys_file = tempfile.mkstemp(prefix="aisci_sys_", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(system_message)
        base_args += ["--system-prompt-file", sys_file]

    last_err: Exception | None = None
    try:
        for attempt in range(_max_retries() + 1):
            t0 = time.time()
            try:
                proc = subprocess.run(
                    base_args,
                    input=user_message,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as e:
                last_err = e
                _backoff(attempt)
                continue

            if proc.returncode != 0:
                last_err = RuntimeError(
                    f"claude exited {proc.returncode}: {proc.stderr[-2000:]}"
                )
                _backoff(attempt)
                continue

            result = _parse_output(proc.stdout, claude_model)
            if result is None:
                last_err = RuntimeError(
                    f"could not parse claude output: {proc.stdout[:2000]!r}"
                )
                _backoff(attempt)
                continue

            result.duration_ms = (time.time() - t0) * 1000.0
            _log_call(result, label)
            return result
    finally:
        if sys_file and os.path.exists(sys_file):
            os.unlink(sys_file)

    raise RuntimeError(f"claude completion failed after retries: {last_err}")


def _backoff(attempt: int) -> None:
    # Exponential backoff capped at 30s; jitter-free for reproducibility.
    delay = min(30.0, 1.5 ** attempt)
    time.sleep(delay)


def _parse_output(stdout: str, model: str) -> ClaudeResult | None:
    stdout = stdout.strip()
    if not stdout:
        return None
    try:
        env = json.loads(stdout)
    except json.JSONDecodeError:
        # Fallback: last non-empty line might be the JSON envelope.
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                env = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        else:
            return None

    if env.get("is_error"):
        return None

    text = env.get("result", "")
    if isinstance(text, (dict, list)):
        # Structured output: hand back the JSON object as text; callers that
        # asked for a schema will json.loads it again.
        text = json.dumps(text)

    usage = env.get("usage", {}) or {}
    return ClaudeResult(
        text=text if isinstance(text, str) else str(text),
        model=model,
        in_tokens=int(usage.get("input_tokens", 0) or 0),
        out_tokens=int(usage.get("output_tokens", 0) or 0),
        cost_usd=float(env.get("total_cost_usd", 0.0) or 0.0),
        session_id=str(env.get("session_id", "")),
        raw=env,
    )
