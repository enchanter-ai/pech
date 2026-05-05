#!/usr/bin/env bash
# Pech installer. Sub-plugins coordinate through the enchanted-mcp event bus;
# the `full` meta-plugin pulls them all in via one dependency-resolution pass.
set -euo pipefail

REPO="https://github.com/enchanter-ai/pech"
PECH_DIR="${HOME}/.claude/plugins/pech"

step() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*" >&2; }

step "Pech installer"

# 1. Clone the monorepo so shared/scripts/*.py are available locally.
#    Plugins themselves are served via the marketplace command below.
if [[ -d "$PECH_DIR/.git" ]]; then
  git -C "$PECH_DIR" pull --ff-only --quiet
  ok "Updated existing clone at $PECH_DIR"
else
  git clone --depth 1 --quiet "$REPO" "$PECH_DIR"
  ok "Cloned to $PECH_DIR"
fi

# 2. Pre-flight: git + jq + python3 (bash+jq for hooks, python stdlib for forecasting)
if ! command -v git >/dev/null 2>&1; then
  warn "git not found on PATH — Pech requires git"
  exit 1
fi
ok "git present"

if ! command -v jq >/dev/null 2>&1; then
  warn "jq not found on PATH — Pech hooks require jq for per-call attribution parsing"
  warn "  macOS:  brew install jq"
  warn "  Linux:  apt install jq   # or dnf / pacman equivalent"
  warn "  Windows: scoop install jq"
  exit 1
fi
ok "jq present ($(jq --version))"

if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — Pech's L1 forecasting + L3 anomaly scripts require Python 3.8+"
  exit 1
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "python3 present (v$PYVER)"

# 3. Rate-card freshness check — surface staleness at install, don't wait until runtime.
RATE_CARD="$PECH_DIR/shared/rate-card.json"
if [[ -f "$RATE_CARD" ]]; then
  EFFECTIVE_FROM=$(jq -r .effective_from "$RATE_CARD" 2>/dev/null || echo "unknown")
  ok "rate-card.json present — effective from $EFFECTIVE_FROM"

  if command -v python3 >/dev/null 2>&1; then
    DAYS_OLD=$(python3 -c "
from datetime import date
try:
    eff = date.fromisoformat('$EFFECTIVE_FROM')
    print((date.today() - eff).days)
except Exception:
    print('?')
" 2>/dev/null || echo '?')
    if [[ "$DAYS_OLD" != "?" ]] && (( DAYS_OLD > 90 )); then
      warn "rate-card.json is $DAYS_OLD days old (> 90). Forecasts will tag rate_card_stale=true until refreshed."
    fi
  fi
else
  warn "rate-card.json missing — cost attribution will fail until restored"
fi

cat <<'EOF'

─────────────────────────────────────────────────────────────────────────
  Pech ships as a 5-sub-plugin marketplace. Each sub-plugin owns one
  named engine (L1–L5) OR one orthogonal concern (rate-card-keeper,
  cost-query). The `full` meta-plugin lists all five as dependencies so
  one install pulls in the whole chain.
─────────────────────────────────────────────────────────────────────────

  Finish in Claude Code with TWO commands:

    /plugin marketplace add enchanter-ai/pech
    /plugin install full@pech

  That installs all 5 sub-plugins via dependency resolution. To cherry-pick
  a single sub-plugin instead, use e.g. `/plugin install cost-tracker@pech`.

  Verify with:   /plugin list
  Expected:      full + 5 sub-plugins under the pech marketplace.

  Once installed, Pech is silent by default — every tool call is observed,
  ledgered, and forecasted without interrupting your flow. The bus fires
  at threshold crossings (50/80/100%), anomaly detections (3σ), and
  session finalization. Peer plugins (Wixie, Sylph, Emu) subscribe and
  degrade gracefully under budget pressure.

  Developer surfaces:

    /pech-cost                  # current session spend + attribution breakdown
    /pech-forecast              # L1 forecast with ±2σ band
    /pech-attribute             # break down last N calls by plugin/tier/model
    /pech-report                # dark-themed PDF audit (Opus anomaly triage)

EOF
