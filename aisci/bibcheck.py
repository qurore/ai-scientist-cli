"""Deterministic citation verifier for a project's ``references.bib``.

The writeup/review skills tell *you* (the agent) to verify every citation via the
arxiv / semantic-scholar MCP and never invent references. That is a discipline, not
a guarantee. This module is the deterministic backstop: it parses the BibTeX file
and checks each entry against **public bibliographic APIs** — Crossref (for DOIs and
title search) and the arXiv API (for arXiv ids) — with **no LLM and no MCP** in the
loop. It catches the concrete hallucination signals: a DOI or arXiv id that does not
resolve, and a title-only reference that no real paper matches.

Output:
  * a machine-readable report at ``projects/<id>/writeup/bibcheck.json``
  * a human summary on stdout
  * exit code 0 if clean, 1 if any blocking (hallucination) signal is present.

The ``enforce_bibcheck`` PreToolUse hook reads the JSON report (never the network)
and refuses to let the writeup stage be marked done until the report is fresh (its
recorded ``bib_sha256`` matches the current file) and clean.

Network-dependent by nature. An entry that cannot be reached (offline, rate-limited)
is recorded as ``network_error`` and is **not** treated as a hallucination — we never
accuse a citation of being fake just because we could not reach the internet. But if
*nothing* could be verified, the report is not a real check and the hook says so.

Usage:
    python -m aisci.bibcheck projects/<id>        # verify that project's references.bib
    python -m aisci.bibcheck <id>                 # same, by project id
    python -m aisci.bibcheck projects/<id> --bib path/to/other.bib
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Contact string for the API "polite pools" (Crossref, arXiv). Non-secret; helps them
# rate-limit us fairly. Pulled from env if the curator set one, else a generic UA.
_MAILTO = os.environ.get("CROSSREF_MAILTO") or os.environ.get("AUTHOR_EMAIL") or ""
USER_AGENT = (
    "ai-scientist-cli/bibcheck (citation existence check; "
    + (f"mailto:{_MAILTO})" if _MAILTO else "https://github.com/)")
)

# Statuses that mean "this is very likely a fabricated / hallucinated citation" and so
# should block finalizing the paper. See classify() below.
BLOCKING = {"not_found", "unresolved"}
# Non-blocking, but surfaced: a resolvable paper whose title differs (probably messy
# metadata, not a fake), an entry with nothing to query on, or a lookup we couldn't run.
WARNING = {"title_mismatch", "no_query", "network_error"}


# ─────────────────────────── BibTeX parsing (dependency-free) ───────────────────────────

def _read_delimited(text: str, start: int, opench: str, closech: str) -> tuple[str, int]:
    """Read a brace/paren-balanced (or quote-terminated) value starting at ``start``
    (which points at the opening delimiter). Returns (inner_text, index_after_close)."""
    depth = 0
    i = start
    n = len(text)
    if opench == '"':  # quoted value: read to next '"' that isn't inside braces
        i += 1
        buf = []
        brace = 0
        while i < n:
            c = text[i]
            if c == "{":
                brace += 1
            elif c == "}":
                brace = max(0, brace - 1)
            elif c == '"' and brace == 0:
                return "".join(buf), i + 1
            buf.append(c)
            i += 1
        return "".join(buf), i
    # brace-delimited value
    while i < n:
        c = text[i]
        if c == opench:
            depth += 1
        elif c == closech:
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], n


def _clean(val: str) -> str:
    """Strip LaTeX braces and collapse whitespace so titles compare cleanly."""
    val = val.replace("{", "").replace("}", "")
    val = re.sub(r"\s+", " ", val)
    return val.strip().strip(",").strip()


def _parse_fields(body: str) -> dict:
    fields: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        m = re.match(r"([A-Za-z][A-Za-z0-9_\-]*)\s*=\s*", body[i:])
        if not m:
            break
        name = m.group(1).lower()
        i += m.end()
        if i >= n:
            break
        c = body[i]
        if c == "{":
            val, i = _read_delimited(body, i, "{", "}")
        elif c == '"':
            val, i = _read_delimited(body, i, '"', '"')
        else:  # bare value (a number or an abbreviation macro) up to the next comma
            j = i
            while j < n and body[j] != ",":
                j += 1
            val, i = body[i:j], j
        fields[name] = _clean(val)
    return fields


def parse_bib(text: str) -> list[dict]:
    """Tolerant BibTeX parser. Returns a list of {type, key, ...fields}. Skips
    ``@comment``/``@string``/``@preamble``. Good enough to pull title/doi/eprint/url."""
    entries: list[dict] = []
    i, n = 0, len(text)
    while True:
        at = text.find("@", i)
        if at == -1:
            break
        j = at + 1
        while j < n and text[j].isalpha():
            j += 1
        etype = text[at + 1:j].lower()
        # find the opening brace of the entry
        while j < n and text[j] not in "{(":
            j += 1
        if j >= n:
            break
        body, end = _read_delimited(text, j, "{", "}") if text[j] == "{" else _read_delimited(text, j, "(", ")")
        i = end
        if etype in ("comment", "string", "preamble"):
            continue
        # split off the citekey (everything before the first comma; keys have no commas)
        if "," not in body:
            continue
        key, rest = body.split(",", 1)
        entry = {"type": etype, "key": key.strip()}
        entry.update(_parse_fields(rest))
        entries.append(entry)
    return entries


# ─────────────────────────── identifier extraction ───────────────────────────

_ARXIV_NEW = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
_ARXIV_OLD = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")


def extract_doi(e: dict) -> str:
    doi = (e.get("doi") or "").strip()
    if not doi:
        for f in ("url", "eprint", "note"):
            m = re.search(r"10\.\d{4,9}/[^\s{}\"]+", e.get(f, ""))
            if m:
                doi = m.group(0)
                break
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I).strip().rstrip(".")
    # A pure arXiv DOI is better checked via the arXiv API; don't treat it as a Crossref DOI.
    if doi.lower().startswith("10.48550/arxiv"):
        return ""
    return doi


def extract_arxiv(e: dict) -> str:
    prefix = (e.get("archiveprefix") or e.get("archivePrefix") or "").lower()
    eprint = (e.get("eprint") or "").strip()
    if "arxiv" in prefix and eprint:
        return re.sub(r"v\d+$", "", eprint)
    haystack = " ".join(e.get(f, "") for f in ("eprint", "url", "doi", "journal", "note", "howpublished"))
    if "arxiv" in haystack.lower() or "arxiv" in prefix:
        m = _ARXIV_NEW.search(haystack) or _ARXIV_OLD.search(haystack)
        if m:
            return m.group(1)
    # bare eprint that *looks* like an arXiv id even without an explicit prefix
    if eprint:
        m = _ARXIV_NEW.fullmatch(eprint) or _ARXIV_OLD.fullmatch(eprint)
        if m:
            return m.group(1)
    return ""


# ─────────────────────────── title matching ───────────────────────────

def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def titles_match(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.90


# ─────────────────────────── HTTP + API lookups ───────────────────────────

# Be a polite API client: a shared minimum gap between requests keeps us out of the
# rate-limiter, and we back off (honoring Retry-After) instead of giving up on a 429/503.
_MIN_INTERVAL = float(os.environ.get("BIBCHECK_MIN_INTERVAL", "0.6"))
_RATE = {"last": 0.0}


def _throttle():
    now = time.monotonic()
    wait = _MIN_INTERVAL - (now - _RATE["last"])
    if wait > 0:
        time.sleep(wait)
    _RATE["last"] = time.monotonic()


def _http(url: str, timeout: float, accept: str = "application/json", retries: int = 3):
    """Return (code, text). code is the HTTP status (int) or None on a connection
    error. On an HTTP error status the body is None. Distinguishes a definitive 404
    (paper does not exist) from a transport failure (offline / rate-limited). Retries
    a rate-limit/transient status (429/503) with backoff, honoring Retry-After."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    backoff = 1.0
    for attempt in range(retries + 1):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.getcode(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as ex:
            if ex.code in (429, 503) and attempt < retries:
                ra = ex.headers.get("Retry-After") if ex.headers else None
                try:
                    delay = float(ra) if ra else backoff
                except ValueError:
                    delay = backoff
                time.sleep(min(delay, 8.0))
                backoff *= 2
                continue
            return ex.code, None
        except Exception:
            return None, None  # connection / timeout / DNS — a network error, not a 404
    return 429, None


def _crossref_doi(doi: str, title: str, timeout: float) -> dict:
    q = urllib.parse.quote(doi, safe="")
    url = f"https://api.crossref.org/works/{q}"
    if _MAILTO:
        url += "?mailto=" + urllib.parse.quote(_MAILTO)
    code, text = _http(url, timeout)
    if code == 404:
        return {"status": "not_found", "source": "crossref", "detail": f"DOI {doi} not in Crossref"}
    if code == 200 and text:
        try:
            msg = json.loads(text).get("message", {})
            found = (msg.get("title") or [""])[0]
        except Exception:
            found = ""
        if title and found and not titles_match(title, found):
            return {"status": "title_mismatch", "source": "crossref",
                    "matched_title": found, "detail": "DOI resolves but title differs"}
        return {"status": "verified", "source": "crossref", "matched_title": found}
    return {"status": "network_error", "source": "crossref", "detail": f"HTTP {code}"}


def _arxiv_id(arxiv: str, title: str, timeout: float) -> dict:
    url = "http://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv) + "&max_results=1"
    code, text = _http(url, timeout, accept="application/atom+xml")
    if code is None or text is None:
        return {"status": "network_error", "source": "arxiv", "detail": f"HTTP {code}"}
    found = _arxiv_first_title(text)
    if found is None:
        return {"status": "not_found", "source": "arxiv", "detail": f"arXiv id {arxiv} returned no entry"}
    if title and not titles_match(title, found):
        return {"status": "title_mismatch", "source": "arxiv",
                "matched_title": found, "detail": "arXiv id resolves but title differs"}
    return {"status": "verified", "source": "arxiv", "matched_title": found}


_ATOM = "{http://www.w3.org/2005/Atom}"


def _arxiv_first_title(atom_xml: str):
    try:
        root = ET.fromstring(atom_xml)
    except Exception:
        return None
    for entry in root.findall(f"{_ATOM}entry"):
        # arXiv returns a synthetic "Error" entry (id .../api/errors) when nothing matches
        eid = (entry.findtext(f"{_ATOM}id") or "")
        if "/api/errors" in eid:
            return None
        t = entry.findtext(f"{_ATOM}title")
        if t:
            return _clean(t)
    return None


def _title_search(title: str, timeout: float) -> dict:
    """Title-only entry: try to find *any* real paper with a matching title, across
    Crossref then arXiv. Only after both come up empty (and the network worked) do we
    call it ``unresolved`` — the hallucination signal for reference lists without ids."""
    reached = False
    # 1) Crossref bibliographic search
    url = ("https://api.crossref.org/works?rows=5&query.bibliographic="
           + urllib.parse.quote(title))
    if _MAILTO:
        url += "&mailto=" + urllib.parse.quote(_MAILTO)
    code, text = _http(url, timeout)
    if code == 200 and text:
        reached = True
        try:
            for item in json.loads(text).get("message", {}).get("items", []):
                cand = (item.get("title") or [""])[0]
                if titles_match(title, cand):
                    return {"status": "verified", "source": "crossref-search", "matched_title": cand}
        except Exception:
            pass
    elif code is not None:
        reached = True
    # 2) arXiv title search
    aurl = ('http://export.arxiv.org/api/query?search_query=ti:'
            + urllib.parse.quote('"' + title + '"') + "&max_results=5")
    code2, text2 = _http(aurl, timeout, accept="application/atom+xml")
    if code2 is not None and text2:
        reached = True
        try:
            root = ET.fromstring(text2)
            for entry in root.findall(f"{_ATOM}entry"):
                cand = _clean(entry.findtext(f"{_ATOM}title") or "")
                if cand and titles_match(title, cand):
                    return {"status": "verified", "source": "arxiv-search", "matched_title": cand}
        except Exception:
            pass
    if not reached:
        return {"status": "network_error", "source": "search", "detail": "no search endpoint reachable"}
    return {"status": "unresolved", "source": "search",
            "detail": "no Crossref/arXiv paper matches this title"}


# ─────────────────────────── per-entry classification ───────────────────────────

def classify(entry: dict, timeout: float) -> dict:
    title = entry.get("title", "")
    doi = extract_doi(entry)
    arxiv = extract_arxiv(entry)
    res: dict = {}
    if doi:
        res = _crossref_doi(doi, title, timeout)
        # If a DOI genuinely isn't in Crossref, it may still be a real (e.g. arXiv-only)
        # paper — fall through to a title search rather than crying fabrication outright.
        if res.get("status") == "not_found" and (arxiv or title):
            res = {}
    if not res and arxiv:
        res = _arxiv_id(arxiv, title, timeout)
        if res.get("status") == "not_found" and title:
            res = {}
    if not res:
        if title:
            res = _title_search(title, timeout)
        else:
            res = {"status": "no_query", "source": "-",
                   "detail": "entry has no title, DOI, or arXiv id to verify"}
    out = {"key": entry.get("key", ""), "title": title, "doi": doi, "arxiv": arxiv}
    out.update(res)
    return out


# ─────────────────────────── bib discovery + top-level run ───────────────────────────

def find_bib(project_dir: Path, override: str | None = None) -> Path | None:
    if override:
        p = Path(override)
        return p if p.exists() else None
    candidates = [
        project_dir / "writeup" / "latex" / "references.bib",
        project_dir / "writeup" / "references.bib",
    ]
    for c in candidates:
        if c.exists():
            return c
    hits = sorted((project_dir / "writeup").rglob("*.bib")) if (project_dir / "writeup").exists() else []
    # prefer a file literally named references.bib
    hits.sort(key=lambda h: (h.name != "references.bib", len(str(h))))
    return hits[0] if hits else None


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry_keys(entry: dict) -> list[str]:
    """Stable identity keys for an entry, used to cache positive verifications so a
    re-run (the fix-and-recheck loop) doesn't re-hit the API for papers already proven
    real. A paper that existed still exists, so caching *positives* is always safe."""
    keys = []
    doi = extract_doi(entry)
    arxiv = extract_arxiv(entry)
    title = _norm(entry.get("title", ""))
    if doi:
        keys.append("doi:" + doi.lower())
    if arxiv:
        keys.append("arxiv:" + arxiv.lower())
    if title:
        keys.append("title:" + title)
    return keys


def resolve_project(arg: str) -> tuple[Path, str]:
    p = Path(arg)
    if p.exists() and p.is_dir():
        return p.resolve(), p.name
    alt = REPO / "projects" / arg
    if alt.exists():
        return alt.resolve(), arg
    raise SystemExit(f"[bibcheck] no such project or directory: {arg}")


def run(project_arg: str, bib_override: str | None = None, timeout: float = 12.0,
        use_cache: bool = True) -> dict:
    project_dir, pid = resolve_project(project_arg)
    bib = find_bib(project_dir, bib_override)
    report: dict = {
        "generated": time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()),
        "project": pid,
        "bib_path": str(bib) if bib else None,
        "bib_sha256": sha256_of(bib) if bib else None,
    }
    if not bib:
        report.update({"counts": {}, "blocking": 0, "ok": True, "entries": [],
                       "note": "no references.bib found — nothing to verify"})
        return report

    cache_path = project_dir / "writeup" / ".bibcheck_cache.json"
    cache: dict = {}
    if use_cache and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text()).get("verified", {})
        except Exception:
            cache = {}

    entries = parse_bib(bib.read_text(encoding="utf-8", errors="replace"))
    results = []
    for e in entries:
        keys = entry_keys(e)
        hit = next((cache[k] for k in keys if k in cache), None)
        if hit is not None:  # previously proven real — trust the positive, skip the network
            out = {"key": e.get("key", ""), "title": e.get("title", ""),
                   "doi": extract_doi(e), "arxiv": extract_arxiv(e),
                   "status": "verified", "source": "cache",
                   "matched_title": hit.get("matched_title", "")}
        else:
            out = classify(e, timeout)
            if out.get("status") == "verified":
                for k in keys:
                    cache[k] = {"matched_title": out.get("matched_title", ""),
                                "source": out.get("source", "")}
        results.append(out)

    if use_cache:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"verified": cache}, indent=2))
        except Exception:
            pass

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(results)
    verified = counts.get("verified", 0)
    blocking = sum(counts.get(s, 0) for s in BLOCKING)
    net_err = counts.get("network_error", 0)
    report.update({
        "counts": {"total": total, **counts},
        "verified": verified,
        "blocking": blocking,
        "network_degraded": net_err > 0,
        "nothing_verified": total > 0 and verified == 0,
        "ok": blocking == 0,
        "entries": results,
    })
    return report


