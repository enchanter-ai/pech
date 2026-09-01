# Claude Code configs — Pech

Optional per-user Claude Code settings snippets for Pech. The plugin works without any settings changes, but these patterns can sharpen the experience.

## `settings.json` patterns

### Enable hard budget enforcement (opt-in)

By default, Pech is showback (advisory). To route 100%-threshold crossings through `sylph-gate` for developer confirmation before continuing:

```json
{
  "env": {
    "PECH_HARD_BUDGET": "1"
  }
}
```

Or enable hybrid — advisory for Sonnet/Haiku, hard for Opus above $5/hour:

```json
{
  "env": {
    "PECH_HYBRID_BUDGET": "1"
  }
}
```

### Allow-list Pech's Bash invocations

Pech's hooks use bash + jq to parse API responses and write ledger rows. To skip permission prompts:

```json
{
  "permissions": {
    "allow": [
      "Bash(jq *)",
      "Bash(python3 plugins/cost-tracker/*)",
      "Bash(python3 plugins/budget-watcher/*)",
      "Bash(python3 plugins/nook-learning/*)"
    ]
  }
}
```

### Status line — always-visible cost

Add the session cost to your status line so it's visible without running `/pech-cost`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "jq -r '\"$\" + (.cost_usd | tostring)' ~/.claude/plugins/pech/plugins/cost-tracker/state/session.json 2>/dev/null || echo '$0.00'"
  }
}
```

### Customize budget ceilings

Budget ceilings live at `plugins/budget-watcher/state/budgets.json`. Example configuration:

```json
{
  "session": { "total_usd": 5.00, "opus_usd": 2.00 },
  "hour":    { "total_usd": 15.00 },
  "day":     { "total_usd": 50.00, "opus_usd": 20.00 },
  "month":   { "total_usd": 500.00 },
  "orphan_rate_threshold": 0.01
}
```

Thresholds fire at 50/80/100% of each ceiling.

### Hook integration

Pech's sub-plugins install their own hooks via `/plugin install`. You do not need to copy hook definitions into your user settings — the plugin manifests handle registration.

## Attribution contract

Every plugin that dispatches work via Claude Code should set the `ENCHANTED_ATTRIBUTION` environment variable before the call:

```bash
export ENCHANTED_ATTRIBUTION='{"plugin":"wixie","sub_plugin":"prompt-crafter","skill":"/create","agent_tier":"orchestrator"}'
```

Pech reads this at `PostToolUse` to attribute the call. Missing `ENCHANTED_ATTRIBUTION` means the call is an *orphan* — tracked as a health metric, not hidden in a "misc" bucket.

## Reference

See Claude Code documentation for full `settings.json` schema. Every Pech snippet here is optional; the plugin is fully functional with default settings.
