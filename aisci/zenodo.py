"""Deposit a finalized project's paper to Zenodo and (optionally) publish for a DOI.

The only secret is a Zenodo personal access token, read from the environment
(``ZENODO_TOKEN`` for production, ``ZENODO_SANDBOX_TOKEN`` for sandbox) — never
stored in the repo. Author/ORCID/license metadata also come from the environment
(see ``.env.example``). Defaults are deliberately safe:

  * SANDBOX unless ``--production`` (test there first; published DOIs are PERMANENT),
  * DRAFT unless ``--publish`` (so a human can review the deposition in the browser),
  * production publish refuses unless the project's review Decision is ``Accept``
    (override with ``--force``).

    python -m aisci.zenodo deposit projects/<id> [--production] [--publish] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import state

PROD_API = "https://zenodo.org/api"
SANDBOX_API = "https://sandbox.zenodo.org/api"
REPO_URL = "https://github.com/qurore/ai-scientist-cli"

AI_DISCLOSURE = (
    "This manuscript was generated autonomously by the AI Scientist running inside "
    "Claude Code (Anthropic); every reported number traces to the project's experiment "
    "outputs. It is deposited by the named curator, who takes responsibility for its "
    "release."
)


def _load_dotenv() -> None:
    """Populate os.environ from the repo .env for any missing keys. Robust to values
    that contain spaces/commas/quotes (so `source .env` quirks don't bite). Never
    overrides a value already set in the real environment."""
    p = state.REPO / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _token(production: bool) -> str:
    env = "ZENODO_TOKEN" if production else "ZENODO_SANDBOX_TOKEN"
    tok = os.environ.get(env, "").strip()
    if not tok:
        raise SystemExit(
            f"Missing {env} in the environment. Put it in .env (gitignored) and "
            f"`source .env`, then retry. See .env.example.")
    return tok


def _api(method: str, url: str, token: str, json_body=None, raw=None, content_type=None):
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        data = raw
        headers["Content-Type"] = content_type or "application/octet-stream"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            msg = json.loads(body)
        except Exception:
            msg = body
        # never echo the token; surface Zenodo's own error
        raise SystemExit(f"Zenodo API {e.code} on {method} {url.split('?')[0]}: {msg}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Zenodo network error on {method} {url.split('?')[0]}: {e.reason}")


def _chosen_idea(run_id: str) -> dict:
    p = state.project_dir(run_id) / "idea.json"
    if not p.exists():
        return {}
    try:
        ideas = json.loads(p.read_text())
    except Exception:
        return {}
    if not isinstance(ideas, list) or not ideas:
        return {}
    slug = state.load_state(run_id).get("idea_slug")
    for it in ideas:
        if it.get("Name") == slug:
            return it
    return ideas[0]


def _paper_title(run_id: str):
    """The FINAL paper title from writeup/latex/paper.tex (source of truth), cleaned."""
    import re
    p = state.project_dir(run_id) / "writeup" / "latex" / "paper.tex"
    if not p.exists():
        return None
    m = re.search(r"\\title\{(.+?)\}", p.read_text(), re.DOTALL)
    if not m:
        return None
    t = m.group(1)
    t = t.replace("\\bfseries", "").replace("\\\\", " ")
    t = t.replace("$", "")   # drop LaTeX math delimiters: "$n$-gram" -> "n-gram"
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _summary(run_id: str) -> dict:
    p = state.project_dir(run_id) / "experiment" / "experiment_results" / "summary.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def build_metadata(run_id: str, publication_type: str = "preprint"):
    st = state.load_state(run_id)
    idea = _chosen_idea(run_id)
    summ = _summary(run_id)
    # Title/abstract from the FINAL artifacts (paper + updated summary), not the
    # original idea (which may predate revisions in the improvement loop).
    title = _paper_title(run_id) or idea.get("Title") or st.get("topic") or run_id
    abstract = "  ".join(x for x in (summ.get("question"), summ.get("overall_conclusion")) if x).strip()
    if not abstract:
        abstract = (idea.get("Abstract") or "").strip()
    desc = abstract + ("<br><br>" if abstract else "") + AI_DISCLOSURE + \
        f'<br><br>Source &amp; method: <a href="{REPO_URL}">{REPO_URL}</a>'

    creators = []
    name = os.environ.get("ZENODO_AUTHOR_NAME", "").strip()
    if name:
        c = {"name": name}
        orcid = os.environ.get("ORCID_ID", "").strip()
        aff = os.environ.get("ZENODO_AUTHOR_AFFILIATION", "").strip()
        if orcid:
            c["orcid"] = orcid
        if aff:
            c["affiliation"] = aff
        creators.append(c)
    # The human curator is the sole author/creator (AI systems cannot take authorship);
    # AI generation is disclosed in the description and notes instead. Fall back to the
    # AI name only if no human is configured.
    if not creators:
        creators.append({"name": "AI Scientist (Claude Code)"})

    stop = {"does", "the", "and", "when", "win", "across", "study", "predict", "right",
            "with", "study", "help", "from", "into", "their", "that", "this", "schedule?",
            "will", "grok?", "early", "cheap", "prediction", "delayed"}
    # Strip LaTeX math/commands ($...$, braces, backslashes) so a math-in-title
    # word like "$n$-gram" becomes the clean keyword "n-gram" on the permanent record.
    words = [re.sub(r"[${}\\]", "", w.strip(",:.?").lower()) for w in title.split()]
    kws = [w for w in dict.fromkeys(words) if len(w) > 4 and w not in stop][:5]
    # Study-specific keywords if the project supplies them (summary.json / idea.json);
    # otherwise just a generic tag. Never hard-code one study's topic here -- that leaks
    # the wrong keywords onto every other study's permanent record.
    extra = summ.get("keywords") or idea.get("Keywords") or idea.get("keywords") or []
    if isinstance(extra, str):
        extra = [k.strip() for k in extra.split(",") if k.strip()]
    for k in list(extra) + ["machine learning"]:
        if k and k not in kws:
            kws.append(k)

    meta = {
        "upload_type": "publication",
        "publication_type": publication_type,
        "title": title,
        "creators": creators,
        "description": desc,
        "access_right": "open",
        "license": os.environ.get("ZENODO_DEFAULT_LICENSE", "cc-by-4.0"),
        "keywords": kws,
        "related_identifiers": [
            {"relation": "isDerivedFrom", "identifier": REPO_URL, "scheme": "url"},
        ],
        "notes": AI_DISCLOSURE,
    }
    return meta, title


def _build_bundle(run_id: str) -> Path:
    """Zip this study's code + data + provenance for archiving alongside the paper:
    experiment code/results/figures, the paper source, and idea/decisions/reviews.
    Excludes logs, caches, and compiled LaTeX aux files. Returns the temp zip path."""
    pdir = state.project_dir(run_id)
    slug = state.load_state(run_id).get("slug", run_id)
    out = Path(tempfile.mkdtemp()) / f"{slug}_code_and_data.zip"
    inc_dirs = ["experiment/code", "experiment/experiment_results", "experiment/plots",
                "writeup/figures", "reviews"]
    inc_files = ["experiment/journal.jsonl", "idea.json", "idea.md", "topic.md",
                 "decisions.jsonl", "study.md", "state.json"]
    inc_globs = ["writeup/latex/*.tex", "writeup/latex/*.bib", "writeup/latex/*.sty",
                 "writeup/latex/*.bst", "writeup/latex/*.tex"]
    bad_suffix = {".aux", ".log", ".out", ".bbl", ".blg", ".gz", ".pyc", ".fls", ".fdb_latexmk"}
    readme = (
        f"# {slug} -- code and data\n\n"
        f"Reproducibility bundle for the paper in this Zenodo record.\n"
        f"Produced with the AI Scientist pipeline (Claude Code): {REPO_URL}\n\n"
        f"- experiment/code/ : all experiment scripts (lib.py, e1..e7, plotting)\n"
        f"- experiment/experiment_results/ : metrics -- summary.json + per-experiment detail "
        f"JSON; every number in the paper traces here\n"
        f"- experiment/plots/, writeup/figures/ : figures\n"
        f"- writeup/latex/ : paper source (paper.tex, references.bib, styles)\n"
        f"- idea.json, topic.md, decisions.jsonl, reviews/ : provenance, decision log, "
        f"and the review/score history\n\n"
        f"Datasets: any real datasets used are fetched by the code from their standard sources "
        f"(not redistributed here); all synthetic data are generated by the code. See the scripts "
        f"in experiment/code/ for exactly what each run uses.\n"
    )

    def ok(p: Path) -> bool:
        return p.is_file() and p.suffix not in bad_suffix and "__pycache__" not in p.parts

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{slug}/README.md", readme)
        seen = set()

        def add(p: Path):
            if ok(p) and p not in seen:
                seen.add(p)
                z.write(p, arcname=f"{slug}/{p.relative_to(pdir)}")

        for d in inc_dirs:
            base = pdir / d
            if base.exists():
                for p in base.rglob("*"):
                    add(p)
        for f in inc_files:
            add(pdir / f)
        for g in inc_globs:
            for p in pdir.glob(g):
                add(p)
    return out


def deposit(run_id: str, production=False, publish=False, publication_type="preprint",
            force=False, dry_run=False, with_code_data=True, new_version=False) -> dict:
    _load_dotenv()
    pdir = state.project_dir(run_id)
    pdf = pdir / "writeup" / "paper.pdf"
    if not pdf.exists():
        raise SystemExit(f"No paper at {pdf}. Run the writeup stage first.")
    st = state.load_state(run_id)
    if st.get("status") != "complete":
        print(f"[warn] project status is {st.get('status')!r}, not 'complete'.", file=sys.stderr)

    meta, title = build_metadata(run_id, publication_type)

    if dry_run:
        print(json.dumps({"dry_run": True,
                          "environment": "production" if production else "sandbox",
                          "would_publish": publish, "pdf": str(pdf), "metadata": meta}, indent=2))
        return {"dry_run": True}

    if publish and production and not force:
        review = {}
        rp = pdir / "review.json"
        if rp.exists():
            try:
                review = json.loads(rp.read_text())
            except Exception:
                review = {}
        if review.get("Decision") != "Accept":
            raise SystemExit(
                "Refusing to PUBLISH to production: review Decision is not 'Accept' "
                f"(got {review.get('Decision')!r}). Re-run with --force to override.")

    base = PROD_API if production else SANDBOX_API
    token = _token(production)

    if new_version:
        prev = {}
        zp = pdir / "zenodo.json"
        if zp.exists():
            try:
                prev = json.loads(zp.read_text())
            except Exception:
                prev = {}
        env = "production" if production else "sandbox"
        prev_id = prev.get("deposition_id")
        if not prev_id or prev.get("environment") != env:
            raise SystemExit(f"--new-version needs a prior {env} deposit in zenodo.json; none found.")
        _, nv = _api("POST", f"{base}/deposit/depositions/{prev_id}/actions/newversion", token)
        draft_api = (nv.get("links", {}) or {}).get("latest_draft")
        if not draft_api:
            raise SystemExit("Zenodo did not return a new-version draft link.")
        _, dep = _api("GET", draft_api, token)
    else:
        _, dep = _api("POST", f"{base}/deposit/depositions", token, json_body={})

    dep_id = dep["id"]
    bucket = dep["links"]["bucket"]
    # upload the paper (overwrites the inherited copy when versioning)
    _api("PUT", f"{bucket}/paper.pdf", token, raw=pdf.read_bytes(),
         content_type="application/octet-stream")
    # upload the code + data bundle alongside it
    bundle_name = None
    if with_code_data:
        bundle = _build_bundle(run_id)
        bundle_name = bundle.name
        _api("PUT", f"{bucket}/{bundle_name}", token, raw=bundle.read_bytes(),
             content_type="application/octet-stream")
    # attach metadata
    _, dep2 = _api("PUT", f"{base}/deposit/depositions/{dep_id}", token, json_body={"metadata": meta})

    rec = {
        "environment": "production" if production else "sandbox",
        "deposition_id": dep_id,
        "draft_url": dep["links"].get("html"),
        "title": title,
        "files": ["paper.pdf"] + ([bundle_name] if bundle_name else []),
        "published": False,
        "reserved_doi": (dep2.get("metadata", {}).get("prereserve_doi", {}) or {}).get("doi"),
    }
    if publish:
        _, pub = _api("POST", f"{base}/deposit/depositions/{dep_id}/actions/publish", token)
        rec["published"] = True
        rec["doi"] = pub.get("doi")
        rec["concept_doi"] = pub.get("conceptdoi")
        rec["record_url"] = (pub.get("links", {}) or {}).get("record_html")
    (pdir / "zenodo.json").write_text(json.dumps(rec, indent=2))
    print(json.dumps(rec, indent=2))
    return rec


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="aisci.zenodo")
    sub = p.add_subparsers(dest="cmd", required=True)
    pd = sub.add_parser("deposit", help="deposit a project's paper.pdf to Zenodo")
    pd.add_argument("project", help="project id or projects/<id>")
    pd.add_argument("--production", action="store_true", help="use zenodo.org (default: sandbox)")
    pd.add_argument("--publish", action="store_true", help="publish (PERMANENT); default: draft only")
    pd.add_argument("--publication-type", default="preprint")
    pd.add_argument("--force", action="store_true", help="allow production publish without an Accept review")
    pd.add_argument("--new-version", action="store_true",
                    help="publish a new version of the prior deposit (from zenodo.json)")
    pd.add_argument("--no-code-data", action="store_true",
                    help="do NOT attach the code+data bundle (paper only)")
    pd.add_argument("--dry-run", action="store_true", help="print the metadata; no token/network")
    args = p.parse_args(argv)
    run_id = Path(args.project).name
    deposit(run_id, production=args.production, publish=args.publish,
            publication_type=args.publication_type, force=args.force, dry_run=args.dry_run,
            with_code_data=not args.no_code_data, new_version=args.new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
