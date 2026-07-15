"""Per-citation evidence vault: no citation ships without its receipts.

``aisci.bibcheck`` proves each reference *exists* and that its metadata matches the
registry. This module goes further and makes every citation carry **primary-source
evidence** under ``projects/<id>/writeup/citations/``:

    citations/
      index.json                whole-vault manifest (freshness + per-key verdicts)
      <bibkey>/
        paper.pdf               the cited paper itself (arXiv / open-access download)
        paper.txt               pdftotext extraction (enables verbatim-quote checks)
        source.html             snapshot ("fish print") of the page it was fetched from
        evidence.json           registry record, artifact hashes, and usage records:
                                where the paper cites it, the claim being supported,
                                and a VERBATIM quote from the cited paper

Two design rules make hallucination mechanically impossible rather than merely
discouraged:

1. **Bib entries are generated, not written.** ``add`` / ``rebib`` fetch the
   authoritative record (arXiv API / Crossref) and render the BibTeX themselves;
   the agent only supplies an id. ``verify`` then re-compares every field, so a
   hand-edited (or hallucinated) title/author/year cannot survive.
2. **Usage evidence must quote the archived text.** Every usage record's
   ``supporting_quote`` must appear verbatim (whitespace/hyphenation-insensitively)
   in the archived ``paper.txt`` (or the page snapshot for paywalled refs). A quote
   that isn't really in the paper fails deterministically.

Semantic honesty — whether the quote genuinely supports the claim — is still the
agent's (and reviewer's) job; the vault makes that judgment *auditable* by pinning
it to real, archived text.

The ``enforce_citations`` PreToolUse hook blocks marking the writeup stage done (and
the study complete) until ``verify`` reports a fresh, fully clean vault, and re-runs
the offline checks itself so a hand-edited ``index.json`` doesn't pass.

Network use is limited to public bibliographic/archive endpoints (arXiv, Crossref,
Unpaywall for legal open-access PDF discovery, optionally the Wayback Machine); no
LLM, no MCP. Downloads are polite (per-host throttle, retry with backoff).

Usage (from repo root):
    .venv/bin/python -m aisci.citations add    projects/<id> --arxiv 2604.06688 [--key k]
    .venv/bin/python -m aisci.citations add    projects/<id> --doi 10.x/y
    .venv/bin/python -m aisci.citations rebib  projects/<id> --all        # canonicalize existing bib
    .venv/bin/python -m aisci.citations fetch  projects/<id> [--key k]    # archive artifacts only
    .venv/bin/python -m aisci.citations usage  projects/<id> --key k \
        --where "Sec. 2" --claim "<sentence from paper.tex>" \
        --quote "<verbatim passage from the cited paper>" --note "<how it supports>"
    .venv/bin/python -m aisci.citations verify projects/<id> [--offline] [--refresh]
    .venv/bin/python -m aisci.citations status projects/<id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import bibcheck
from .bibcheck import (USER_AGENT, _ascii_fold, _clean, _http, _name_tokens,
                       _parse_fields, _read_delimited, compare_meta, extract_arxiv,
                       extract_doi, find_bib, resolve_project, sha256_of)

PDF_NAME = "paper.pdf"
TEXT_NAME = "paper.txt"
SNAP_NAME = "source.html"
EVIDENCE_NAME = "evidence.json"
INDEX_NAME = "index.json"

# A "supporting quote" shorter than this (after squashing to alphanumerics) matches
# almost anything and proves nothing — refuse it.
MIN_QUOTE_CHARS = 20


def vault_dir(project_dir: Path) -> Path:
    return Path(project_dir) / "writeup" / "citations"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_file(p: Path) -> str:
    return _sha_bytes(Path(p).read_bytes())


def _squash(s: str) -> str:
    """Collapse text to bare lowercase alphanumerics. Survives line breaks, hyphenation
    ('mar-\\nkets' -> 'markets'), ligatures, and punctuation drift between a PDF's
    extracted text and a quoted passage."""
    return re.sub(r"[^a-z0-9]+", "", _ascii_fold(s or "").lower())


# ─────────────────────────── polite fetching ───────────────────────────

_HOST_LAST: dict[str, float] = {}


def _polite_wait(url: str) -> None:
    host = urllib.parse.urlparse(url).netloc.lower()
    interval = float(os.environ.get("AISCI_CITE_INTERVAL", "3.0")) if "arxiv.org" in host else 1.0
    wait = interval - (time.monotonic() - _HOST_LAST.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _HOST_LAST[host] = time.monotonic()


def _fetch_bytes(url: str, timeout: float = 60.0, accept: str | None = None,
                 retries: int = 2):
    """GET raw bytes. Returns (http_status|None, final_url, body|None). Retries
    429/503 with backoff (honoring Retry-After); a connection error returns None
    status so callers can distinguish 'offline' from 'does not exist'."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    backoff = 2.0
    for attempt in range(retries + 1):
        _polite_wait(url)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.getcode(), r.geturl(), r.read()
        except urllib.error.HTTPError as ex:
            if ex.code in (429, 503) and attempt < retries:
                ra = ex.headers.get("Retry-After") if ex.headers else None
                try:
                    delay = float(ra) if ra else backoff
                except ValueError:
                    delay = backoff
                time.sleep(min(delay, 15.0))
                backoff *= 2
                continue
            try:
                body = ex.read()
            except Exception:
                body = None
            return ex.code, url, body
        except Exception:
            return None, url, None
    return 429, url, None


# ─────────────────────────── bib parsing with source spans ───────────────────────────

