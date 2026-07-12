"""Install the Claude Code bridge into a live AI-Scientist process.

Call :func:`install` *before* running any AI-Scientist pipeline code (the
``bridge.run`` launcher and ``scripts/*`` wrappers do this for you). It swaps the
LLM/VLM/tree-search entry points for Claude-Code-backed equivalents in two ways,
so it is robust to import order:

1. Replace the functions on their *source* modules (``ai_scientist.llm`` etc.).
   Any ``from ai_scientist.llm import X`` executed afterwards picks up the new X.
2. Walk already-imported ``ai_scientist.*`` modules and repair any references
   bound by an earlier ``from ... import X``.
"""

from __future__ import annotations

import sys

_installed = False


def install(verbose: bool = True) -> None:
    global _installed
    if _installed:
        return

    from . import llm_backend, vlm_backend, treesearch_backend

    # name -> new function, grouped by the source module that defines it.
    import ai_scientist.llm as llm_mod
    import ai_scientist.vlm as vlm_mod
    import ai_scientist.treesearch.backend as backend_mod

    replacements: dict[str, object] = {}

    def _swap(mod, name, new):
        old = getattr(mod, name, None)
        if old is not None:
            replacements[id(old)] = new
        setattr(mod, name, new)

    # 1a. ai_scientist.llm
    _swap(llm_mod, "create_client", llm_backend.create_client)
    _swap(llm_mod, "get_response_from_llm", llm_backend.get_response_from_llm)
    _swap(llm_mod, "get_batch_responses_from_llm", llm_backend.get_batch_responses_from_llm)
    _swap(llm_mod, "make_llm_call", llm_backend.make_llm_call)

    # 1b. ai_scientist.vlm  (note: vlm.create_client differs from llm.create_client)
    _swap(vlm_mod, "create_client", vlm_backend.create_client)
    _swap(vlm_mod, "get_response_from_vlm", vlm_backend.get_response_from_vlm)
    _swap(vlm_mod, "get_batch_responses_from_vlm", vlm_backend.get_batch_responses_from_vlm)

    # 1c. tree-search dispatcher
    _swap(backend_mod, "query", treesearch_backend.query)

    # 2. Repair references already imported into other ai_scientist modules.
    repaired = 0
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not mod_name.startswith("ai_scientist"):
            continue
        mod_dict = getattr(mod, "__dict__", None)
        if not mod_dict:
            continue
        for attr, value in list(mod_dict.items()):
            new = replacements.get(id(value))
            if new is not None and value is not new:
                setattr(mod, attr, new)
                repaired += 1

    _installed = True
    if verbose:
        print(
            f"[bridge] Claude Code bridge installed "
            f"(patched llm/vlm/treesearch; repaired {repaired} imported refs)."
        )
