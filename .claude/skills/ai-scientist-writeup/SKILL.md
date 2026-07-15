---
name: ai-scientist-writeup
description: Stage 3 of the AI Scientist pipeline — gather citations and write the experiment results into a rigorous, publication-quality LaTeX paper, compile it to PDF, and reflect/fix until clean. Use after experiments have produced results and plots and the user wants the paper.
---

# Stage 3 — Writeup

Turn `projects/<id>/experiment/` results + plots into a compiled, **publication-quality
paper aimed at the standard of a top venue / journal**.

## Aim high, don't pre-constrain
- **Target top-journal quality**: a complete, self-contained, rigorous paper — thorough
  related work, a precise method/setup, experiments with real numbers and uncertainty,
  honest analysis, and a substantive discussion.
- **Do NOT impose a page limit or a venue format up front.** Let the length follow the
  content. It is fine if the paper *ends up* compact enough for a conference, but that is
  an outcome, not a starting constraint. Never trim real content just to hit a page count.
- **Venue-neutral.** Do not brand the paper as "under review at <venue>" or print a
  conference banner. Write it as a standalone manuscript. Pick a venue only if/when the
  user asks.

## Authoritative reference (for structure/phrasing only)
`vendor/AI-Scientist-v2/ai_scientist/perform_writeup.py` and `gather_citations` show the
upstream process. The vendored `blank_icml_latex/` and `blank_icbinb_latex/` templates
exist if you ever want a specific venue format, but they are **not** the default and they
carry venue branding — prefer the neutral setup below.

## Prerequisites
- LaTeX toolchain: `pdflatex`/`bibtex` (TeX Live or MacTeX), `poppler` (`pdftoppm`,
  `pdftotext`), optionally `chktex` (lint). `scripts/doctor.sh` checks these. Missing
  font/style packages can be added without admin rights via
  `tlmgr --usermode install <pkg>` (e.g. on a basictex install).

## Procedure
1. **Set up** `projects/<id>/writeup/latex/`. Use a clean, **venue-neutral** preamble —
   no conference style file, no "under review" banner. A good default:
   ```latex
   \documentclass[11pt]{article}
   \usepackage[margin=1in]{geometry}
   \usepackage{graphicx,booktabs,amsmath,amssymb,natbib,hyperref,xcolor}
   \usepackage[capitalize]{cleveref}
   \graphicspath{{../figures/}}
   ```
   Put figures in `projects/<id>/writeup/figures/`.
2. **Gather citations — NEVER hand-write a bib entry.** Find candidate papers via the
   `mcp__semantic-scholar__*` / `mcp__arxiv__*` MCP tools (or WebSearch / the Semantic
   Scholar API via `curl`), but the *only* thing you take from the search is the
   **arXiv id or DOI**. The BibTeX itself is generated from the authoritative registry
   record (title, authors, year — no hallucinated metadata is possible by construction):
   ```bash
   .venv/bin/python -m aisci.citations add projects/<id> --arxiv <id> [--key <bibkey>]
   .venv/bin/python -m aisci.citations add projects/<id> --doi <doi>   [--key <bibkey>]
   ```
   Each `add` also archives the citation's **evidence vault** under
   `writeup/citations/<bibkey>/`: the paper's PDF, its extracted text, and a snapshot
   of the source webpage. Typing an author list or title into `references.bib` by hand
   is a protocol violation — if an entry needs fixing, re-run `add` (same `--key`) or
   `aisci.citations rebib`.
   **Cite actively, not minimally.** A top-journal paper situates itself in a broad
   literature; err on the side of engaging *more* prior work, never less. Run a
   separate, explicit search pass for each of these categories:
   - direct prior work on the same question — including anything that could be read as
     scooping, partially anticipating, or contradicting the result;
   - the original source of every method, model, dataset, metric, and baseline used;
   - the theoretical / background work the argument rests on;
   - adjacent lines a reader would expect the paper positioned against (same phenomenon
     with different tools; same tools on a different phenomenon);
   - recent work (≈ last 2 years) showing where the field is now.
   Mature papers typically carry ~30–60 references; treat a short bibliography as a
   symptom of incomplete coverage, not a virtue — go back and search the missing
   categories rather than accepting it. The anti-padding rule that keeps this honest:
   every citation must be **load-bearing** — attached to a specific point in the text
   where it supports, informs, or contrasts with a specific claim, with at least a
   phrase saying *how* it relates. Never add a reference you haven't verified or can't
   say something concrete about; a bare citation dump (`[3,7,12,19]` with no
   discussion) is padding, not coverage.
   Every reference must carry a DOI or arXiv id (the vault requires one); step 7's
   deterministic gates (`aisci.citations verify` + `aisci.bibcheck`) are hook-enforced,
   so an unevidenced or metadata-drifted entry cannot ship.