def parse_bib_spans(text: str) -> list[tuple[dict, str, int, int]]:
    """Like bibcheck.parse_bib but also returns each entry's exact source slice and
    span, so entries can be hashed (evidence freshness) and spliced (rebib/add)."""
    out: list[tuple[dict, str, int, int]] = []
    i, n = 0, len(text)
    while True:
        at = text.find("@", i)
        if at == -1:
            break
        j = at + 1
        while j < n and text[j].isalpha():
            j += 1
        etype = text[at + 1:j].lower()
        while j < n and text[j] not in "{(":
            j += 1
        if j >= n:
            break
        if text[j] == "{":
            body, end = _read_delimited(text, j, "{", "}")
        else:
            body, end = _read_delimited(text, j, "(", ")")
        i = end
        if etype in ("comment", "string", "preamble") or "," not in body:
            continue
        key, rest = body.split(",", 1)
        entry = {"type": etype, "key": key.strip()}
        entry.update(_parse_fields(rest))
        out.append((entry, text[at:end], at, end))
    return out


def entry_sha(raw: str) -> str:
    return _sha_bytes(raw.strip().encode("utf-8"))


# ─────────────────────────── registry lookup + BibTeX generation ───────────────────────────

def registry_meta(arxiv: str | None = None, doi: str | None = None,
                  timeout: float = 20.0) -> dict:
    """Fetch the authoritative record for an id. {"meta": {...}} or {"status": ...}.
    A DOI takes precedence (it names the published version)."""
    if doi:
        return bibcheck._crossref_doi(doi, timeout)
    if arxiv:
        return bibcheck._arxiv_id(re.sub(r"v\d+$", "", arxiv.strip()), timeout)
    return {"status": "no_identifier", "detail": "need --arxiv or --doi"}


_BIB_ESCAPE = re.compile(r"(?<!\\)([&%#])")
_STOP_WORDS = {"a", "an", "the", "on", "of", "for", "and", "or", "in", "to", "with",
               "when", "at", "from", "by", "is", "are", "as", "its", "their", "via",
               "toward", "towards", "do", "does", "can", "what", "how", "why"}


def _tex(s: str) -> str:
    return _BIB_ESCAPE.sub(r"\\\1", s or "")


def make_key(meta: dict) -> str:
    fam = _name_tokens(meta["authors"][0])[-1] if meta.get("authors") else "anon"
    words = [w for w in re.sub(r"[^a-z0-9\s]", " ", _ascii_fold(meta.get("title", "")).lower()).split()
             if w not in _STOP_WORDS]
    return f"{fam}{meta.get('year') or ''}{''.join(words[:3])}"


def render_bib_entry(key: str, meta: dict, fallback: dict | None = None) -> str:
    """Render the canonical BibTeX for a registry record. This is the *only* way a
    bib entry should come into existence — never hand-write one.

    ``fallback`` (the pre-existing parsed entry, if any) fills only fields the
    registry record *omits* (old Crossref records sometimes lack authors). Fields the
    registry does provide always win — and verification only compares
    registry-provided fields, so a carried-over value is never silently 'verified'."""
    fallback = fallback or {}
    authors = _tex(" and ".join(meta.get("authors") or []))
    if not authors and fallback.get("author"):
        authors = _tex(fallback["author"])
        print(f"  [note] registry record lists no authors — kept the entry's existing "
              f"author field ('{fallback['author'][:60]}'); verify it manually against "
              f"the paper itself")
    if meta.get("source") == "arxiv":
        aid = meta.get("arxiv", "")
        lines = [f"@misc{{{key},",
                 f"  title={{{_tex(meta.get('title', ''))}}},",
                 f"  author={{{authors}}},",
                 f"  year={{{meta.get('year') or ''}}},",
                 f"  eprint={{{aid}}},",
                 "  archivePrefix={arXiv},"]
        if meta.get("primary_class"):
            lines.append(f"  primaryClass={{{meta['primary_class']}}},")
        lines.append(f"  url={{https://arxiv.org/abs/{aid}}}")
        lines.append("}")
        return "\n".join(lines)
    etype = {"journal-article": "article", "proceedings-article": "inproceedings",
             "book-chapter": "incollection", "book": "book", "monograph": "book",
             }.get(meta.get("type", ""), "misc")
    doi = meta.get("doi", "")
    fields = [("title", _tex(meta.get("title", ""))),
              ("author", authors),
              ("year", str(meta.get("year") or ""))]
    container = meta.get("container", "")
    if container and etype in ("article", "inproceedings", "incollection"):
        fields.append(("journal" if etype == "article" else "booktitle", _tex(container)))
    for f in ("volume", "number", "pages"):
        v = meta.get(f) or fallback.get(f)
        if v:
            fields.append((f, str(v)))
    if doi:
        fields.append(("doi", doi))
        fields.append(("url", f"https://doi.org/{doi}"))
    body = ",\n".join(f"  {k}={{{v}}}" for k, v in fields if v)
    return f"@{etype}{{{key},\n{body}\n}}"


def source_urls(meta: dict, entry: dict | None = None) -> tuple[str, str]:
    """(landing_page_url, direct_pdf_url_or_empty) for a registry record."""
    if meta.get("source") == "arxiv":
        aid = meta.get("arxiv") or (extract_arxiv(entry) if entry else "")
        return f"https://arxiv.org/abs/{aid}", f"https://arxiv.org/pdf/{aid}"
    doi = meta.get("doi") or (extract_doi(entry) if entry else "")
    return (f"https://doi.org/{doi}" if doi else ""), ""


# ─────────────────────────── artifact archiving ───────────────────────────

