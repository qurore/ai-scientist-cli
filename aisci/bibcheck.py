"""Deterministic citation verifier for a project's ``references.bib``.

The writeup/review skills tell *you* (the agent) to verify every citation via the
arxiv / semantic-scholar MCP and never invent references. That is a discipline, not
a guarantee. This module is the deterministic backstop: it parses the BibTeX file
and checks each entry against **public bibliographic APIs** — Crossref (for DOIs and
title search) and the arXiv API (for arXiv ids) — with **no LLM and no MCP** in the
loop. It catches the concrete hallucination signals: a DOI or arXiv id that does not
resolve, a title-only reference that no real paper matches, and — the classic
"real paper, hallucinated metadata" failure — a resolvable id whose recorded title,
author list, or year does not match the registry record. Title comparison is strict
(no substring shortcut: a fabricated subtitle is a mismatch) and the author list is
compared name by name (family names must match; given names may abbreviate to an
initial but may not change).

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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Contact string for the API "polite pools" (Crossref, arXiv). Non-secret; helps them
# rate-limit us fairly (the anonymous pool 429s under load). Pulled from the
# environment, else from the repo's .env (where the curator keeps non-secret metadata).
def _env_contact() -> str:
    v = os.environ.get("CROSSREF_MAILTO") or os.environ.get("AUTHOR_EMAIL")
    if v:
        return v
    envf = REPO / ".env"
    if envf.exists():
        try:
            for line in envf.read_text().splitlines():
                m = re.match(r"\s*(?:export\s+)?(?:CROSSREF_MAILTO|AUTHOR_EMAIL)\s*=\s*[\"']?([^\"'#\s]+)",
                             line)
                if m:
                    return m.group(1)
        except Exception:
            pass
    return ""


_MAILTO = _env_contact()
USER_AGENT = (
    "ai-scientist-cli/bibcheck (citation existence check; "
    + (f"mailto:{_MAILTO})" if _MAILTO else "https://github.com/)")
)

# Statuses that mean "this is very likely a fabricated / hallucinated citation" and so
# should block finalizing the paper. See classify() below. title/author mismatches are
# blocking: an id that resolves to a real paper whose title or author list differs from
# the bib entry is exactly how hallucinated metadata ships (it happened; see the
# citations module for the per-citation evidence vault built in response).
BLOCKING = {"not_found", "unresolved", "title_mismatch", "author_mismatch"}
# Non-blocking, but surfaced: a preprint/published year skew, an entry with nothing to
# query on, a lookup we couldn't run, or a vault-backed manual exemption (a whitepaper/
# standard with no registry record — legitimate only because `aisci.citations exempt`
# requires the primary source itself to be archived).
WARNING = {"year_mismatch", "no_query", "network_error", "exempt"}


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


# ─────────────────────────── title + author matching ───────────────────────────

# Characters NFKD can't fold usefully: German ß, ligatures/strokes, and Greek letters
# (a registry title 'p+ε' must match a bib title spelling out 'p + epsilon').
_TRANSLIT = {"ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ø": "o", "Ø": "O",
             "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "þ": "th", "Þ": "Th", "ð": "d",
             "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
             "ϵ": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota",
             "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "π": "pi",
             "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi",
             "χ": "chi", "ψ": "psi", "ω": "omega", "Γ": "Gamma", "Δ": "Delta",
             "Θ": "Theta", "Λ": "Lambda", "Π": "Pi", "Σ": "Sigma", "Φ": "Phi",
             "Ψ": "Psi", "Ω": "Omega"}


def _ascii_fold(s: str) -> str:
    """Fold accents/ligatures/Greek to plain ASCII so 'Schrödinger' == 'Schrodinger'."""
    s = "".join(_TRANSLIT.get(ch, ch) for ch in (s or ""))
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


# LaTeX-isms that survive _clean's brace stripping (e.g. 'Toma\vsev' from
# 'Toma{\v s}ev', 'Reitwie\ssner' from 'Reitwie{\ss}ner', '$\epsilon$' in titles).
# Normalized for MATCHING only — never used to render anything.
_TEX_WORDS = re.compile(
    r"\\(varepsilon|epsilon|alpha|beta|gamma|delta|zeta|theta|iota|kappa|lambda|sigma|"
    r"upsilon|omicron|omega|mu|nu|xi|pi|rho|tau|phi|chi|psi|eta|ss|ae|oe|aa|o|l|i|j)")
_TEX_ACCENTS = re.compile(r"\\([vcuHkbdr'\"`^~=.])")


def _delatex(s: str) -> str:
    if "\\" not in (s or ""):
        return s or ""
    s = _TEX_WORDS.sub(lambda m: "epsilon" if m.group(1) == "varepsilon" else m.group(1), s)
    s = _TEX_ACCENTS.sub("", s)                # accent commands: keep the modified letter
    return re.sub(r"\\[a-zA-Z]+\s*", " ", s)   # any remaining command: drop it


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _ascii_fold(_delatex(title)).lower()).strip()


def titles_match_strict(bib_title: str, candidates) -> tuple[bool, str]:
    """Field-level title check for a resolved entry: normalized equality or >=0.97
    similarity against any candidate. Deliberately NO substring rule — a real title
    plus a fabricated subtitle must come out a mismatch, not a match. ``candidates``
    may include a with-subtitle variant (Crossref stores subtitles separately)."""
    nb = _norm(bib_title)
    best_title, best_ratio = "", 0.0
    for cand in candidates or []:
        nc = _norm(cand)
        if not nb or not nc:
            continue
        if nb == nc:
            return True, cand
        r = difflib.SequenceMatcher(None, nb, nc).ratio()
        if r > best_ratio:
            best_title, best_ratio = cand, r
    return best_ratio >= 0.97, best_title


def _name_tokens(name: str) -> list[str]:
    s = _ascii_fold(_delatex(name or "")).lower().replace("-", " ").replace(".", " ")
    return [t for t in re.sub(r"[^a-z\s]", "", s).split() if t]


def split_bib_authors(field: str) -> list[str]:
    """Split a (brace-stripped) BibTeX author field on ' and ' into display names,
    normalizing 'Last, First' to 'First Last'. A trailing 'others' is kept as-is."""
    names = []
    for raw in re.split(r"\s+and\s+", (field or "").strip(), flags=re.IGNORECASE):
        raw = raw.strip().strip(",").strip()
        if not raw:
            continue
        if raw.lower() in ("others", "et al"):
            names.append("others")
            continue
        if "," in raw:
            fam, _, giv = raw.partition(",")
            raw = (giv.strip() + " " + fam.strip()).strip()
        names.append(raw)
    return names


def names_match(a: str, b: str) -> bool:
    """One person, two spellings? Family name (last token) must match exactly; given
    names may abbreviate to an initial ('J.' vs 'John') but may not change ('Yuxuan'
    vs 'Xuan' is a mismatch). Middle tokens are only compared when both sides have
    them, so 'John Smith' still matches 'John A. Smith'."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True

    def tok_ok(x: str, y: str) -> bool:
        return x == y or (x[0] == y[0] and (len(x) == 1 or len(y) == 1))

    def structural(ga: list[str], gb: list[str]) -> bool:
        if not ga or not gb:  # one side wrote the family name only — accept
            return True
        if not tok_ok(ga[0], gb[0]):
            return False
        return all(tok_ok(x, y) for x, y in zip(ga[1:], gb[1:]))

    if ta[-1] == tb[-1] and structural(ta[:-1], tb[:-1]):
        return True
    # Registry metadata itself is occasionally noisy (Crossref lists 'Penno k' for
    # 'Pennock'); absorb single-typo noise with a tight full-name similarity floor.
    # Genuinely different names stay far below it ('Yuxuan Liu' vs 'Xuan Liu' ≈ 0.87).
    return difflib.SequenceMatcher(None, "".join(ta), "".join(tb)).ratio() >= 0.93


