#!/usr/bin/env bash
# Diagnose the AI-Scientist-on-Claude-Code environment. Read-only; exits 0.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }

echo "AI-Scientist / Claude Code — doctor"
echo "repo: $REPO_ROOT"

echo "[core]"
command -v claude >/dev/null 2>&1 && ok "claude CLI: $(claude --version 2>/dev/null)" || bad "claude CLI not found (the whole system depends on it)"
[ -d ".venv" ] && ok ".venv present: $(.venv/bin/python --version 2>&1)" || bad ".venv missing — run scripts/setup.sh"
[ -d "vendor/AI-Scientist-v2/ai_scientist" ] && ok "vendor/AI-Scientist-v2 present" || bad "vendor missing — run scripts/setup.sh"

echo "[python deps]"
if [ -d ".venv" ]; then
  for mod in anthropic openai backoff omegaconf jsonschema funcy; do
    .venv/bin/python -c "import $mod" 2>/dev/null && ok "import $mod" || bad "import $mod (run setup.sh)"
  done
  .venv/bin/python -c "import torch" 2>/dev/null && ok "import torch ($(.venv/bin/python -c 'import torch;print(torch.__version__)' 2>/dev/null))" || warn "torch not installed (only the bridge launcher needs it)"
  .venv/bin/python -c "import psutil" 2>/dev/null && ok "import psutil" || warn "psutil not installed (bridge launcher cleanup needs it)"
fi

echo "[bridge]"
if [ -d ".venv" ]; then
  .venv/bin/python -c "import sys; sys.path.insert(0,'.'); from bridge import claude_cli, model_map; print(model_map.resolve_model('gpt-4o-mini'))" >/tmp/aisci_bridge.$$ 2>&1 \
    && ok "bridge imports; gpt-4o-mini -> $(cat /tmp/aisci_bridge.$$)" \
    || { bad "bridge import failed:"; sed 's/^/      /' /tmp/aisci_bridge.$$; }
  rm -f /tmp/aisci_bridge.$$
fi

echo "[writeup tools]"
command -v pdflatex >/dev/null 2>&1 && ok "pdflatex" || warn "pdflatex missing (brew install basictex)"
command -v pdftotext >/dev/null 2>&1 && ok "poppler (pdftotext)" || warn "poppler missing (brew install poppler)"
command -v chktex >/dev/null 2>&1 && ok "chktex" || warn "chktex missing (brew install chktex)"

echo "[mcp]"
[ -x ".venv/bin/uvx" ] && ok "uvx present (.venv/bin/uvx) — arxiv/semantic-scholar MCP servers can launch" || warn "uvx missing — run scripts/setup.sh, or ideate/writeup fall back to WebSearch"
python3 -c "import json;json.load(open('.mcp.json'))" 2>/dev/null && ok ".mcp.json valid JSON" || bad ".mcp.json missing or invalid"

echo "[hooks]"
for h in session_start guard_experiment_exec log_tool_use stop_autopilot; do
  [ -f ".claude/hooks/$h.py" ] && ok "hook $h.py" || bad "hook $h.py missing"
done
python3 -c "import json;json.load(open('.claude/settings.json'))" 2>/dev/null && ok ".claude/settings.json valid JSON" || bad ".claude/settings.json invalid"

echo "[gpu]"
if [ -d ".venv" ]; then
  .venv/bin/python -c "import torch;print('mps' if torch.backends.mps.is_available() else 'cpu-only')" 2>/dev/null | sed 's/^/  compute: /' || echo "  compute: cpu-only (torch not installed)"
fi

echo "[studies]"
.venv/bin/python -m aisci.run list 2>/dev/null | sed 's/^/  /' || echo "  (none)"
exit 0
