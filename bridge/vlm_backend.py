"""Drop-in replacements for ``ai_scientist.vlm`` functions, served by Claude Code.

Vision review (figures, captions, references) is handled by letting headless
Claude Code open the image files with its native ``Read`` tool. We pass the
image paths in the prompt and grant read access to their directories via
``--add-dir``; Claude reads each image and answers, no base64 plumbing needed.
"""

from __future__ import annotations

import os
from typing import Any

from . import claude_cli
from .llm_backend import ClaudeSentinelClient, _compose_user


def create_client(model: str) -> tuple[Any, str]:
    print(f"[bridge] Routing VLM model '{model}' through Claude Code (Read tool).")
    return ClaudeSentinelClient(model), model


def _vlm_complete(
    msg: str,
    image_paths,
    model: str,
    system_message: str,
    msg_history: list,
    max_images: int,
    label: str,
) -> str:
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    image_paths = [p for p in (image_paths or []) if p][:max_images]
    abs_paths = [os.path.abspath(p) for p in image_paths]

    add_dirs = sorted({os.path.dirname(p) for p in abs_paths if os.path.dirname(p)})
    listing = "\n".join(f"- {p}" for p in abs_paths)

    base_msg = _compose_user(msg_history or [], msg)
    user_text = (
        f"{base_msg}\n\n"
        f"# Images to analyze\n"
        f"Open and view each of the following image files with the Read tool, "
        f"then complete the task above strictly from what the images show:\n"
        f"{listing}"
    )

    # Allow a handful of turns so Claude can read several images before replying.
    turns = max(2, min(8, len(abs_paths) + 2))
    result = claude_cli.complete(
        user_text,
        system_message=system_message,
        model=model,
        allowed_tools=["Read"],
        add_dirs=add_dirs,
        max_turns=turns,
        label=label,
    )
    return result.text


def get_response_from_vlm(
    msg: str,
    image_paths,
    client: Any,
    model: str,
    system_message: str,
    print_debug: bool = False,
    msg_history=None,
    temperature: float = 0.7,
    max_images: int = 25,
) -> tuple[str, list[dict[str, Any]]]:
    if msg_history is None:
        msg_history = []
    content = _vlm_complete(
        msg, image_paths, model, system_message, msg_history, max_images, "vlm.get_response"
    )
    new_msg_history = msg_history + [
        {"role": "user", "content": msg},
        {"role": "assistant", "content": content},
    ]
    if print_debug:
        print("*" * 20 + " VLM (bridge) " + "*" * 20)
        print(content)
    return content, new_msg_history


def get_batch_responses_from_vlm(
    msg: str,
    image_paths,
    client: Any,
    model: str,
    system_message: str,
    print_debug: bool = False,
    msg_history=None,
    temperature: float = 0.7,
    n_responses: int = 1,
    max_images: int = 200,
) -> tuple[list[str], list[list[dict[str, Any]]]]:
    if msg_history is None:
        msg_history = []
    contents: list[str] = []
    histories: list[list[dict[str, Any]]] = []
    for _ in range(n_responses):
        c, h = get_response_from_vlm(
            msg, image_paths, client, model, system_message,
            print_debug=False, msg_history=msg_history,
            temperature=temperature, max_images=max_images,
        )
        contents.append(c)
        histories.append(h)
    return contents, histories
