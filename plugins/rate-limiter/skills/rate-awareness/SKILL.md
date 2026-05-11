---
name: rate-awareness
description: >
  Token-bucket advisory rate limiter per skill+session. Surfaces runaway
  tool-call loops in real time before pech/budget-watcher reports them
  post-hoc. Auto-fires on PreToolUse. Configurable per-skill limits via
  state/buckets.json. Do not use for cost reporting (see budget-watcher)
  or for blocking installs (see package-gate).
model: haiku
tools: [Read, Bash]
---

# rate-awareness

Token-bucket advisory limiter. Each tool call consumes one token from a per
(session, skill) bucket. When the bucket is empty, an advisory is emitted to
stderr — the tool still proceeds (advisory-only contract per
`../enchanter-foundations/packages/core/conduct/hooks.md`).

## Preconditions

- `state/buckets.json` exists (opt-in gate — absence = silent no-op).
- The PreToolUse hook is registered via `hooks/hooks.json`.

## Inputs

- **Hook event:** `PreToolUse` on every tool (matcher `.*`).
- **Bucket config:** `state/buckets.json` — `global_default` plus optional
  `per_skill` overrides.
- **Session id:** `$CLAUDE_SESSION_ID` if set, else SHA-1 hash of
  `cwd:ppid` truncated to 16 chars.
- **Skill id:** best-effort — most recent `skills/<name>/` ancestor of cwd,
  else `ungated`.

## Steps

1. Hook (`hooks/pretooluse-rate.sh`) fires; if `state/buckets.json` missing,
   exits 0 silently.
2. `scripts/rate-check.py` opens `state/buckets.json` `r+`, takes an
   exclusive lock (msvcrt on Windows, fcntl elsewhere).
3. Reads state. Resolves capacity + refill rate via per-skill override or
   `global_default`.
4. Refills the (session, skill) bucket: `tokens = min(capacity, tokens + dt * refill)`.
5. If `tokens >= 1` → consume 1, no advisory. Else → record empty, set
   `advisory = true`.
6. Write-back atomically (truncate + `fsync`) under the same lock.
7. If advisory: emit stderr message; always exit 0.

**Success criterion:** every PreToolUse decrements (or refills) exactly one
bucket entry; the 61st call within a 1-second window for a bucket of
capacity 60 emits the advisory; the tool call proceeds regardless.

## Outputs

- Updated `state/buckets.json` (mutated `_buckets` map keyed by
  `<session>::<skill>`).
- Stderr advisory line on bucket-empty (visible to the developer; not
  injected into the model context).

## Configuration

`state/buckets.json` schema:

```json
{
  "global_default": {"capacity": 60, "refill_per_sec": 1.0},
  "per_skill": {
    "deep-research": {"capacity": 200, "refill_per_sec": 5.0}
  }
}
```

Add per-skill entries as needed. Delete the file entirely to disable the
plugin (opt-in by file presence).

## Handoff

Downstream: pech/budget-watcher still owns post-hoc cost ceilings. This
plugin only surfaces velocity anomalies before the spend lands.

## Failure modes

| Code | Scenario | Counter |
|------|----------|---------|
| F09 | Two PreToolUse hooks writing buckets.json concurrently | Exclusive flock/msvcrt lock around the read-modify-write |
| F05 | Advisory spam on every call once bucket empties | Tokens stay at 0 until refill catches up; one stderr line per emptied call is the signal, not a bug |
| F13 | Skill mis-identified as `ungated` when cwd is outside any skills/ tree | Default `ungated` bucket uses `global_default`; per-skill overrides only fire when detection succeeds |
| F08 | Hook calling the script with wrong python | `python3` per pech convention; matches budget-watcher hooks |
