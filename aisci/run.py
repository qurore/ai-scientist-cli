"""CLI for managing AI-Scientist study projects.

Each project is a self-contained study under ``projects/<id>/``.

    python -m aisci.run new   --slug my_study --topic "research topic" [--rubric aamas-agentic]
    python -m aisci.run show  [--run <id>]
    python -m aisci.run set   --stage experiment --status done [--idea-slug foo] [--rubric <name>] [--run <id>]
    python -m aisci.run rubrics
    python -m aisci.run list
"""

from __future__ import annotations

import argparse
import json
import sys

from . import state


def _resolve(run_id: str | None) -> str:
    rid = run_id or state.current_run()
    if not rid:
        print("no run specified and no current run set", file=sys.stderr)
        raise SystemExit(2)
    return rid


def cmd_new(args) -> int:
    try:
        rid = state.new_run(args.slug, args.topic or "", rubric=args.rubric)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    print(rid)
    return 0


def cmd_show(args) -> int:
    rid = _resolve(args.run)
    print(json.dumps(state.load_state(rid), indent=2))
    return 0


def cmd_set(args) -> int:
    rid = _resolve(args.run)
    st = state.load_state(rid)
    if args.stage:
        st["stage"] = args.stage
    if args.status:
        st["status"] = args.status
    if args.idea_slug:
        st["idea_slug"] = args.idea_slug
    if args.rubric:
        try:
            st["rubric"] = state._check_rubric(args.rubric)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
    if args.complete:
        st["status"] = "complete"
    state.save_state(rid, st)
    if args.note:
        state.append_study_log(rid, args.note)
    print(json.dumps(st, indent=2))
    return 0


def cmd_decide(args) -> int:
    """Append one major decision to the project's append-only decision log.

    decisions.jsonl is the human-readable audit trail of *why* the study turned
    out the way it did — the trail from idea to the produced artifact.
    """
    rid = _resolve(args.run)
    st = state.load_state(rid)
    stage = args.stage or st.get("stage", "ideate")
    entry = {
        "ts": state._stamp(),
        "stage": stage,
        "decision": args.decision,
        "why": args.why,
        "alternatives": [a.strip() for a in (args.alternatives or "").split(";") if a.strip()],
        "evidence": args.evidence or "",
    }
    path = state.project_dir(rid) / "decisions.jsonl"
    with path.open("a") as f:  # append-only
        f.write(json.dumps(entry) + "\n")
    state.append_study_log(rid, f"DECISION [{stage}]: {args.decision} — why: {args.why}")
    print(json.dumps(entry))
    return 0


def cmd_ideas(args) -> int:
    """List OPEN human-written ideas in the project inbox (human_ideas.md)."""
    rid = _resolve(args.run)
    from . import ideas
    ideas.ensure(rid)
    items = ideas.list_open(rid)
    print(json.dumps({"open_ideas": items, "count": len(items)}, indent=2))
    return 0


def cmd_idea_resolve(args) -> int:
    """Close a human idea with an outcome so it is not re-read in later loops."""
    rid = _resolve(args.run)
    from . import ideas
    res = ideas.resolve(rid, args.id, args.outcome, args.note or "")
    state.append_study_log(rid, f"HUMAN IDEA [{args.outcome}]: {res['title']} — {args.note or ''}")
    print(json.dumps(res))
    return 0


def cmd_lit(args) -> int:
    """Append one structured literature-refresh entry to the project's survey log
    (literature.md), shared across all improvement-loop iterations."""
    rid = _resolve(args.run)
    from . import literature
    res = literature.append(rid, args.context or "refresh", args.queries or "",
                            args.found or "", args.verdict or "", args.impact or "")
    state.append_study_log(rid, f"LIT REFRESH [{args.context or 'refresh'}]: {args.verdict or ''}")
    print(json.dumps(res))
    return 0


