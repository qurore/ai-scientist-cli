# ideas/ — topic staging area

This folder is a **scratchpad for topic descriptions** — the seed/input of a study,
written *before* a project exists. It is **not** where projects live (those go in
[`../projects/`](../projects/README.md)).

## How it relates to projects

1. Draft a topic here, e.g. `ideas/my_topic.md` (copy `TEMPLATE_topic.md`), **or** just
   pass a topic sentence straight to `/ai-scientist "<topic>"`.
2. When ideation runs, it creates `projects/<slug>/` and **copies the topic into the
   project** as `projects/<slug>/topic.md`, so each project is fully self-contained and
   portable. `state.json` also stores the topic string.
3. After that, the canonical copy of the topic is the one *inside the project*. The draft
   here is just a staging artifact you can keep or delete.

## Privacy

Like projects, your topic drafts are **gitignored by default** (they reveal your research
directions). Only `TEMPLATE_topic.md` and this `README.md` are tracked. To version your
drafts in a private repo, comment out the `/ideas/*` line in the repo `.gitignore` (see
`README.md` → "Projects & privacy").
