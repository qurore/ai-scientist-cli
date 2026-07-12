"""Shared state / project-directory helpers for the AI-Scientist skills.

A *project* is one self-contained study: everything it produces (idea, code,
logs, results, plots, paper, review, lab notebook) lives under its own folder
``projects/<id>/``. Projects are gitignored by default (see .gitignore) so the
integration layer can be pushed to a public remote without shipping your
studies; un-ignore them to version your projects in a private repo.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROJECTS = REPO / "projects"
CACHE = REPO / ".aisci_cache"

STAGES = ["ideate", "experiment", "writeup", "review"]

RUBRICS = REPO / "config" / "rubrics"
DEFAULT_RUBRIC = "neurips-ml"


def list_rubrics() -> list[str]:
    """Names of the review rubrics available in the registry (config/rubrics/)."""
    if not RUBRICS.exists():
        return []
    return sorted(p.stem for p in RUBRICS.glob("*.md") if p.name != "README.md")


def rubric_path(name: str) -> Path:
    return RUBRICS / f"{name}.md"


def _check_rubric(name: str) -> str:
    if name not in list_rubrics():
        avail = ", ".join(list_rubrics()) or "(none — is config/rubrics/ present?)"
        raise ValueError(f"unknown rubric {name!r}; available: {avail}")
    return name


def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return (text or "study")[:48]


def project_dir(project_id: str) -> Path:
    return PROJECTS / project_id


def state_path(project_id: str) -> Path:
    return project_dir(project_id) / "state.json"


def load_state(project_id: str) -> dict:
    p = state_path(project_id)
    if not p.exists():
        raise FileNotFoundError(f"no state.json for project {project_id!r} ({p})")
    return json.loads(p.read_text())


def save_state(project_id: str, state: dict) -> None:
    state["updated"] = _stamp()
    state_path(project_id).write_text(json.dumps(state, indent=2))


def set_current(project_id: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "current_run").write_text(project_id)


def current_project() -> str | None:
    p = CACHE / "current_run"
    if p.exists():
        pid = p.read_text().strip()
        if pid and project_dir(pid).exists():
            return pid
    return None


def _unique_id(slug: str) -> str:
    """A clean, human-friendly project folder name (the slug), with a numeric
    suffix on collision so each project stays in its own folder."""
    pid = slug
    n = 2
    while project_dir(pid).exists():
        pid = f"{slug}-{n}"
        n += 1
    return pid


def new_project(slug: str, topic: str = "", rubric: str | None = None) -> str:
    rubric = _check_rubric(rubric or DEFAULT_RUBRIC)
    slug = slugify(slug)
    project_id = _unique_id(slug)
    d = project_dir(project_id)
    for sub in ("experiment/code", "experiment/logs",
                "experiment/experiment_results", "experiment/plots",
                "writeup"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": project_id,
        "slug": slug,
        "topic": topic,
        "stage": "ideate",
        "status": "pending",
        "rubric": rubric,
        "idea_slug": None,
        "created": _stamp(),
        "updated": _stamp(),
    }
    save_state(project_id, state)
    (d / "study.md").write_text(
        f"# Project: {slug}\n\n- **Project id:** {project_id}\n- **Topic:** {topic}\n"
        f"- **Review rubric:** {rubric}\n\n"
        f"## Log\n\n- {_stamp()} — project created (stage: ideate)\n"
    )
    from . import ideas, literature  # local import avoids a circular import at module load
    ideas.ensure(project_id, slug)
    literature.ensure(project_id, slug)
    set_current(project_id)
    return project_id


def append_study_log(project_id: str, line: str) -> None:
    p = project_dir(project_id) / "study.md"
    with p.open("a") as f:
        f.write(f"- {_stamp()} — {line}\n")


# ── Back-compat aliases (older code/skills used "run" terminology) ──────────
RUNS = PROJECTS
run_dir = project_dir
new_run = new_project
current_run = current_project
