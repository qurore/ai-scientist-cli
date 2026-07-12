"""Drop-in replacements for ``ai_scientist.llm`` functions, served by Claude Code.

These mirror the signatures and return contracts of the upstream functions so
that the unmodified AI-Scientist pipeline (ideation, writeup, review, plotting,
log-summarization) works without any code edits once :func:`bridge.install`
swaps them in.
"""

from __future__ import annotations

from typing import Any

from . import claude_cli


class ClaudeSentinelClient:
    """Stand-in for an ``anthropic.Anthropic`` / ``openai.OpenAI`` client.

    The real network client is never needed because every completion is served
    by :mod:`bridge.claude_cli`. We keep a tiny object so that code which only
    passes the client around keeps working; any *direct* use of a network
    method raises loudly so we can spot an un-bridged call path.
    """

    def __init__(self, model: str):
        self.model = model

    def __getattr__(self, item):  # pragma: no cover - defensive
        raise AttributeError(
            f"ClaudeSentinelClient has no '{item}'. An LLM call bypassed the "
            f"Claude Code bridge - it should go through get_response_from_llm()."
        )


def create_client(model) -> tuple[Any, str]:
    print(f"[bridge] Routing model '{model}' through Claude Code (headless).")
    return ClaudeSentinelClient(model), model


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", block.get("content", "")))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return content.get("text", content.get("content", str(content)))
    return str(content)


def _compose_user(msg_history: list, prompt: str) -> str:
    """Flatten prior turns + the new prompt into a single text message.

    `claude -p` takes one user message, so multi-turn context (used by the
    reflection loops) is rendered as a transcript prefix.
    """
    if not msg_history:
        return prompt
    lines = []
    for turn in msg_history:
        role = turn.get("role", "user") if isinstance(turn, dict) else "user"
        text = _content_to_text(turn.get("content", "") if isinstance(turn, dict) else turn)
        if not text:
            continue
        header = "Assistant" if role == "assistant" else "User"
        lines.append(f"## Previous {header} message\n{text}")
    lines.append(f"## New User message\n{prompt}")
    return "\n\n".join(lines)


def get_response_from_llm(
    prompt,
    client,
    model,
    system_message,
    print_debug=False,
    msg_history=None,
    temperature=0.7,
) -> tuple[str, list[dict[str, Any]]]:
    if msg_history is None:
        msg_history = []

    user_text = _compose_user(msg_history, prompt)
    result = claude_cli.complete(
        user_text,
        system_message=system_message,
        model=model,
        label="llm.get_response",
    )
    content = result.text

    new_msg_history = msg_history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": content},
    ]

    if print_debug:
        print()
        print("*" * 20 + " LLM START " + "*" * 20)
        for j, m in enumerate(new_msg_history):
            print(f'{j}, {m["role"]}: {m["content"]}')
        print(content)
        print("*" * 21 + " LLM END " + "*" * 21)
        print()

    return content, new_msg_history


def get_batch_responses_from_llm(
    prompt,
    client,
    model,
    system_message,
    print_debug=False,
    msg_history=None,
    temperature=0.7,
    n_responses=1,
) -> tuple[list[str], list[list[dict[str, Any]]]]:
    contents: list[str] = []
    histories: list[list[dict[str, Any]]] = []
    for _ in range(n_responses):
        c, h = get_response_from_llm(
            prompt,
            client,
            model,
            system_message,
            print_debug=False,
            msg_history=msg_history,
            temperature=temperature,
        )
        contents.append(c)
        histories.append(h)

    if print_debug and histories:
        print()
        print("*" * 20 + " LLM START " + "*" * 20)
        for j, m in enumerate(histories[0]):
            print(f'{j}, {m["role"]}: {m["content"]}')
        print(contents)
        print("*" * 21 + " LLM END " + "*" * 21)
        print()

    return contents, histories


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str):
        self.message = _Message(content)


class _OpenAILikeResponse:
    """Minimal shim for callers that read ``resp.choices[0].message.content``."""

    def __init__(self, content: str):
        self.choices = [_Choice(content)]


def make_llm_call(client, model, temperature, system_message, prompt):
    # `prompt` here is an OpenAI-style message list; flatten to text.
    user_text = _compose_user(prompt[:-1] if prompt else [], prompt[-1]["content"] if prompt else "")
    result = claude_cli.complete(
        user_text,
        system_message=system_message,
        model=model,
        label="llm.make_llm_call",
    )
    return _OpenAILikeResponse(result.text)
