#!/usr/bin/env bash
# Set up the AI-Scientist-on-Claude-Code base environment.
# Idempotent and safe to re-run. Works from a fresh clone of THIS repo
# (it will pull the gitignored upstream into vendor/ on first run).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

UPSTREAM_URL="https://github.com/SakanaAI/AI-Scientist-v2.git"
VENDOR_DIR="vendor/AI-Scientist-v2"
PY="${AISCI_PYTHON:-python3.11}"

echo "==> Repo: $REPO_ROOT"

# 1) Vendor the upstream code (gitignored).
if [ ! -d "$VENDOR_DIR/ai_scientist" ]; then
  echo "==> Cloning upstream into $VENDOR_DIR"
  git clone --depth 1 "$UPSTREAM_URL" "$VENDOR_DIR"
else
  echo "==> Upstream already present in $VENDOR_DIR"
fi

# 2) Python venv (3.11 required by upstream).
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: $PY not found. Install Python 3.11 (e.g. 'brew install python@3.11')." >&2
  exit 1
fi
if [ ! -d ".venv" ]; then
  echo "==> Creating .venv with $PY"
  "$PY" -m venv .venv
fi
echo "==> Python: $(.venv/bin/python --version)"

# 3) Python dependencies.
echo "==> Upgrading pip"
.venv/bin/python -m pip install -q --upgrade pip
echo "==> Installing upstream requirements (this can take a few minutes)"
.venv/bin/python -m pip install -q -r "$VENDOR_DIR/requirements.txt"
echo "==> Installing extras needed by the launcher (torch, psutil)"
# torch + psutil are imported by launch_scientist_bfts.py but are NOT in
# requirements.txt. CPU/MPS build is fine on macOS.
.venv/bin/python -m pip install -q torch psutil || {
  echo "WARN: torch/psutil install failed. The native experiment skill still"
  echo "      works without them; only the bridge launcher needs them." >&2
}

# 4) Optional: anthropic[bedrock] for strict upstream parity via the bridge.
.venv/bin/python -m pip install -q "anthropic[bedrock]" >/dev/null 2>&1 || true

# 5) Optional: uv, used by .mcp.json to launch the literature-search MCP
#    servers (arxiv-mcp-server, semantic-scholar-fastmcp). Best-effort: the
#    ideate/writeup skills fall back to WebSearch/curl if this is unavailable.
echo "==> Installing uv (for literature-search MCP servers) into .venv"
.venv/bin/python -m pip install -q uv || {
  echo "WARN: uv install failed. /ai-scientist-ideate and -writeup still work" >&2
  echo "      via WebSearch; the arxiv/semantic-scholar MCP tools need uv." >&2
}

# 6) System tools needed for the writeup stage (best-effort, never fatal).
echo "==> Checking system tools for the writeup stage"
missing=()
for t in pdflatex pdftotext chktex; do
  command -v "$t" >/dev/null 2>&1 || missing+=("$t")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "    Missing: ${missing[*]}"
  echo "    To enable LaTeX writeup on macOS:"
  echo "      brew install basictex chktex poppler"
  echo "      # (basictex is small; for the full stack use: brew install --cask mactex-no-gui)"
  echo "      eval \"\$(/usr/libexec/path_helper)\"   # add TeX to PATH in this shell"
else
  echo "    All writeup tools present."
fi

mkdir -p projects ideas .aisci_cache .mcp-data

echo
echo "==> Setup complete. Verify anytime with: bash scripts/doctor.sh"
echo "==> Start a study by invoking the /ai-scientist skill in Claude Code."
