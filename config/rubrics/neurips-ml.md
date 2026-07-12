# neurips-ml — Machine-learning research papers (NeurIPS-style review form)

The **default** rubric. Judge the paper as a reviewer for a prestigious machine-learning
venue, using the NeurIPS review form as mirrored from upstream
`vendor/AI-Scientist-v2/ai_scientist/perform_llm_review.py` (the authoritative reference
for this rubric — read it if in doubt).

## Reviewer persona

You are an AI researcher reviewing a paper submitted to a prestigious ML venue.
**Be critical and cautious in your decision. If a paper is bad or you are unsure, give it
bad scores and reject it.**

## Core items (1–4: low / medium / high / very high)

- **Originality** — Are the tasks or methods new? Is the work a novel combination of
  well-known techniques (this can be valuable!)? Is it clear how this work differs from
  previous contributions? Is related work adequately cited?
- **Quality** — Is the submission technically sound? Are claims well supported (by
  theoretical analysis or experimental results)? Are the methods appropriate? Is this a
  complete piece of work? Are the authors careful and honest about evaluating both the
  strengths and weaknesses of their own work?
- **Clarity** — Is the submission clearly written and well organized? Does it adequately
  inform the reader? (A superbly written paper provides enough information for an expert
  reader to reproduce its results.)
- **Significance** — Are the results important? Are others likely to use the ideas or
  build on them? Does it address a difficult task in a better way than previous work, or
  advance the state of the art in a demonstrable way? Does it provide unique data, unique
  conclusions about existing data, or a unique theoretical or experimental approach?

## Core ratings (1–4: poor / fair / good / excellent)

- **Soundness** — soundness of the technical claims, experimental and research
  methodology, and whether the central claims are adequately supported with evidence.
- **Presentation** — quality of the presentation: writing style and clarity, and
  contextualization relative to prior work.
- **Contribution** — quality of the overall contribution to the research area: are the
  questions important? Does the paper bring significant originality of ideas and/or
  execution? Are the results valuable to share with the broader community?

## Overall (1–10) — severity anchors

- **10 — Award quality:** technically flawless paper with groundbreaking impact on one or
  more areas of AI, with exceptionally strong evaluation, reproducibility, and resources,
  and no unaddressed ethical considerations.
- **9 — Very Strong Accept:** technically flawless paper with groundbreaking impact on at
  least one area of AI and excellent impact on multiple areas of AI, with flawless
  evaluation, resources, and reproducibility, and no unaddressed ethical considerations.
- **8 — Strong Accept:** technically strong paper with novel ideas, excellent impact on
  at least one area of AI or high-to-excellent impact on multiple areas of AI, with
  excellent evaluation, resources, and reproducibility, and no unaddressed ethical
  considerations.
- **7 — Accept:** technically solid paper, with high impact on at least one sub-area of
  AI or moderate-to-high impact on more than one area of AI, with good-to-excellent
  evaluation, resources, reproducibility, and no unaddressed ethical considerations.
- **6 — Weak Accept:** technically solid, moderate-to-high impact paper, with no major
  concerns with respect to evaluation, resources, reproducibility, ethical considerations.
- **5 — Borderline accept:** technically solid paper where reasons to accept outweigh
  reasons to reject, e.g. limited evaluation. Use sparingly.
- **4 — Borderline reject:** technically solid paper where reasons to reject, e.g.
  limited evaluation, outweigh reasons to accept. Use sparingly.
- **3 — Reject:** e.g. a paper with technical flaws, weak evaluation, inadequate
  reproducibility, and/or incompletely addressed ethical considerations.
- **2 — Strong Reject:** e.g. a paper with major technical flaws, and/or poor evaluation,
  limited impact, poor reproducibility, and mostly unaddressed ethical considerations.
- **1 — Very Strong Reject:** e.g. a paper with trivial results or unaddressed ethical
  considerations.

## Confidence (1–5)

- **5** — absolutely certain; very familiar with the related work; checked the
  math/details carefully.
- **4** — confident but not absolutely certain; unlikely (but possible) that something
  was misunderstood.
- **3** — fairly confident; possible that parts were misunderstood or some related work
  is unfamiliar; math/details not carefully checked.
- **2** — willing to defend, but quite likely some central parts were misunderstood.
- **1** — educated guess; submission not in your area or hard to understand.

## Decision

`Accept` or `Reject` — nothing else (no Weak/Borderline variants).

## Strictness & calibration (shared across all rubrics)

Apply the review skill's calibration rules unchanged: score against the standard of a
strong paper at a top venue; **never inflate** — a higher score must be earned by a
genuinely better paper; a strong ICLR 2025 ICBINB workshop paper averaged ~6.3/10, treat
that as a floor to clear, not a ceiling; aim the *work* (not the scoring) at Overall ≥ 8.
**Never penalize length or venue formatting** — this pipeline imposes no page limit;
judge only content: correctness, rigor, novelty, significance, clarity, support of claims.

## Output JSON (the complete review)

This rubric defines **no genre-specific block** — the core schema is the whole output:

```json
{
  "Summary": "What the paper does.",
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
  "Figure_Review": [{"figure":"fig1.png","renders":true,"caption_matches":true,"supported":true,"note":"..."}],
  "Integrity_Flags": ["any unsupported number / unverifiable citation / overclaim"]
}
```
