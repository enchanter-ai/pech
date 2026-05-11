# rate-shield

> **OPT-IN BLOCKING.** Sibling of [`rate-limiter`](../rate-limiter)
> (advisory). When `state/rate-policy.json` sets `enabled: true`, this
> PreToolUse hook **blocks** (`exit 2`) any tool call once the active
> `(session, skill)` token bucket is empty. Default disabled — out of
> the box this shield does nothing.

## Why a separate plugin from rate-limiter

`rate-limiter` is **observability** (advisory, always exits 0, prints to
stderr when a bucket empties). It conforms to
`../enchanter-foundations/packages/core/conduct/hooks.md` "Hooks inform, they don't decide". Operators
who want enforcement, not just signal, install **this** plugin in
addition to (or instead of) the limiter.

Splitting them keeps:

- The advisory contract clean for users who don't want surprises.
- The blocking contract opt-in and reversible by editing one JSON file.
- The override of `hooks.md` localized to one plugin (this one), which
  CLAUDE.md explicitly permits: *"When a module conflicts with a
  plugin-local instruction, the plugin wins — but log the override."*

## Bucket-source coordination with rate-limiter

`rate-shield` shares state with `rate-limiter` whenever both are
installed:

1. If `../rate-limiter/state/buckets.json` exists, the shield reads and
   writes that file (so a single decrement counts against the same
   bucket the advisory limiter sees).
2. Otherwise the shield falls back to its own `state/buckets.json`
   (created lazily on first run).
3. If the sibling file is corrupted/unreadable, the shield's fail-safe
   path returns `exit 0` (graceful degrade).

This means the per-skill overrides you set in `rate-policy.json` (this
plugin) drive the **decrement** semantics, while the sibling's
`buckets.json` is the **state surface**.

## hooks.md override (logged)

This plugin **overrides** the project-wide rule in
`../enchanter-foundations/packages/core/conduct/hooks.md` that hooks must be advisory-only. The override
is bounded:

1. **Off by default.** Disabled `state/rate-policy.json` ships out of
   the box; `enabled:false` means the hook is a silent no-op.
2. **Fail-safe.** Any error in the shield itself (malformed policy,
   parse failure, IO error, missing python) results in `exit 0`. Operator
   must fix the config to re-enable enforcement.
3. **Subagent-recursion guard.** `$CLAUDE_SUBAGENT` set → exit 0.
4. **Pre-filtered hot path.** Disabled-policy fast path is a single
   `grep` + early exit, no python startup.

## Opt-in flow

```bash
# 1) Copy the example policy.
cp state/rate-policy.example.json state/rate-policy.json

# 2) Edit to enable; tune per_skill as needed.
# {
#   "enabled": true,
#   "default_capacity": 60,
#   "default_refill_per_sec": 1.0,
#   "per_skill": { "deep-research": { "capacity": 200, "refill_per_sec": 5.0 } }
# }

# 3) Restart Claude Code so the hook is registered.

# 4) Reverse anytime by setting enabled:false.
```

## Behavior

1. **PreToolUse hook on all tools.** Pre-filter: bails if policy file
   absent OR `enabled:true` not present in the JSON.
2. **shield-check.py:**
   - Loads `state/rate-policy.json`. If disabled → exit 0.
   - Resolves `(session, skill)` identity:
     - `session` = `$CLAUDE_SESSION_ID` if set, else SHA-1 of
       `cwd:ppid` (truncated to 16 chars).
     - `skill` = closest `skills/<name>/` ancestor of cwd, else
       `ungated`.
   - Looks up `(capacity, refill_per_sec)` from `policy.per_skill[skill]`
     when set, else `policy.default_*`.
   - Opens the active `buckets.json` (sibling preferred, own fallback)
     under exclusive lock.
   - Refills: `tokens = min(capacity, tokens + dt * refill)`.
   - If `tokens >= 1` → consume, write-back, exit 0.
     Else → record empty, write-back, stderr advisory, **exit 2**.
3. **Subagent-recursion guard** (`$CLAUDE_SUBAGENT`).
4. **Fail-safe.** Any unhandled exception → exit 0.

## Stderr block message

```
=== rate-shield (BLOCKED) ===
Bucket empty for skill=<skill> (capacity=<n>, refill=<r>/sec). Tool
call blocked to prevent runaway loop. To unblock: wait for refill,
raise the limit in state/rate-policy.json (per_skill override), or set
enabled:false to disable the shield.
```

## Files

```
plugins/rate-shield/
├── .claude-plugin/plugin.json
├── README.md                           (this file)
├── hooks/hooks.json                    (PreToolUse registration)
├── hooks/pretooluse.sh                 (recursion guard, fail-safe, propagates exit 2)
├── scripts/shield-check.py             (token-bucket decrement, exit 2 on empty)
├── skills/shield-awareness/SKILL.md    (interpretation + opt-in flow)
└── state/rate-policy.example.json      (default-disabled template)
```

## See also

- [`rate-limiter`](../rate-limiter) — advisory sibling (observability
  only); this shield reads its `state/buckets.json` when present.
- [`budget-watcher`](../budget-watcher) — post-hoc cost ceilings.
- `../enchanter-foundations/packages/core/conduct/hooks.md` — advisory-default rule (overridden here,
  per the override-note above).
- F-013 (rate-limit enforcement) — closed by this plugin.