def _print_summary(report: dict) -> None:
    c = report.get("counts", {})
    total = c.get("total", 0)
    print(f"[bibcheck] {report['project']}: {total} references — "
          f"{report.get('verified', 0)} verified, {report.get('blocking', 0)} blocking")
    if report.get("bib_path"):
        print(f"           bib: {report['bib_path']}")
    for r in report.get("entries", []):
        if r["status"] == "verified":
            continue
        tag = "BLOCK" if r["status"] in BLOCKING else "warn "
        title = (r.get("title") or "")[:70]
        print(f"  [{tag}] {r['status']:14s} {r['key']:22s} {title}")
        if r.get("detail"):
            print(f"           ↳ {r['detail']}")
    if report.get("nothing_verified"):
        print("  [warn ] nothing could be verified — likely offline/rate-limited; re-run online.")
    print(f"[bibcheck] verdict: {'CLEAN ✓' if report.get('ok') else 'HALLUCINATION SIGNALS ✗'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aisci.bibcheck",
                                 description="Deterministically verify a project's citations exist.")
    ap.add_argument("project", help="project id or path to projects/<id>")
    ap.add_argument("--bib", default=None, help="explicit path to a .bib file (overrides discovery)")
    ap.add_argument("--timeout", type=float, default=12.0, help="per-request HTTP timeout (s)")
    ap.add_argument("--json", action="store_true", help="print the full report JSON to stdout too")
    ap.add_argument("--no-cache", action="store_true",
                    help="re-verify every entry online, ignoring the positive-verification cache")
    args = ap.parse_args(argv)

    report = run(args.project, args.bib, args.timeout, use_cache=not args.no_cache)

    # Always persist the report next to the paper so the hook (and humans) can read it.
    if report.get("bib_path"):
        # write into the project's writeup/ dir, not next to a --bib override elsewhere
        project_dir, _ = resolve_project(args.project)
        report_path = project_dir / "writeup" / "bibcheck.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))
        report["report_path"] = str(report_path)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_summary(report)
        if report.get("report_path"):
            print(f"[bibcheck] report: {report['report_path']}")

    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
