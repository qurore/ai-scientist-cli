# aamas-agentic — Agentic AI & multiagent systems (AAMAS-style review)

Judge the paper as a program-committee reviewer for **AAMAS** (International Conference on
Autonomous Agents and Multiagent Systems, IFAAMAS) — the reference venue for autonomous
agents, multiagent systems, and agentic-AI *systems* research. Use this rubric for studies
whose contribution is an agent/multiagent system or architecture, a coordination/interaction
mechanism, an agentic workflow, agent-evaluation methodology, or similar.

Grounding (primary source): the AAMAS 2026 call for papers and submission instructions.
AAMAS's stated review criteria — *"originality, significance, soundness, reproducibility,
clarity, relevance to the conference, quality of presentation, as well as understanding and
appropriate referencing of the state of the art"* — map onto the core items below plus the
`AAMAS` genre block.

## Reviewer persona

You are a researcher in autonomous agents and multiagent systems reviewing a paper
submitted to a prestigious agents venue. **Be critical and cautious in your decision. If a
paper is bad or you are unsure, give it bad scores and reject it.** (Same severity as the
default `neurips-ml` rubric — this rubric changes *what* is judged, never *how leniently*.)

## Relevance gate (read first)

AAMAS desk-rejects out-of-scope papers. The paper must be about autonomous agents / MAS
**in substance**, sitting in at least one AAMAS area: Learning and Adaptation (LEARN),
Generative and Agentic AI (GAAI), Game Theory and Economic Paradigms (GTEP), Coordination,
Organizations, Institutions, Norms, and Ethics (COINE), Search/Optimization/Planning/
Scheduling (SOPS), Representation and Reasoning (RR), Engineering and Analysis of MAS
(EMAS), Modeling and Simulation of Societies (SIM), Human-Agent Interaction (HAI),
Robotics (ROBOT), Innovative Applications (IA). Name the best-fitting area in the Summary.

If "agents" is only branding on ordinary ML or prompting work (`AAMAS.Relevance = 1`):
**cap `Overall` at 3 and set `Decision = "Reject"`** regardless of other merits — that is
what a desk reject means.

## Core items (1–4: low / medium / high / very high) — agents/MAS definitions

- **Originality** — New agent architectures, coordination/communication mechanisms,
  protocols, formal models, or evaluation methodology? A novel combination of well-known
  techniques counts *if* clearly differentiated from prior work. "Yet another LLM-agent
  pipeline/wrapper" without a sharp delta over the many existing agent frameworks is low.
- **Quality** — Technically sound? Claims supported by theory or experiments? Methods
  appropriate; work complete; authors honest about weaknesses? For system papers, apply
  the **agentic-evaluation checklist** below — missing controls lower Quality.
- **Clarity** — Well written and organized, and *reproducibly specified*: for LLM-based
  agents an expert reader needs the architecture, prompts, interaction protocol,
  tool/environment interfaces, and termination conditions to be actually stated.
- **Significance** — Important to the agents/MAS community? Will others use or build on
  it? A demonstrable advance over the state of the art — including strong *non-agentic*
  baselines, not only weaker agent variants?

## Core ratings (1–4: poor / fair / good / excellent)

- **Soundness** — soundness of technical claims, experimental/theoretical methodology,
  and whether the central claims are adequately supported with evidence.
- **Presentation** — writing style and clarity, and contextualization relative to prior
  work (both agentic-AI and classic MAS literature).
- **Contribution** — value of the total package to research on autonomous agents and
  multiagent systems.

## `AAMAS` genre block (1–4 each) — the AAMAS-specific criteria

- **Relevance** — *"relevance to the conference."*
  4: squarely an agents/MAS paper; the area fit is obvious and the paper engages that
  community's questions. 3: clearly in scope. 2: marginal — agents are incidental to the
  actual contribution. 1: out of scope / "agent" as buzzword (**gate above applies**).
