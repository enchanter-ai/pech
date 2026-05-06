#!/usr/bin/env bash
# rate-shield: OPT-IN BLOCKING PreToolUse hook.
# When state/rate-policy.json has enabled:true, exits 2 (block) when the
# active (session, skill) token bucket is empty. Default disabled (no-op).
#
# Override of shared/conduct/hooks.md "Hooks inform, they don't decide" —
# documented in README.md per wixie/CLAUDE.md "When a module conflicts with
# a plugin-local instruction, the plugin wins — but log the override."
#
# Pre-filter strategy: cheap bash check on policy file presence + enabled
# flag before paying python startup cost. Disabled-policy hot path ~5ms.

# Subagent recursion guard — see shared/conduct/hooks.md.
if [[ -n "${CLAUDE_SUBAGENT:-}" ]]; then exit 0; fi

# Fail-safe: any error in the SHIELD itself defaults to NOT blocking.
trap 'exit 0' ERR INT TERM
set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
POLICY_FILE="${PLUGIN_ROOT}/state/rate-policy.json"

# Cheap pre-filter 1: no policy file at all → silent no-op.
[[ -f "$POLICY_FILE" ]] || exit 0

# Cheap pre-filter 2: grep for enabled:true. If absent, silent no-op.
if ! grep -E '"enabled"[[:space:]]*:[[:space:]]*true' "$POLICY_FILE" >/dev/null 2>&1; then
  exit 0
fi

# Dependencies — silently fail-safe if missing.
PY=python3
if ! command -v python3 >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PY=python
  else
    exit 0
  fi
fi

# Run the shield checker. Capture exit code so we can propagate exit 2.
# Note: do NOT use `|| true` here — we WANT the exit code.
SHIELD_EXIT=0
"$PY" "${PLUGIN_ROOT}/scripts/shield-check.py" || SHIELD_EXIT=$?

if [[ "$SHIELD_EXIT" -eq 2 ]]; then
  exit 2
fi
exit 0