3. **Write the paper** section by section, grounded **only** in `experiment/` results:
   Title, Abstract, Introduction, Related Work, Method, Experimental Setup, Experiments &
   Results (real numbers, mean±std, from `experiment_results/summary.json`; figures from
   `experiment/plots/`), Discussion, Limitations, Conclusion (+ Appendix if useful — the
   appendix has no length concern). Report failures and nuance **honestly**; a strong
   honest result (positive, negative, or mixed) is the goal.
4. **Insert figures** by copying the plots into the figures dir and `\includegraphics`-ing
   them at a size that reads well (don't shrink to save space). Use the saved
   `<fig>.caption.txt` as a starting caption and expand it to be self-contained.
5. **Compile** to PDF, iterating on errors:
   ```bash
   .venv/bin/python -m aisci.latex projects/<id>/writeup/latex paper.tex
   ```
   Fix LaTeX errors, undefined refs/citations, and overfull boxes. Run `chktex` if present.
6. **Reflect** (several rounds): re-read the compiled PDF (open `paper.pdf` with Read — you
   can see it), check figures render, captions match and are self-contained, every claim is
   supported, the prose is clear and complete, and the argument is tight. Revise and
   recompile. Improve quality; do **not** cut substance to hit a length.
7. **Verify citations deterministically (enforced, two layers).** After the paper text
   is stable, complete the per-citation evidence and run both gates:
   1. **Usage evidence** — for *every* reference, record how the paper uses it, with a
      **verbatim quote from the archived paper text** (open
      `writeup/citations/<key>/paper.txt`, copy the passage exactly — never paraphrase,
      never quote from memory; the command refuses a quote that isn't really there):
      ```bash
      .venv/bin/python -m aisci.citations usage projects/<id> --key <bibkey> \
        --where "Sec. 2 Related Work" --claim "<the sentence in paper.tex citing it>" \
        --quote "<verbatim passage from the cited paper>" --note "<how it supports the claim>"
      ```
      If, while doing this, you find the citation does NOT support the claim, fix the
      paper text (or drop the citation) — or record `--context-flag` so the gate blocks
      until it is fixed. Never write a quote that stretches the source.
   2. **Vault verification** — checks every entry field-by-field against the registry
      (strict title, full author list, year), that the PDF/snapshot/text artifacts
      exist and match their recorded hashes, that every entry is actually `\cite`'d,
      and that every usage quote appears verbatim in the archived text. Writes
      `writeup/citations/index.json`:
      ```bash
      .venv/bin/python -m aisci.citations verify projects/<id>
      ```
   3. **Existence backstop** — the original checker still runs (it also covers strict
      title/author/year now), writing `writeup/bibcheck.json`:
      ```bash
      .venv/bin/python -m aisci.bibcheck projects/<id>
      ```
   Fix every blocking issue *at the source* (regenerate the entry with
   `aisci.citations add`/`rebib`, complete the vault, correct the paper text) and
   re-run until **both** report CLEAN. The `enforce_bibcheck` and `enforce_citations`
   hooks block marking this stage done until fresh, clean reports exist — and the
   citations hook re-runs the offline checks itself, so hand-editing a report file
   achieves nothing. Re-verify after the *final* compile: the index is stale the
   moment `references.bib` or the main `.tex` changes.
8. **Finalize:** copy the final PDF to `projects/<id>/writeup/paper.pdf`. Record the key
   writeup decisions (`aisci.run decide …`), then update `state.json`:
   `stage="writeup"`, `status="done"`.

## Guardrails
- Every number in the paper must trace to a file in `experiment/`. If a result is missing,
  run it (back to Stage 2) or omit the claim — do not fabricate.
- Every citation must be a real, findable paper — and **load-bearing**: tied in the text
  to a specific claim it supports or contrasts with. Breadth comes from searching more
  categories of related work, never from decorative citations. `aisci.bibcheck` (step 7,
  hook-enforced) is the deterministic proof that none are fabricated — never route around
  it by hand-editing `bibcheck.json`; fix the real reference instead.
- Quality over brevity: never remove real content, experiments, or nuance to satisfy a
  page budget. There is no page budget.

## Output to the user
Report: compile status (clean?), figure list, citation count **and both citation
verdicts** (`citations verify`: N fully evidenced / 0 blocking; `bibcheck`: N verified /
0 blocking), page count (as an *observation*, not a target), and the path to
`paper.pdf`. Offer to proceed to `/ai-scientist-review` (or to the improvement loop,
`/ai-scientist-improve`).