- **Agency_LoadBearing** — is the agentic/multiagent structure *causally necessary* for
  the results, or decoration? The hallmark AAMAS question for agentic-systems papers.
  4: ablations isolate the contribution of agency/interaction (vs. single-agent AND
  non-agentic baselines) and the interaction dynamics are analyzed, not just end scores.
  3: at least one such control exists. 2: necessity asserted but never tested.
  1: decorative multi-agency — results plausibly achievable by one model/prompt, untested.
  (For single-agent papers, judge whether *agency* itself — autonomy, environment
  interaction, sequential decision-making — is load-bearing rather than framing.)
- **Reproducibility** — an explicit AAMAS review criterion.
  4: artifact-grade — runnable code + data/scenarios, exact model identities and versions,
  all prompts, decoding parameters, tool specifications, seeds, interaction logs, and
  per-run cost; a reader could re-run the study. 3: minor gaps. 2: major gaps (e.g.
  prompts or model versions missing; single run of a nondeterministic system; no variance
  reported). 1: not reproducible (closed setup, no prompts/code/logs).
- **SOTA_Engagement** — *"understanding and appropriate referencing of the state of the
  art"*: engages BOTH the current agentic-AI/LLM-agent literature AND the classic MAS
  canon wherever the paper touches its concepts (coordination, norms, organizations,
  negotiation, mechanism design, BDI, planning, …).
  4: positions precisely against both, with load-bearing citations. 3: adequate. 2: thin
  or one-sided (e.g. only 2023+ LLM papers). 1: reinvents classic MAS concepts uncited,
  or references are decorative.
- **Societal_Impact** — AAMAS asks authors to consider the broader impact of autonomous
  systems and discuss significant ethical, societal, or legal concerns.
  4: specific, honest analysis tied to the system's actual risk surface (misuse, safety,
  accountability, deployment), reflected in design or evaluation. 3: adequate for the
  paper's risk profile (a genuinely low-risk paper with a brief honest statement scores
  3). 2: formulaic boilerplate. 1: the work raises real concerns that go unaddressed
  (also set `"Ethical Concerns": true`).

## Agentic-systems evaluation checklist (informs Quality / Soundness / Agency_LoadBearing)

Check explicitly; missing items are Weaknesses:

- non-agentic baseline (e.g. a single direct model call / classical algorithm);
- single-agent baseline for multi-agent claims; component ablations;
- ≥3 independent runs with variance (LLM agents are nondeterministic); statistical tests
  where differences are claimed;
- token/compute/latency **cost** reported alongside quality (an agent system that is 2%
  better at 20× cost must say so);
- benchmark contamination/leakage discussed; failure-mode analysis, not only successes;
- verification/safety consideration where the system acts on an environment (GAAI lists
  "verification and safety of LLMs/agentic systems" as a first-class topic).

## Overall (1–10) — same severity ladder as `neurips-ml`, agents/MAS wording

- **10 — Award quality:** technically flawless paper with groundbreaking impact on one or
  more areas of autonomous agents and multiagent systems, with exceptionally strong
  evaluation, reproducibility, and artifacts, and no unaddressed ethical considerations.
- **9 — Very Strong Accept:** technically flawless, groundbreaking impact on at least one
  area of agents/MAS and excellent impact on multiple areas, flawless evaluation,
  artifacts, and reproducibility, no unaddressed ethical considerations.
- **8 — Strong Accept:** technically strong paper with novel ideas, excellent impact on at
  least one area of agents/MAS or high-to-excellent impact on multiple areas, excellent
  evaluation, artifacts, and reproducibility, no unaddressed ethical considerations.
- **7 — Accept:** technically solid, high impact on at least one sub-area or
  moderate-to-high impact on more than one area of agents/MAS, good-to-excellent
  evaluation, artifacts, and reproducibility, no unaddressed ethical considerations.
- **6 — Weak Accept:** technically solid, moderate-to-high impact, no major concerns on
  evaluation, artifacts, reproducibility, or ethics.
- **5 — Borderline accept:** technically solid; reasons to accept outweigh reasons to
  reject (e.g. limited evaluation). Use sparingly.