def _wayback(url: str) -> str | None:
    """Best-effort Wayback Machine save; returns the archived URL or None."""
    code, final, _ = _fetch_bytes("https://web.archive.org/save/" + url, timeout=90.0)
    if code == 200 and "web.archive.org/web/" in (final or ""):
        return final
    return None


def fetch_snapshot(url: str, kdir: Path, wayback: bool = False) -> dict:
    info: dict = {"path": SNAP_NAME, "url": url, "fetched_at": _now(), "wayback_url": None}
    code, final, body = _fetch_bytes(url, timeout=45.0,
                                     accept="text/html,application/xhtml+xml")
    info["http_status"] = code
    info["final_url"] = final
    if body:
        (kdir / SNAP_NAME).write_bytes(body)
        info["sha256"] = _sha_bytes(body)
        info["bytes"] = len(body)
    if wayback:
        info["wayback_url"] = _wayback(url)
    return info


def _oa_pdf_url(doi: str, timeout: float = 20.0) -> str:
    """Find a *legal* open-access PDF for a DOI (Unpaywall, then Crossref links).
    Paywalled papers are never fetched from shadow libraries — they are recorded as
    unavailable instead."""
    email = os.environ.get("CROSSREF_MAILTO") or os.environ.get("AUTHOR_EMAIL") or bibcheck._MAILTO
    if email:
        code, _, body = _fetch_bytes(
            f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}"
            f"?email={urllib.parse.quote(email)}",
            timeout=timeout, accept="application/json")
        if code == 200 and body:
            try:
                j = json.loads(body)
                for loc in [j.get("best_oa_location") or {}] + (j.get("oa_locations") or []):
                    if (loc or {}).get("url_for_pdf"):
                        return loc["url_for_pdf"]
            except Exception:
                pass
    code, _, body = _fetch_bytes(
        f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}",
        timeout=timeout, accept="application/json")
    if code == 200 and body:
        try:
            for ln in (json.loads(body).get("message", {}).get("link") or []):
                if "pdf" in (ln.get("content-type") or ""):
                    return ln.get("URL", "")
        except Exception:
            pass
    return ""


def fetch_pdf(meta: dict, entry: dict | None, kdir: Path) -> dict:
    info: dict = {"path": PDF_NAME}
    if meta.get("source") == "arxiv":
        pdf_url = f"https://arxiv.org/pdf/{meta.get('arxiv') or (extract_arxiv(entry) if entry else '')}"
    else:
        doi = meta.get("doi") or (extract_doi(entry) if entry else "")
        pdf_url = _oa_pdf_url(doi) if doi else ""
        if not pdf_url:
            info.update({"status": "unavailable", "fetched_at": _now(),
                         "reason": "no open-access PDF located (paywalled?) — the "
                                   "landing-page snapshot is the archived record"})
            return info
    code, final, body = _fetch_bytes(pdf_url, timeout=120.0, accept="application/pdf")
    info["source_url"] = final or pdf_url
    info["fetched_at"] = _now()
    if code == 200 and body and body[:5] == b"%PDF-":
        (kdir / PDF_NAME).write_bytes(body)
        info.update({"status": "archived", "sha256": _sha_bytes(body), "bytes": len(body)})
    else:
        info.update({"status": "unavailable",
                     "reason": f"download failed (HTTP {code} or response was not a PDF)"})
    return info


def extract_text(kdir: Path) -> dict:
    pdf, txt = kdir / PDF_NAME, kdir / TEXT_NAME
    if not pdf.exists():
        return {"path": TEXT_NAME, "status": "no_pdf"}
    exe = shutil.which("pdftotext")
    if not exe:
        return {"path": TEXT_NAME, "status": "extractor_missing", "extractor": "pdftotext"}
    try:
        subprocess.run([exe, "-enc", "UTF-8", str(pdf), str(txt)],
                       check=True, capture_output=True, timeout=120)
    except Exception as ex:
        return {"path": TEXT_NAME, "status": "extraction_failed", "detail": str(ex)[:200]}
    chars = len(txt.read_text(encoding="utf-8", errors="replace")) if txt.exists() else 0
    return {"path": TEXT_NAME, "status": "extracted", "extractor": "pdftotext",
            "sha256": _sha_file(txt), "chars": chars}


# ─────────────────────────── evidence records ───────────────────────────