def author_lists_match(bib_field: str, registry_authors: list) -> tuple[bool, str]:
    """Positional comparison of the bib author list against the registry's. A trailing
    'and others' truncation is tolerated; every listed name must still match."""
    if not registry_authors:
        return True, "registry lists no authors"
    bib = split_bib_authors(bib_field)
    if not bib:
        return False, "bib entry lists no authors"
    truncated = bib[-1] == "others"
    if truncated:
        bib = bib[:-1]
    if not truncated and len(bib) != len(registry_authors):
        return False, (f"author count differs: bib lists {len(bib)}, "
                       f"registry lists {len(registry_authors)}")
    if len(bib) > len(registry_authors):
        return False, "bib lists more authors than the registry record"
    for i, (a, b) in enumerate(zip(bib, registry_authors)):
        if not names_match(a, b):
            return False, f"author {i + 1} differs: bib '{a}' vs registry '{b}'"
    return True, "authors match"


# ─────────────────────────── HTTP + API lookups ───────────────────────────

# Be a polite API client: a per-host minimum gap between requests keeps us out of the
# rate-limiter, and we back off (honoring Retry-After) instead of giving up on a 429/503.
# arXiv asks for ~1 request / 3 s; a global 0.6 s gap reliably earns sustained 429s there.
_MIN_INTERVAL = float(os.environ.get("BIBCHECK_MIN_INTERVAL", "0.6"))
_ARXIV_INTERVAL = float(os.environ.get("BIBCHECK_ARXIV_INTERVAL", "3.0"))
_RATE: dict[str, float] = {}