def cmd_rubrics(args) -> int:
    """List the review rubrics available in the registry (config/rubrics/)."""
    names = state.list_rubrics()
    if not names:
        print("no rubrics found in config/rubrics/", file=sys.stderr)
        return 1
    for n in names:
        title = ""
        for line in state.rubric_path(n).read_text().splitlines():
            if line.startswith("#"):
                title = line.lstrip("# ").strip()
                break
        mark = " (default)" if n == state.DEFAULT_RUBRIC else ""
        label = title if title.startswith(n) else f"{n} — {title}"
        print(f"{label}{mark}")
    return 0


def cmd_list(args) -> int:
    if not state.RUNS.exists():
        return 0
    for d in sorted(state.RUNS.iterdir()):
        sp = d / "state.json"
        if sp.exists():
            st = json.loads(sp.read_text())
            cur = " *" if st["run_id"] == state.current_run() else "  "
            print(f"{cur} {st['run_id']:40s} stage={st['stage']:10s} status={st['status']}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="aisci.run")
    sub = p.add_subparsers(dest="cmd", required=True)

    pn = sub.add_parser("new")
    pn.add_argument("--slug", required=True)
    pn.add_argument("--topic", default="")
    pn.add_argument("--rubric", default=None,
                    help="review rubric from config/rubrics/ (default: %s)" % state.DEFAULT_RUBRIC)
    pn.set_defaults(func=cmd_new)

    ps = sub.add_parser("show")
    ps.add_argument("--run", default=None)
    ps.set_defaults(func=cmd_show)

    pset = sub.add_parser("set")
    pset.add_argument("--run", default=None)
    pset.add_argument("--stage", choices=state.STAGES, default=None)
    pset.add_argument("--status", default=None)
    pset.add_argument("--idea-slug", dest="idea_slug", default=None)
    pset.add_argument("--rubric", default=None,
                      help="review rubric from config/rubrics/")
    pset.add_argument("--complete", action="store_true")
    pset.add_argument("--note", default=None)
    pset.set_defaults(func=cmd_set)

    pd = sub.add_parser("decide", help="append a major decision to the project's audit log")
    pd.add_argument("--run", default=None)
    pd.add_argument("--decision", required=True, help="what was decided")
    pd.add_argument("--why", required=True, help="the rationale")
    pd.add_argument("--stage", choices=state.STAGES, default=None)
    pd.add_argument("--alternatives", default=None, help="semicolon-separated options not taken")
    pd.add_argument("--evidence", default=None, help="pointer to supporting result/file")
    pd.set_defaults(func=cmd_decide)

    pi = sub.add_parser("ideas", help="list OPEN human ideas in the project inbox")
    pi.add_argument("--run", default=None)
    pi.set_defaults(func=cmd_ideas)

    pir = sub.add_parser("idea-resolve", help="close a human idea with an outcome")
    pir.add_argument("--run", default=None)
    pir.add_argument("--id", type=int, required=True)
    pir.add_argument("--outcome", required=True,
                     choices=["confirmed", "refuted", "inconclusive"])
    pir.add_argument("--note", default=None)
    pir.set_defaults(func=cmd_idea_resolve)

    plit = sub.add_parser("lit", help="append a literature-refresh entry to the project survey log")
    plit.add_argument("--run", default=None)
    plit.add_argument("--context", default=None, help='e.g. "iter 3 refresh" or "ideation"')
    plit.add_argument("--queries", default=None, help="what was searched (terms/ids/citation hops)")
    plit.add_argument("--found", default=None, help="key papers found: Title (arXiv id) — relevance")
    plit.add_argument("--verdict", default=None,
                      help="nothing-new | scooped | replicate-extend [cite] | contradicted | novel-confirmed")
    plit.add_argument("--impact", default=None, help="how it changed the plan/claims/citations")
    plit.set_defaults(func=cmd_lit)

    pr = sub.add_parser("rubrics", help="list available review rubrics (config/rubrics/)")
    pr.set_defaults(func=cmd_rubrics)

    pl = sub.add_parser("list")
    pl.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
