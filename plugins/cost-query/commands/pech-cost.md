---
description: Display current Pech cost totals with attribution breakdown. Scope via --session (default), --day, or --month.
---

# /pech-cost

Shows what the current session / day / month has cost, broken down by plugin → sub-plugin → skill → agent tier → model.

## Usage

```
/pech-cost                  # current session (default)
/pech-cost --session
/pech-cost --day
/pech-cost --month
/pech-cost --json           # machine-readable JSON instead of table
```

## Arguments

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `--session` / `--day` / `--month` | flag | `--session` | Scope of the cost total |
| `--json` | flag | off | Emit JSON instead of human-readable table |
| `--tier` | enum | all | Filter to one agent tier (opus/sonnet/haiku) |

## Example output

```
Pech — session spend (session_id: 4f2a...9e3d)
─────────────────────────────────────────────────────────────
Total:                                                $1.23
  wixie / convergence-engine / /converge / sonnet     $1.10  (89%)
  crow / trust-scorer / PostToolUse / haiku        $0.08  (6.5%)
  pech / cost-tracker / observe / haiku              $0.02  (1.6%)
  orphan (no ENCHANTED_ATTRIBUTION)                  $0.03  (2.4%)
─────────────────────────────────────────────────────────────
Cache hit ratio: 78%   Cache waste: $0.04 (writes with no downstream reads)
```

## Invokes

This command invokes the `cost-display` skill. See [../skills/cost-display/SKILL.md](../skills/cost-display/SKILL.md) for the behavioral contract.