def load_evidence(kdir: Path) -> dict | None:
    p = kdir / EVIDENCE_NAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_evidence(kdir: Path, ev: dict) -> None:
    kdir.mkdir(parents=True, exist_ok=True)
    (kdir / EVIDENCE_NAME).write_text(json.dumps(ev, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8")


def ensure_citation(project_dir: Path, key: str, meta: dict, entry: dict | None,
                    entry_raw: str, wayback: bool = False, refetch: bool = False) -> dict:
    """Make citations/<key>/ complete for a registry record: snapshot + PDF + text +
    evidence.json (existing usage records are preserved)."""
    kdir = vault_dir(project_dir) / key
    kdir.mkdir(parents=True, exist_ok=True)
    ev = load_evidence(kdir) or {}
    files = ev.get("files") or {}

    abs_url, _ = source_urls(meta, entry)
    snap = files.get("snapshot") or {}
    if refetch or snap.get("http_status") != 200 or not (kdir / SNAP_NAME).exists():
        snap = fetch_snapshot(abs_url, kdir, wayback=wayback) if abs_url \
            else {"path": SNAP_NAME, "http_status": None, "url": "", "fetched_at": _now()}
    elif wayback and not snap.get("wayback_url"):
        snap["wayback_url"] = _wayback(abs_url)

    pdf = files.get("pdf") or {}
    have_good_pdf = (pdf.get("status") == "archived" and (kdir / PDF_NAME).exists()
                     and _sha_file(kdir / PDF_NAME) == pdf.get("sha256"))
    keep_unavailable = pdf.get("status") == "unavailable" and not refetch
    if refetch or not (have_good_pdf or keep_unavailable):
        pdf = fetch_pdf(meta, entry, kdir)

    text = files.get("text") or {}
    if pdf.get("status") == "archived":
        have_good_text = (text.get("status") == "extracted" and (kdir / TEXT_NAME).exists()
                          and _sha_file(kdir / TEXT_NAME) == text.get("sha256"))
        if refetch or not have_good_text:
            text = extract_text(kdir)
    elif not (kdir / TEXT_NAME).exists():
        text = {"path": TEXT_NAME, "status": "no_pdf"}

    ident = {"arxiv": meta.get("arxiv") or (extract_arxiv(entry) if entry else ""),
             "doi": meta.get("doi") or (extract_doi(entry) if entry else "")}
    ev.update({
        "key": key,
        "bib_entry_sha256": entry_sha(entry_raw) if entry_raw else ev.get("bib_entry_sha256"),
        "identity": ident,
        "registry": {**{k: meta.get(k) for k in
                        ("source", "title", "titles", "authors", "year", "primary_class",
                         "container", "type", "volume", "pages")},
                     "ids": ident, "fetched_at": _now()},
        "files": {"pdf": pdf, "text": text, "snapshot": snap},
    })
    ev.setdefault("usage", [])
    save_evidence(kdir, ev)
    return ev


def _archived_text(kdir: Path) -> tuple[str, str]:
    """Text available for verbatim-quote verification: the extracted PDF text, else
    the tag-stripped page snapshot (title/abstract at minimum)."""
    txt = kdir / TEXT_NAME
    if txt.exists():
        return txt.read_text(encoding="utf-8", errors="replace"), "pdf_text"
    snap = kdir / SNAP_NAME
    if snap.exists():
        html = snap.read_text(encoding="utf-8", errors="replace")
        return re.sub(r"<[^>]+>", " ", html), "snapshot_text"
    return "", ""


# ─────────────────────────── paper-side (LaTeX) helpers ───────────────────────────

_CITE_RE = re.compile(r"\\(?:no)?[Cc]ite[a-zA-Z*]*\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}")


def _strip_tex_comments(tex: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", tex)


def find_main_tex(project_dir: Path) -> Path | None:
    latex_dir = Path(project_dir) / "writeup" / "latex"
    p = latex_dir / "paper.tex"
    if p.exists():
        return p
    cands = sorted(latex_dir.glob("*.tex"), key=lambda x: -x.stat().st_size) \
        if latex_dir.exists() else []
    for c in cands:
        try:
            if "\\documentclass" in c.read_text(encoding="utf-8", errors="replace"):
                return c
        except Exception:
            pass
    return cands[0] if cands else None


def cited_keys(tex_text: str) -> set[str]:
    keys: set[str] = set()
    for m in _CITE_RE.finditer(_strip_tex_comments(tex_text)):
        for k in m.group(1).split(","):
            k = k.strip()
            if k:
                keys.add(k)
    return keys


# ─────────────────────────── verify (the deterministic gate) ───────────────────────────

def run_verify(project_arg: str, offline: bool = False, refresh: bool = False,
               write: bool = True, timeout: float = 20.0) -> dict:
    """Verify the whole vault against the current references.bib + paper source and
    (optionally) write citations/index.json. Deterministic; ``offline=True`` uses only
    local files + the registry snapshots already recorded in evidence.json — that mode
    is what the enforcement hook re-runs, so a hand-edited index.json cannot pass."""
    project_dir, pid = resolve_project(str(project_arg))
    bib = find_bib(project_dir)
    vault = vault_dir(project_dir)
    report: dict = {"generated": _now(), "project": pid, "offline": bool(offline),
                    "bib_path": str(bib) if bib else None,
                    "bib_sha256": sha256_of(bib) if bib else None}
    if not bib:
        report.update({"counts": {"total": 0, "verified": 0}, "blocking": 0, "ok": True,
                       "nothing_verified": False, "entries": [], "index_blocking": [],
                       "note": "no references.bib found — nothing to verify"})
        if write:
            vault.mkdir(parents=True, exist_ok=True)
            (vault / INDEX_NAME).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return report

    text = bib.read_text(encoding="utf-8", errors="replace")
    spans = parse_bib_spans(text)
    tex = find_main_tex(project_dir)
    tex_text = tex.read_text(encoding="utf-8", errors="replace") if tex else ""
    report["tex_path"] = str(tex) if tex else None
    report["tex_sha256"] = sha256_of(tex) if tex else None
    cited = cited_keys(tex_text) if tex_text else set()
    squashed_tex = _squash(_strip_tex_comments(tex_text))

    seen: set[str] = set()
    entries_out: list[dict] = []
    for entry, raw, _s, _e in spans:
        key = entry.get("key", "")
        blocking: list[str] = []
        warnings: list[str] = []
        info: dict = {}
        if key in seen:
            blocking.append("duplicate_key: key appears more than once in references.bib")
        seen.add(key)
        kdir = vault / key
        ev = load_evidence(kdir)
        doi, axv = extract_doi(entry), extract_arxiv(entry)

        reg0 = (ev or {}).get("registry") or {}
        if reg0.get("source") == "manual-exempt":
            # Whitepapers/standards with no registry record: allowed only because the
            # primary source itself is archived (and quote-checked) below. Surfaced as
            # a warning so it is never invisible.
            warnings.append(f"registry_exempt: {reg0.get('exempt_reason', '')} — no registry "
                            "record; the archived primary source is the evidence")
            info["registry_source"] = "manual-exempt"
        elif not doi and not axv:
            blocking.append("no_identifier: every reference must carry a DOI or arXiv id — "
                            "regenerate it with `aisci.citations add` (or, for a whitepaper/"
                            "standard, archive it with `aisci.citations exempt`)")
        else:
            # Registry record: the snapshot in evidence.json (if it matches this entry's
            # identity), else a live fetch. The comparison itself always re-runs.
            meta, meta_from = None, ""
            if ev and not refresh:
                reg = ev.get("registry") or {}
                ids = reg.get("ids") or {}
                if reg.get("authors") is not None and (
                        (axv and ids.get("arxiv") == axv) or (doi and ids.get("doi") == doi)):
                    meta, meta_from = reg, "evidence"
            if meta is None and not offline:
                r = registry_meta(arxiv=axv or None, doi=doi or None, timeout=timeout)
                if "meta" in r:
                    meta, meta_from = r["meta"], "network"
                elif r.get("status") == "network_error":
                    blocking.append(f"registry_unreachable: {r.get('detail', '')} — "
                                    "re-run while online")
                else:
                    blocking.append(f"not_found: {r.get('detail', 'id does not resolve')}")
            if meta is None and offline and not blocking:
                blocking.append("unverified_offline: no registry snapshot in evidence.json — "
                                "run `aisci.citations fetch`/`verify` online first")
            if meta is not None:
                cmp = compare_meta(entry, meta)
                info["registry_source"] = f"{meta.get('source', '')}[{meta_from}]"
                info["matched_title"] = cmp.get("matched_title", "")
                if cmp["status"] != "verified":
                    # In the vault even a year skew blocks: entries are machine-generated
                    # from the registry, so any drift means someone edited by hand.
                    blocking.append(f"{cmp['status']}: {cmp.get('detail', '')}")

        if ev is None:
            blocking.append("no_evidence: citations/<key>/evidence.json missing — run "
                            f"`aisci.citations fetch projects/{pid} --key {key}`")
        else:
            if ev.get("bib_entry_sha256") != entry_sha(raw):
                blocking.append("evidence_stale: the bib entry changed after its evidence was "
                                f"recorded — re-run `aisci.citations fetch projects/{pid} --key {key}`")
            files = ev.get("files") or {}
            pdf = files.get("pdf") or {}
            if pdf.get("status") == "archived":
                p = kdir / PDF_NAME
                if not p.exists():
                    blocking.append("pdf_missing: evidence says archived but paper.pdf is gone")
                elif _sha_file(p) != pdf.get("sha256"):
                    blocking.append("pdf_hash_mismatch: paper.pdf differs from the recorded sha256")
                t = kdir / TEXT_NAME
                tinfo = files.get("text") or {}
                if tinfo.get("status") != "extracted" or not t.exists():
                    blocking.append("text_missing: extracted paper.txt is required for "
                                    "quote verification (is pdftotext installed?)")
                elif _sha_file(t) != tinfo.get("sha256"):
                    blocking.append("text_hash_mismatch: paper.txt differs from the recorded sha256")
            elif pdf.get("status") == "unavailable":
                warnings.append(f"pdf_unavailable: {pdf.get('reason', '')}")
            else:
                blocking.append("pdf_missing: no archived PDF and no recorded unavailability "
                                "reason — run `aisci.citations fetch`")
            snap = files.get("snapshot") or {}
            sp = kdir / SNAP_NAME
            if not sp.exists():
                blocking.append("snapshot_missing: no saved copy of the source webpage")
            else:
                if snap.get("sha256") and _sha_file(sp) != snap.get("sha256"):
                    blocking.append("snapshot_hash_mismatch: source.html differs from the recorded sha256")
                if snap.get("http_status") != 200:
                    warnings.append(f"snapshot_http_{snap.get('http_status')}: source page "
                                    "returned a non-200 (attempt kept for the record)")

            if tex is not None and key not in cited:
                blocking.append("uncited: entry is in references.bib but never \\cite'd — "
                                "remove it or cite it (no decorative references)")
            usage = ev.get("usage") or []
            if not usage:
                blocking.append("no_usage: at least one usage record (claim + verbatim "
                                "supporting quote) is required — add with `aisci.citations usage`")
            else:
                hay, hay_src = _archived_text(kdir)
                hay_sq = _squash(hay)
                for i, u in enumerate(usage, 1):
                    if u.get("context_ok") is False:
                        blocking.append(f"context_flagged: usage {i} is flagged as NOT supporting "
                                        "the claim — fix the paper text or drop the citation")
                    q = _squash(u.get("supporting_quote", ""))
                    if len(q) < MIN_QUOTE_CHARS:
                        blocking.append(f"quote_too_short: usage {i} needs a substantial verbatim "
                                        f"passage (≥{MIN_QUOTE_CHARS} significant characters)")
                    elif not hay_sq:
                        warnings.append(f"quote_unverifiable: usage {i} — no archived text to check against")
                    elif q not in hay_sq:
                        blocking.append(f"quote_not_found: usage {i} supporting_quote does not appear "
                                        f"verbatim in the archived {hay_src or 'text'} — quote the real "
                                        f"paper (see citations/{key}/{TEXT_NAME})")
                    c = _squash(u.get("claim", ""))
                    if c and squashed_tex and c not in squashed_tex:
                        warnings.append(f"claim_not_in_tex: usage {i} claim text not found in the "
                                        "paper source (moved or edited since?)")

        entries_out.append({"key": key, "status": "verified" if not blocking else "blocked",
                            **info, "blocking": blocking, "warnings": warnings})

    index_blocking = [f"missing_bib_entry: '{k}' is \\cite'd in the paper but not in references.bib"
                      for k in sorted(cited - seen)] if tex is not None else []
    orphans = sorted(d.name for d in vault.iterdir()
                     if d.is_dir() and d.name not in seen) if vault.exists() else []

    total = len(entries_out)
    verified = sum(1 for x in entries_out if x["status"] == "verified")
    blocking_count = sum(len(x["blocking"]) for x in entries_out) + len(index_blocking)
    report.update({
        "counts": {"total": total, "verified": verified,
                   "blocked_entries": total - verified,
                   "warnings": sum(len(x["warnings"]) for x in entries_out)},
        "blocking": blocking_count,
        "index_blocking": index_blocking,
        "orphan_vault_dirs": orphans,
        "nothing_verified": total > 0 and verified == 0,
        "ok": blocking_count == 0,
        "entries": entries_out,
    })
    if write:
        vault.mkdir(parents=True, exist_ok=True)
        (vault / INDEX_NAME).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        report["index_path"] = str(vault / INDEX_NAME)
    return report


def _print_verify(report: dict) -> None:
    c = report.get("counts", {})
    print(f"[citations] {report['project']}: {c.get('total', 0)} references — "
          f"{c.get('verified', 0)} fully evidenced, {report.get('blocking', 0)} blocking issue(s)"
          + (" [offline]" if report.get("offline") else ""))
    for x in report.get("entries", []):
        for b in x.get("blocking", []):
            print(f"  [BLOCK] {x['key']:26s} {b}")
        for w in x.get("warnings", []):
            print(f"  [warn ] {x['key']:26s} {w}")
    for b in report.get("index_blocking", []):
        print(f"  [BLOCK] {b}")
    for o in report.get("orphan_vault_dirs", []):
        print(f"  [warn ] orphan vault dir (no bib entry): citations/{o}/")
    print(f"[citations] verdict: {'CLEAN ✓' if report.get('ok') else 'INCOMPLETE / MISMATCH ✗'}")
    if report.get("index_path"):
        print(f"[citations] index: {report['index_path']}")


# ─────────────────────────── CLI commands ───────────────────────────

def _load_bib(project_dir: Path) -> tuple[Path, str]:
    bib = find_bib(project_dir)
    if bib is None:
        bib = project_dir / "writeup" / "latex" / "references.bib"
        bib.parent.mkdir(parents=True, exist_ok=True)
        bib.write_text("", encoding="utf-8")
    return bib, bib.read_text(encoding="utf-8", errors="replace")


def _splice(text: str, spans, key: str, rendered: str) -> tuple[str, str]:
    hit = next(((s, e) for en, _raw, s, e in spans if en.get("key") == key), None)
    if hit:
        s, e = hit
        return text[:s] + rendered + text[e:], "replaced"
    sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + rendered + "\n", "appended"


def _report_artifacts(ev: dict) -> str:
    f = ev.get("files") or {}
    pdf, txt, snap = f.get("pdf") or {}, f.get("text") or {}, f.get("snapshot") or {}
    bits = [f"pdf={pdf.get('status', '?')}", f"text={txt.get('status', '?')}",
            f"snapshot=HTTP {snap.get('http_status')}"]
    if snap.get("wayback_url"):
        bits.append("wayback=saved")
    return ", ".join(bits)


def cmd_add(args) -> int:
    project_dir, pid = resolve_project(args.project)
    r = registry_meta(arxiv=args.arxiv, doi=args.doi)
    if "meta" not in r:
        print(f"[citations] cannot resolve id: {r.get('status')} — {r.get('detail', '')}")
        return 1
    meta = r["meta"]
    key = args.key or make_key(meta)
    bib, text = _load_bib(project_dir)
    spans = parse_bib_spans(text)
    prior = next((en for en, _raw, _s, _e in spans if en.get("key") == key), None)
    rendered = render_bib_entry(key, meta, fallback=prior)
    text, action = _splice(text, spans, key, rendered)
    bib.write_text(text, encoding="utf-8")
    entry = parse_bib_spans(rendered)[0][0]
    ev = ensure_citation(project_dir, key, meta, entry, rendered,
                         wayback=args.wayback, refetch=args.refetch)
    print(f"[citations] {action} @{key} in {bib}")
    print(f"  registry: {meta.get('source')} | {meta.get('title')}")
    print(f"  authors : {', '.join(meta.get('authors') or [])} ({meta.get('year')})")
    print(f"  vault   : {_report_artifacts(ev)}")
    print(rendered)
    print(f"  next    : record how the paper uses it —\n"
          f"    .venv/bin/python -m aisci.citations usage projects/{pid} --key {key} "
          f"--where ... --claim ... --quote ... --note ...")
    return 0


def _iter_targets(spans, key: str | None, want_all: bool):
    for entry, raw, s, e in spans:
        if want_all or entry.get("key") == key:
            yield entry, raw, s, e


def cmd_fetch(args) -> int:
    project_dir, pid = resolve_project(args.project)
    bib, text = _load_bib(project_dir)
    spans = parse_bib_spans(text)
    if not args.all and not args.key:
        print("[citations] fetch needs --key <bibkey> or --all")
        return 1
    failures = 0
    for entry, raw, _s, _e in _iter_targets(spans, args.key, args.all):
        key = entry.get("key", "")
        doi, axv = extract_doi(entry), extract_arxiv(entry)
        if not doi and not axv:
            print(f"  [skip] {key}: no DOI/arXiv id — regenerate with `aisci.citations add`")
            failures += 1
            continue
        ev = load_evidence(vault_dir(project_dir) / key)
        meta = None
        if ev and not args.refetch:
            reg = ev.get("registry") or {}
            ids = reg.get("ids") or {}
            if reg.get("authors") is not None and (
                    (axv and ids.get("arxiv") == axv) or (doi and ids.get("doi") == doi)):
                meta = reg
        if meta is None:
            r = registry_meta(arxiv=axv or None, doi=doi or None)
            if "meta" not in r:
                print(f"  [fail] {key}: {r.get('status')} — {r.get('detail', '')}")
                failures += 1
                continue
            meta = r["meta"]
        ev = ensure_citation(project_dir, key, meta, entry, raw,
                             wayback=args.wayback, refetch=args.refetch)
        print(f"  [ok  ] {key}: {_report_artifacts(ev)}")
    print(f"[citations] fetch done ({failures} failure(s)) — now run "
          f"`aisci.citations verify projects/{pid}`")
    return 1 if failures else 0


def cmd_rebib(args) -> int:
    """Regenerate existing bib entries canonically from the registry (same keys)."""
    project_dir, pid = resolve_project(args.project)
    bib, text = _load_bib(project_dir)
    spans = parse_bib_spans(text)
    if not args.all and not args.key:
        print("[citations] rebib needs --key <bibkey> or --all")
        return 1
    metas: dict[str, dict] = {}
    failures = 0
    for entry, _raw, _s, _e in _iter_targets(spans, args.key, args.all):
        key = entry.get("key", "")
        doi, axv = extract_doi(entry), extract_arxiv(entry)
        if not doi and not axv:
            print(f"  [skip] {key}: no DOI/arXiv id to regenerate from — find the real id "
                  "(arxiv/semantic-scholar MCP) and use `aisci.citations add --key`")
            failures += 1
            continue
        r = registry_meta(arxiv=axv or None, doi=doi or None)
        if "meta" not in r:
            print(f"  [fail] {key}: {r.get('status')} — {r.get('detail', '')}")
            failures += 1
            continue
        metas[key] = r["meta"]
    # splice back-to-front so spans stay valid
    changed = 0
    for entry, raw, s, e in sorted(_iter_targets(spans, args.key, args.all),
                                   key=lambda t: -t[2]):
        key = entry.get("key", "")
        if key not in metas:
            continue
        rendered = render_bib_entry(key, metas[key], fallback=entry)
        if rendered.strip() != raw.strip():
            changed += 1
            print(f"  [rewrite] {key}")
        text = text[:s] + rendered + text[e:]
    bib.write_text(text, encoding="utf-8")
    for entry, raw, _s, _e in parse_bib_spans(text):
        key = entry.get("key", "")
        if key in metas:
            ensure_citation(project_dir, key, metas[key], entry, raw,
                            wayback=args.wayback, refetch=args.refetch)
    print(f"[citations] rebib: {changed} entr{'y' if changed == 1 else 'ies'} rewritten, "
          f"{failures} failure(s)")
    return 1 if failures else 0


def cmd_exempt(args) -> int:
    """Narrow escape hatch for real sources with no registry record (whitepapers,
    standards): archive the primary source itself. Usage quotes are then verified
    against the archived document, exactly like a registry-backed citation — the
    exemption removes the registry comparison, never the evidence requirement."""
    project_dir, pid = resolve_project(args.project)
    bib, text = _load_bib(project_dir)
    hit = next((t for t in parse_bib_spans(text) if t[0].get("key") == args.key), None)
    if hit is None:
        print(f"[citations] no bib entry '{args.key}' in {bib}")
        return 1
    entry, raw, _s, _e = hit
    kdir = vault_dir(project_dir) / args.key
    kdir.mkdir(parents=True, exist_ok=True)
    ev = load_evidence(kdir) or {}

    code, final, body = _fetch_bytes(args.url, timeout=120.0)
    is_pdf = bool(body) and body[:5] == b"%PDF-"
    snap = {"path": SNAP_NAME, "url": args.url, "final_url": final, "http_status": code,
            "fetched_at": _now(), "wayback_url": _wayback(args.url) if args.wayback else None,
            "content_type": "application/pdf" if is_pdf else "text/html"}
    pdf = {"path": PDF_NAME, "source_url": final or args.url, "fetched_at": _now()}
    if body:
        # source.html is the literal fetch of the given URL (the "fish print"), even
        # when those bytes are a PDF — content_type above records what it really is.
        (kdir / SNAP_NAME).write_bytes(body)
        snap.update({"sha256": _sha_bytes(body), "bytes": len(body)})
    if is_pdf:
        (kdir / PDF_NAME).write_bytes(body)
        pdf.update({"status": "archived", "sha256": _sha_bytes(body), "bytes": len(body)})
    else:
        pdf.update({"status": "unavailable",
                    "reason": "exempt source URL did not serve a PDF — snapshot archived"})
    text_info = extract_text(kdir) if is_pdf else {"path": TEXT_NAME, "status": "no_pdf"}
    if code != 200 or not body:
        print(f"[citations] could not archive {args.url} (HTTP {code}) — an exemption "
              "without an archived primary source is not accepted")
        return 1

    ev.update({
        "key": args.key,
        "bib_entry_sha256": entry_sha(raw),
        "identity": {"arxiv": "", "doi": ""},
        "registry": {"source": "manual-exempt", "title": entry.get("title", ""),
                     "authors": bibcheck.split_bib_authors(entry.get("author", "")),
                     "year": entry.get("year", ""), "ids": {"arxiv": "", "doi": ""},
                     "exempt_reason": args.reason, "exempt_url": args.url,
                     "fetched_at": _now()},
        "files": {"pdf": pdf, "text": text_info, "snapshot": snap},
    })
    ev.setdefault("usage", [])
    save_evidence(kdir, ev)
    print(f"[citations] exempted @{args.key}: {args.reason}")
    print(f"  archived: {_report_artifacts(ev)}")
    print("  usage records (with quotes from the archived document) are still required.")
    return 0


def cmd_usage(args) -> int:
    project_dir, pid = resolve_project(args.project)
    kdir = vault_dir(project_dir) / args.key
    ev = load_evidence(kdir)
    if ev is None:
        print(f"[citations] no evidence.json for '{args.key}' — run "
              f"`aisci.citations fetch projects/{pid} --key {args.key}` (or `add`) first")
        return 1
    hay, hay_src = _archived_text(kdir)
    q = _squash(args.quote)
    if len(q) < MIN_QUOTE_CHARS:
        print(f"[citations] quote too short — provide a substantial verbatim passage "
              f"(≥{MIN_QUOTE_CHARS} significant characters)")
        return 2
    if not hay:
        print("[citations] no archived text (pdf/snapshot) to verify the quote against — "
              "run fetch first")
        return 2
    if q not in _squash(hay):
        print(f"[citations] REFUSED: the quote does not appear verbatim in the archived "
              f"{hay_src} — copy it exactly from citations/{args.key}/{TEXT_NAME} "
              "(never paraphrase, never quote from memory)")
        return 2
    tex = find_main_tex(project_dir)
    if tex is not None and args.claim:
        tex_sq = _squash(_strip_tex_comments(tex.read_text(encoding="utf-8", errors="replace")))
        if _squash(args.claim) not in tex_sq:
            print("  [warn] claim text not found in the paper source — make sure it is the "
                  "actual sentence citing this work")
    ev.setdefault("usage", []).append({
        "where": args.where, "claim": args.claim, "supporting_quote": args.quote,
        "note": args.note, "context_ok": not args.context_flag,
        "verified_against": hay_src, "added_at": _now(),
    })
    save_evidence(kdir, ev)
    n = len(ev["usage"])
    print(f"[citations] usage {n} recorded for {args.key} (quote verified in {hay_src})")
    if args.context_flag:
        print("  flagged context_ok=false — verify will BLOCK until the paper text is fixed")
    return 0


def cmd_verify(args) -> int:
    report = run_verify(args.project, offline=args.offline, refresh=args.refresh,
                        write=True)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_verify(report)
    return 0 if report.get("ok") else 1


def cmd_status(args) -> int:
    project_dir, pid = resolve_project(args.project)
    p = vault_dir(project_dir) / INDEX_NAME
    if not p.exists():
        print(f"[citations] no index yet — run `aisci.citations verify projects/{pid}`")
        return 1
    _print_verify(json.loads(p.read_text(encoding="utf-8")))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="aisci.citations",
        description="Per-citation evidence vault: registry-generated bib entries, "
                    "archived PDFs + page snapshots, and verbatim-quote usage evidence.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("project", help="project id or path to projects/<id>")

    p = sub.add_parser("add", help="resolve an id, generate the canonical bib entry, archive artifacts")
    common(p)
    p.add_argument("--arxiv", default=None, help="arXiv id, e.g. 2604.06688")
    p.add_argument("--doi", default=None, help="DOI, e.g. 10.1145/xxxx")
    p.add_argument("--key", default=None, help="bib key to use/replace (default: generated)")
    p.add_argument("--wayback", action="store_true", help="also save the page to the Wayback Machine")
    p.add_argument("--refetch", action="store_true", help="re-download artifacts even if present")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("fetch", help="archive artifacts + evidence for existing bib entries (no bib edits)")
    common(p)
    p.add_argument("--key", default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--wayback", action="store_true")
    p.add_argument("--refetch", action="store_true")
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("rebib", help="regenerate existing bib entries canonically from the registry")
    common(p)
    p.add_argument("--key", default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--wayback", action="store_true")
    p.add_argument("--refetch", action="store_true")
    p.set_defaults(fn=cmd_rebib)

    p = sub.add_parser("exempt", help="archive a registry-less primary source (whitepaper/standard) as a citation's evidence")
    common(p)
    p.add_argument("--key", required=True)
    p.add_argument("--url", required=True, help="URL of the primary source document/page")
    p.add_argument("--reason", required=True, help="why no DOI/arXiv id exists for this source")
    p.add_argument("--wayback", action="store_true")
    p.set_defaults(fn=cmd_exempt)

    p = sub.add_parser("usage", help="record how the paper uses a citation (quote is verified immediately)")
    common(p)
    p.add_argument("--key", required=True)
    p.add_argument("--where", required=True, help="location in the paper, e.g. 'Sec. 2 Related Work'")
    p.add_argument("--claim", required=True, help="the sentence in paper.tex that cites this work")
    p.add_argument("--quote", required=True, help="VERBATIM passage from the cited paper that supports it")
    p.add_argument("--note", required=True, help="one line on how the quote supports the claim")
    p.add_argument("--context-flag", action="store_true",
                   help="record that the citation does NOT support the claim (verify will block)")
    p.set_defaults(fn=cmd_usage)

    p = sub.add_parser("verify", help="verify the whole vault; writes citations/index.json")
    common(p)
    p.add_argument("--offline", action="store_true", help="local files + recorded registry snapshots only")
    p.add_argument("--refresh", action="store_true", help="re-fetch registry records instead of using evidence snapshots")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("status", help="print the last verify verdict")
    common(p)
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