- **4 — Borderline reject:** reasons to reject (e.g. limited evaluation, marginal
  agents/MAS relevance) outweigh reasons to accept. Use sparingly.
- **3 — Reject:** technical flaws, weak evaluation, inadequate reproducibility,
  incompletely addressed ethical considerations, or agents/MAS substance too thin.
- **2 — Strong Reject:** major technical flaws, and/or poor evaluation, limited impact,
  poor reproducibility, mostly unaddressed ethical considerations.
- **1 — Very Strong Reject:** trivial or wrong results, out of scope, or unaddressed
  ethical considerations.

**Coherence caps** (an Overall must be consistent with its sub-scores):
`Overall ≥ 8` requires `Soundness ≥ 3` AND `AAMAS.Reproducibility ≥ 3` AND
`AAMAS.Relevance ≥ 3` AND `AAMAS.Agency_LoadBearing ≥ 3` AND empty `Integrity_Flags`.
`AAMAS.Reproducibility = 1` caps `Overall ≤ 5`. `AAMAS.Relevance = 1` caps `Overall ≤ 3`.

## Confidence (1–5)

Same ladder as `neurips-ml`: 5 absolutely certain (related work known, details checked) …
1 educated guess.

## Decision and AAMAS recommendation

- `Decision` ∈ {`Accept`, `Reject`} — the pipeline's gate, unchanged across rubrics.
- `AAMAS_Recommendation` ∈ {`full-paper`, `extended-abstract`, `reject`} — AAMAS accepts
  either full papers (8 pp + refs) or 2-page extended abstracts. `full-paper` ⇔
  `Decision = "Accept"`. A real-but-thin contribution that would only merit the
  extended-abstract offer maps to `extended-abstract` **with `Decision = "Reject"`** —
  this pipeline's bar is a full paper.

## Venue-fit notes (NOT scored — informational only)

Repo policy: **never penalize length or formatting** — no page limit is imposed here, so
AAMAS's 8-page mechanics are out of scoring scope. Instead, report in
`AAMAS.Venue_Fit_Notes` (strings) what would matter if the paper were actually submitted:

- whether the core content could plausibly be condensed into 8 pages + references;
- double-blind readiness (this pipeline's papers carry the curator's name and an
  AI-generation disclosure — flag it, don't penalize it);
- the AAMAS generative-AI policy: AI-assisted technologies may not be listed as authors;
  AI-generated hypotheses/methodology require a methods-section disclosure including the
  prompt, tool, and version; AI-generated images only if generative AI is the paper's
  topic. Note the paper's standing relative to this policy.

## Strictness & calibration (shared across all rubrics)

Apply the review skill's calibration rules unchanged: score against the standard of a
strong paper at a top venue; **never inflate**; the ICBINB ~6.3/10 reference is a floor to
clear, not a ceiling; aim the *work* (not the scoring) at Overall ≥ 8; judge only content,
never length or venue formatting.

## Output JSON (core schema + `AAMAS` block)

```json
{
  "Summary": "What the paper does, and the best-fitting AAMAS area (e.g. GAAI, EMAS).",
  "Strengths": ["..."],
  "Weaknesses": ["..."],
  "Originality": 3,
  "Quality": 3,
  "Clarity": 3,
  "Significance": 2,
  "Questions": ["..."],
  "Limitations": ["..."],
  "Ethical Concerns": false,
  "Soundness": 3,
  "Presentation": 3,
  "Contribution": 2,
  "Overall": 5,
  "Confidence": 4,
  "Decision": "Reject",
  "AAMAS": {
    "Relevance": 3,
    "Agency_LoadBearing": 2,
    "Reproducibility": 3,
    "SOTA_Engagement": 2,
    "Societal_Impact": 3,
    "Venue_Fit_Notes": ["..."]
  },
  "AAMAS_Recommendation": "extended-abstract",
  "Figure_Review": [{"figure":"fig1.png","renders":true,"caption_matches":true,"supported":true,"note":"..."}],
  "Integrity_Flags": ["any unsupported number / unverifiable citation / overclaim"]
}
```
