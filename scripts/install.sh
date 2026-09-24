#!/usr/bin/env bash
# Installs goohle-mcp, signs in with Google and registers it in Claude Code.
#
# Usage:
#   bash install.sh /path/to/client_secret.json [read|write|publish]
set -euo pipefail

REPO="git+https://github.com/haditaj/goohlemcp@${GOOHLE_MCP_REF:-claude/vibrant-knuth-ovrixn}"
SECRETS="${1:-}"
MODE="${2:-write}"

if [[ -z "$SECRETS" || ! -f "$SECRETS" ]]; then
  echo "Usage: bash install.sh /path/to/client_secret.json [read|write|publish]" >&2
  echo "Download the JSON from Google Cloud Console > Google Auth Platform > Clients (type: Desktop app)." >&2
  exit 1
fi
case "$MODE" in read|write|publish) ;; *) echo "Mode must be read, write or publish." >&2; exit 1 ;; esac

echo "==> 1/4 Checking uv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> 2/4 Installing goohle-mcp"
uv tool install --force "$REPO"
BIN="$(uv tool dir --bin)/goohle-mcp"

echo "==> 3/4 Signing in with Google (a browser window opens)"
if [[ "$MODE" == "read" ]]; then
  "$BIN" auth --client-secrets "$SECRETS" --read-only
else
  "$BIN" auth --client-secrets "$SECRETS"
fi
GOOHLE_MCP_MODE="$MODE" "$BIN" status

echo "==> 4/4 Registering with Claude Code (mode: $MODE)"
if command -v claude >/dev/null 2>&1; then
  claude mcp remove goohle --scope user >/dev/null 2>&1 || true
  claude mcp add goohle --scope user -e "GOOHLE_MCP_MODE=$MODE" -- "$BIN"
  echo "Done. Open Claude Code and ask: list my GA4 accounts"
else
  echo "Claude Code CLI not found. Add this server manually:"
  echo "  claude mcp add goohle --scope user -e GOOHLE_MCP_MODE=$MODE -- $BIN"
fi
