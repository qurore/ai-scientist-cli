# Codex integration

Codex-specific behavior lives in this directory:

- `config.toml` enables project-scoped environment defaults and lifecycle hooks.
- `hooks.json` wires the hook scripts in `hooks/`.
- `skills/` contains the Codex-native research workflow.

Codex officially discovers repository skills through `.agents/skills`, so the
repository keeps a single symlink there pointing back to `.codex/skills`. The skill
implementation remains under `.codex`; shared research code remains outside both
`.codex` and `.claude` so either agent can use it.

Project-local Codex configuration and hooks load only after the repository is trusted.
Review and trust changed hooks with `/hooks` when Codex prompts for it.
