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
2. **Gather citations.** Build `references.bib` from real papers via the
   `mcp__semantic-scholar__*` / `mcp__arxiv__*` MCP tools (or WebSearch / the Semantic
   Scholar API via `curl`). Verify each exists — **never invent citations**.
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
   Verifying each citation by hand via the MCP is the primary defense; step 7 adds a
   **deterministic backstop** (`aisci.bibcheck`) that catches any fabricated entry that
   slips through, so build the `.bib` with real DOIs / arXiv ids where possible.
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
7. **Verify citations deterministically (enforced).** Before finalizing, run the
   citation checker — it parses `references.bib` and confirms every entry is a real,
   findable paper against the Crossref + arXiv APIs (no LLM/MCP), writing
   `writeup/bibcheck.json`:
   ```bash
   .venv/bin/python -m aisci.bibcheck projects/<id>
   ```
   Fix every **blocking** entry (`not_found` = a DOI/arXiv id that doesn't resolve;
   `unresolved` = a title no real paper matches — both are hallucination signals):
   correct the identifier/title against the real paper (re-verify via the arxiv /
   semantic-scholar MCP) or remove the reference, then re-run until it reports CLEAN.
   `title_mismatch` / `no_query` are warnings — check them but they don't block.
   The `enforce_bibcheck` hook **blocks** marking this stage done until a fresh, clean
   report exists, so there is no way to ship a paper with an unverified citation.
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
Report: compile status (clean?), figure list, citation count **and bibcheck verdict
(N verified / 0 blocking)**, page count (as an *observation*, not a target), and the
path to `paper.pdf`. Offer to proceed to `/ai-scientist-review` (or to the improvement
loop, `/ai-scientist-improve`).