def _throttle(url: str):
    host = urllib.parse.urlparse(url).netloc.lower()
    interval = _ARXIV_INTERVAL if "arxiv.org" in host else _MIN_INTERVAL
    wait = interval - (time.monotonic() - _RATE.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _RATE[host] = time.monotonic()


def _http(url: str, timeout: float, accept: str = "application/json", retries: int = 3):
    """Return (code, text). code is the HTTP status (int) or None on a connection
    error. On an HTTP error status the body is None. Distinguishes a definitive 404
    (paper does not exist) from a transport failure (offline / rate-limited). Retries
    a rate-limit/transient status (429/503) with backoff, honoring Retry-After."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    backoff = 1.0
    for attempt in range(retries + 1):
        _throttle(url)
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


def _crossref_msg_meta(msg: dict) -> dict:
    """Normalize a Crossref work record to the registry-meta shape shared with arXiv:
    {source, title, titles (with-subtitle variants), authors (full-name strings), year}."""
    title = _clean((msg.get("title") or [""])[0])
    subtitle = _clean((msg.get("subtitle") or [""])[0])
    # Handbook/book chapters often embed 'Chapter 51 ' in the Crossref title; papers
    # legitimately cite them without it.
    chapterless = re.sub(r"^chapter\s+\d+[:.\s]\s*", "", title, flags=re.IGNORECASE)
    titles = [t for t in (title, f"{title}: {subtitle}" if subtitle else "",
                          chapterless if chapterless != title else "") if t]
    authors = []
    for a in msg.get("author") or []:
        full = " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name", "")
        if full:
            authors.append(full)
    year = None
    for k in ("issued", "published-print", "published-online", "created"):
        parts = ((msg.get(k) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            year = int(parts[0])
            break
    return {"source": "crossref", "title": titles[-1] if titles else "", "titles": titles,
            "authors": authors, "year": year, "doi": msg.get("DOI", ""),
            "container": _clean((msg.get("container-title") or [""])[0]),
            "type": msg.get("type", ""), "volume": msg.get("volume", ""),
            "number": msg.get("issue", ""), "pages": msg.get("page", "")}


def _crossref_doi(doi: str, timeout: float) -> dict:
    """Resolve a DOI to registry metadata. Returns {"meta": {...}} on success, else a
    {"status": ...} error dict (not_found / network_error)."""
    q = urllib.parse.quote(doi, safe="")
    url = f"https://api.crossref.org/works/{q}"
    if _MAILTO:
        url += "?mailto=" + urllib.parse.quote(_MAILTO)
    code, text = _http(url, timeout)
    if code == 404:
        return {"status": "not_found", "source": "crossref", "detail": f"DOI {doi} not in Crossref"}
    if code == 200 and text:
        try:
            return {"meta": _crossref_msg_meta(json.loads(text).get("message", {}))}
        except Exception:
            return {"status": "network_error", "source": "crossref", "detail": "unparseable response"}
    return {"status": "network_error", "source": "crossref", "detail": f"HTTP {code}"}


_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def _arxiv_entry_meta(entry_el) -> dict:
    """Normalize one arXiv Atom entry to the shared registry-meta shape."""
    title = _clean(entry_el.findtext(f"{_ATOM}title") or "")
    authors = [_clean(a.findtext(f"{_ATOM}name") or "")
               for a in entry_el.findall(f"{_ATOM}author")]
    published = entry_el.findtext(f"{_ATOM}published") or ""  # v1 date — stable
    eid = entry_el.findtext(f"{_ATOM}id") or ""
    m = re.search(r"abs/(\S+?)(v\d+)?$", eid)
    pc = entry_el.find(f"{_ARXIV_NS}primary_category")
    return {"source": "arxiv", "title": title, "titles": [title],
            "authors": [a for a in authors if a],
            "year": int(published[:4]) if published[:4].isdigit() else None,
            "arxiv": m.group(1) if m else "",
            "primary_class": pc.get("term") if pc is not None else ""}


def _arxiv_entries(atom_xml: str):
    """Parse an arXiv Atom feed into meta dicts. None = unparseable (treat as network
    trouble); [] = the feed parsed but matched nothing (a real not-found)."""
    try:
        root = ET.fromstring(atom_xml)
    except Exception:
        return None
    out = []
    for entry in root.findall(f"{_ATOM}entry"):
        # arXiv returns a synthetic "Error" entry (id .../api/errors) when nothing matches
        if "/api/errors" in (entry.findtext(f"{_ATOM}id") or ""):
            continue
        out.append(_arxiv_entry_meta(entry))
    return out


def _arxiv_id(arxiv: str, timeout: float) -> dict:
    """Resolve an arXiv id to registry metadata. {"meta": {...}} or {"status": ...}."""
    url = "http://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv) + "&max_results=1"
    code, text = _http(url, timeout, accept="application/atom+xml")
    if code is None or text is None:
        return {"status": "network_error", "source": "arxiv", "detail": f"HTTP {code}"}
    entries = _arxiv_entries(text)
    if entries is None:
        return {"status": "network_error", "source": "arxiv", "detail": "unparseable response"}
    if not entries:
        return {"status": "not_found", "source": "arxiv", "detail": f"arXiv id {arxiv} returned no entry"}
    return {"meta": entries[0]}


def compare_meta(entry: dict, meta: dict) -> dict:
    """Field-level comparison of a bib entry against a registry record. This is the
    whole point: an id that resolves is not enough — the *metadata the paper prints*
    must be what the registry says. Returns a status dict (verified / title_mismatch /
    author_mismatch / year_mismatch)."""
    base = {"source": meta.get("source", ""), "matched_title": meta.get("title", ""),
            "matched_authors": meta.get("authors", []), "matched_year": meta.get("year")}
    title = entry.get("title", "")
    ok_t, _ = titles_match_strict(title, meta.get("titles") or [meta.get("title", "")])
    if title and not ok_t:
        return {**base, "status": "title_mismatch",
                "detail": f"id resolves to '{meta.get('title')}' but the bib title differs "
                          f"beyond metadata noise (fabricated subtitle / wrong paper?)"}
    ok_a, why = author_lists_match(entry.get("author", ""), meta.get("authors") or [])
    if not ok_a:
        return {**base, "status": "author_mismatch", "detail": why}
    m = re.search(r"\d{4}", entry.get("year", "") or "")
    if m and meta.get("year") and int(m.group(0)) != int(meta["year"]):
        return {**base, "status": "year_mismatch",
                "detail": f"bib year {m.group(0)} vs registry year {meta['year']} "
                          f"(preprint/published skew?)"}
    return {**base, "status": "verified"}


def _title_search(entry: dict, timeout: float) -> dict:
    """Id-less entry: try to find *any* real paper with a strictly matching title,
    across Crossref then arXiv, and compare the full metadata of each candidate. A
    title that matches a real paper whose authors differ is reported as
    ``author_mismatch``, not verified. Only after both searches come up empty (and the
    network worked) do we call it ``unresolved`` — the hallucination signal for
    reference lists without ids."""
    title = entry.get("title", "")
    reached = False
    near_miss = None
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
                meta = _crossref_msg_meta(item)
                if not titles_match_strict(title, meta["titles"])[0]:
                    continue
                res = compare_meta(entry, meta)
                res["source"] = "crossref-search"
                res["_meta"] = meta
                if res["status"] in ("verified", "year_mismatch"):
                    return res
                near_miss = res
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
        for meta in _arxiv_entries(text2) or []:
            if not titles_match_strict(title, meta["titles"])[0]:
                continue
            res = compare_meta(entry, meta)
            res["source"] = "arxiv-search"
            res["_meta"] = meta
            if res["status"] in ("verified", "year_mismatch"):
                return res
            near_miss = near_miss or res
    if near_miss:
        return near_miss
    if not reached:
        return {"status": "network_error", "source": "search", "detail": "no search endpoint reachable"}
    return {"status": "unresolved", "source": "search",
            "detail": "no Crossref/arXiv paper matches this title"}


# ─────────────────────────── per-entry classification ───────────────────────────

def classify(entry: dict, timeout: float) -> dict:
    """Resolve the entry's registry record and compare field by field. The returned
    dict may carry ``_meta`` (the fetched registry record) for the caller to cache."""
    title = entry.get("title", "")
    doi = extract_doi(entry)
    arxiv = extract_arxiv(entry)
    res: dict = {}
    if doi:
        r = _crossref_doi(doi, timeout)
        if "meta" in r:
            res = compare_meta(entry, r["meta"])
            res["_meta"] = r["meta"]
        elif r.get("status") == "not_found" and (arxiv or title):
            # If a DOI genuinely isn't in Crossref, it may still be a real (e.g.
            # arXiv-only) paper — fall through rather than crying fabrication outright.
            res = {}
        else:
            res = r
    if not res and arxiv:
        r = _arxiv_id(arxiv, timeout)
        if "meta" in r:
            res = compare_meta(entry, r["meta"])
            res["_meta"] = r["meta"]
        elif r.get("status") == "not_found" and title:
            res = {}
        else:
            res = r
    if not res:
        if title:
            res = _title_search(entry, timeout)
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


def _vault_exemption(project_dir: Path, key: str) -> str:
    """A citation may be exempted from registry lookup only through the citations
    vault (``aisci.citations exempt``): the exemption itself must carry the archived
    primary source, so it is never a free pass. Returns the recorded reason, or ''."""
    p = project_dir / "writeup" / "citations" / key / "evidence.json"
    try:
        reg = (json.loads(p.read_text()).get("registry") or {})
        if reg.get("source") == "manual-exempt":
            return reg.get("exempt_reason") or "exempt"
    except Exception:
        pass
    return ""


def entry_keys(entry: dict) -> list[str]:
    """Stable identity keys for an entry, used to cache **registry metadata** so a
    re-run (the fix-and-recheck loop) doesn't re-hit the API for papers already
    resolved. Only the fetch is cached — the field-level comparison re-runs locally
    every time, so an entry edited to disagree with its cached registry record is
    still caught (a blind 'verified' cache once let exactly that slip through)."""
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

    # Cache format: {"meta": {identity_key: registry_meta}}. Older caches used a blind
    # {"verified": ...} shape that skipped comparison on hit — reading only "meta" here
    # invalidates those wholesale.
    cache_path = project_dir / "writeup" / ".bibcheck_cache.json"
    cache: dict = {}
    if use_cache and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text()).get("meta", {})
        except Exception:
            cache = {}

    entries = parse_bib(bib.read_text(encoding="utf-8", errors="replace"))
    results = []
    for e in entries:
        reason = _vault_exemption(project_dir, e.get("key", ""))
        if reason:
            results.append({"key": e.get("key", ""), "title": e.get("title", ""),
                            "doi": extract_doi(e), "arxiv": extract_arxiv(e),
                            "status": "exempt", "source": "citations-vault",
                            "detail": f"manual primary-source exemption: {reason}"})
            continue
        keys = entry_keys(e)
        hit = next((cache[k] for k in keys if k in cache and isinstance(cache[k], dict)
                    and cache[k].get("authors") is not None), None)
        out = {"key": e.get("key", ""), "title": e.get("title", ""),
               "doi": extract_doi(e), "arxiv": extract_arxiv(e)}
        if hit is not None:  # registry record cached — re-run the comparison locally
            cmp = compare_meta(e, hit)
            cmp["source"] = (hit.get("source", "") or "registry") + "+cache"
            out.update(cmp)
        else:
            out = classify(e, timeout)
            meta = out.pop("_meta", None)
            # Cache only records that agree with the entry (a mismatch must be fixed
            # and will be re-fetched on the recheck anyway).
            if meta and out.get("status") in ("verified", "year_mismatch"):
                for k in keys:
                    cache[k] = meta
        results.append(out)

    if use_cache:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"meta": cache}, indent=2))
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
