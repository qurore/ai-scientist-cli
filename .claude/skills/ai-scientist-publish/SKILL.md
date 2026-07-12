---
name: ai-scientist-publish
description: Stage 6 (optional) — deposit a finalized project's paper to Zenodo and (on explicit confirmation) publish it for a permanent DOI, with ORCID/author metadata and an AI-generation disclosure. Use only after a study is complete and its review is Accept, and only when the user wants to archive/publish it.
---

# Stage 6 — Publish to Zenodo (DOI)

Archive a finished paper to Zenodo and mint a DOI. **Outward-facing and, once published,
irreversible** (Zenodo DOIs are permanent — you can only add new versions, never delete).
So this stage is deliberately gated, defaults to sandbox + draft, and never publishes without
explicit human confirmation.

## Preconditions ("OK to publish")
- The project is `status: complete` and its `review.json` `Decision` is `Accept`. If not,
  stop and tell the user (the production publish path enforces the Accept gate anyway).
- `projects/<id>/writeup/paper.pdf` exists.
- Credentials are in `.env` (gitignored — **never commit; the repo is public**):
  `ZENODO_SANDBOX_TOKEN` and/or `ZENODO_TOKEN` (scopes `deposit:write`, `deposit:actions`),
  plus the non-secret `ORCID_ID`, `ZENODO_AUTHOR_NAME`, optional `ZENODO_AUTHOR_AFFILIATION`,
  `ZENODO_DEFAULT_LICENSE`. The user must `source .env` (Claude Code does not auto-load it).

## Metadata (built automatically by the helper)
Title comes from the **final** `paper.tex`; the abstract/description from the **current**
`experiment_results/summary.json` (so a revised paper is described correctly, not by the
original idea). Creators = the human curator (with ORCID) **and** "AI Scientist (Claude Code)".
The description and `notes` carry an **AI-generation disclosure** — this is required: these
papers are autonomously generated, the human with the ORCID is the responsible depositor, and
every number traces to `experiment/`. A `related_identifiers` link points back to the repo.

## Procedure (escalating, safest first)
1. **Review the metadata** (no token/network):
   ```bash
   .venv/bin/python -m aisci.zenodo deposit projects/<id> --dry-run
   ```
   Check the title, abstract, creators (ORCID present?), license, keywords with the user.
2. **Sandbox draft:**
   ```bash
   .venv/bin/python -m aisci.zenodo deposit projects/<id>
   ```
   This uploads the PDF + metadata to `sandbox.zenodo.org` as a **draft**. Open the printed
   `draft_url` in the browser and verify it renders correctly. (Optionally test the full flow
   with `--publish` on sandbox — sandbox DOIs are disposable.)
3. **Production draft:**
   ```bash
   .venv/bin/python -m aisci.zenodo deposit projects/<id> --production
   ```
   Review the real draft in the browser.
4. **Production publish (PERMANENT) — only on explicit user confirmation:**
   ```bash
   .venv/bin/python -m aisci.zenodo deposit projects/<id> --production --publish
   ```
   The helper refuses this unless `review.json` Decision is `Accept` (override: `--force`).
   It writes the DOI + record URL to `projects/<id>/zenodo.json`.

## After publishing
- Record the DOI: `aisci.run decide --stage review --decision "Published to Zenodo: <doi>" --why "study complete + accepted" --evidence "zenodo.json"`, and note it in `study.md`.
- The DOI can be added to the paper / ORCID record (link Zenodo↔ORCID in the Zenodo UI so it
  appears on the ORCID profile automatically).

## Guardrails
- **Never** print or commit the token; it lives only in `.env`.
- Default to sandbox + draft; escalate only with the user. Treat production `--publish` like
  any irreversible outward action — confirm first.
- Keep the AI-generation disclosure intact; do not misrepresent authorship.
