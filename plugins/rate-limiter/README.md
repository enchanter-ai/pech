# rate-limiter

*Part of [Pech](../../README.md) — Cost Ledger for AI-Assisted Development.*

Advisory token-bucket rate limiter per `(session, skill)`. Fires on
`PreToolUse` for every tool call. Surfaces runaway loops in real time —
before `budget-watcher` reports the cost post-hoc.

**Advisory-only contract.** This plugin never blocks. Bucket empty → one
stderr line; the tool call proceeds. Per `../enchanter-foundations/packages/core/conduct/hooks.md`.

## How it works

Each `(session_id, skill)` pair gets a token bucket. Defaults: capacity 60,
refill 1 token/second. Each tool call consumes one token; if the bucket is
empty, an advisory is printed to stderr.

- **Session id:** `$CLAUDE_SESSION_ID` if present, else `sha1(cwd:ppid)[:16]`.
- **Skill id:** the closest `skills/<name>/` ancestor of cwd, else `ungated`.
- **Atomicity:** read-modify-write of `state/buckets.json` under exclusive
  lock (msvcrt on Windows, fcntl elsewhere).

## Configuration

`state/buckets.json` is the opt-in gate. Delete it to disable the plugin
(the hook becomes a no-op).

```json
{
  "global_default": {"capacity": 60, "refill_per_sec": 1.0},
  "per_skill": {
    "deep-research": {"capacity": 200, "refill_per_sec": 5.0}
  }
}
```

Missing per-skill entry → fall back to `global_default`. The runtime bucket
state is stored in the same file under the `_buckets` map (key
`<session>::<skill>`); leave it alone — the script owns it.

## Files

```
rate-limiter/
├── .claude-plugin/plugin.json     manifest
├── hooks/hooks.json               PreToolUse registration
├── hooks/pretooluse-rate.sh       opt-in gate + python dispatch
├── scripts/rate-check.py          locked read-modify-write + advisory emit
├── skills/rate-awareness/SKILL.md skill metadata
└── state/buckets.json             config + bucket state (opt-in by presence)
```

## Stop conditions

- Always exits 0. Always.
- Stderr advisory format:
  `=== rate-limiter (advisory) === Bucket empty for <skill>. Recent rate exceeds <N>/min — possible runaway loop. Pausing... is your call. Tool will proceed.`

## Relation to peers

| Plugin | Owns |
|--------|------|
| **rate-limiter** (this) | Velocity advisory, real-time, per `(session, skill)` |
| `budget-watcher` | Cost-based threshold + 3σ anomaly, post-hoc on the ledger |
| `cost-tracker` | Ledger writer, source of truth for spend |
