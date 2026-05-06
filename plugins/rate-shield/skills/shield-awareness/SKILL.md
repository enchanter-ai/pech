---
name: rate-shield-awareness
description: >
  OPT-IN BLOCKING token-bucket rate limiter. Pairs with pech-rate-limiter
  (advisory). When state/rate-policy.json sets enabled:true, this shield
  blocks (exits 2) any tool call once the active (session, skill) bucket
  is empty. Reads buckets from rate-limiter's state/buckets.json when
  present; gracefully degrades when absent. Use when the developer asks
  why a tool call was rate-blocked, wants to enable or tune the rate
  policy, or reviews a stderr "rate-shield (BLOCKED)" message. Default
  disabled. Do not use for advisory-only velocity signals (see
  rate-limiter) or for cost reporting (see budget-watcher).
allowed-tools:
  - Read
  - Bash
model: haiku
---

<purpose>
Help the developer interpret rate-shield's blocking decisions. The
PreToolUse hook reads state/rate-policy.json; when enabled, it
decrements the active (session, skill) token bucket and exits 2 once the
bucket is empty. Each block emits a stderr message naming the skill, the
capacity, and the refill rate. This skill reads those signals and
explains them — it never claims a block was incorrect without checking
the policy file and the relevant bucket entry.
</purpose>

<override_note>
This shield exists as an explicit override of shared/foundations/conduct/hooks.md
"Hooks inform, they don't decide". The override is documented in this
plugin's README and is permitted by wixie/CLAUDE.md: "When a module
conflicts with a plugin-local instruction, the plugin wins — but log
the override." The advisory sibling pech-rate-limiter remains unchanged;
operators choose whether to add this blocking layer on top.
</override_note>

<constraints>
1. NEVER claim a block was a bug without verifying the bucket is genuinely
   empty in the relevant buckets.json (sibling rate-limiter's, or this
   plugin's own fallback).
2. NEVER recommend setting enabled:false to suppress an unwanted block —
   recommend raising the per-skill capacity / refill_per_sec, or
   investigating the runaway loop that drained the bucket.
3. ALWAYS read state/rate-policy.json AND the active buckets.json before
   answering "why was X blocked".
4. ALWAYS note that the shield is fail-safe: malformed policy file, IO
   errors, or missing buckets.json (with sibling absent) → no blocking.
5. NEVER write to state/rate-policy.json from this skill — propose the
   diff to the operator; they edit. Tools allow Read+Bash only.
</constraints>

<signal_glossary>
- enabled:false        — shield is OFF; hook is a no-op.
- enabled:true         — shield is ON; empty bucket → exit 2.
- default_capacity     — bucket size when no per_skill override matches.
- default_refill_per_sec — token refill rate (per second) for the default.
- per_skill            — map of skill_name → {capacity, refill_per_sec}.
- BLOCKED stderr header — the hook just returned exit 2.
</signal_glossary>

<decision_tree>
IF developer asks "why was X blocked":
  → Read state/rate-policy.json → confirm enabled:true.
  → Read sibling rate-limiter/state/buckets.json (or this plugin's own
    state/buckets.json fallback) → find the (session, skill) entry.
  → Confirm tokens reached 0.0 and refill rate is too slow for the
    workload, OR a runaway loop drained it legitimately.
  → Recommend: raise per_skill capacity/refill, fix the loop, or wait
    for refill.

IF developer wants to enable the shield:
  → Confirm state/rate-policy.json exists (copy from .example.json).
  → Show the diff to set enabled:true.
  → Suggest starting with default_capacity:60 / refill:1.0 and tuning
    per_skill overrides for known-noisy skills.

IF developer wants to disable the shield:
  → Edit state/rate-policy.json: set enabled:false.
  → Hook becomes silent no-op until re-enabled.
</decision_tree>

<output_format>
## rate-shield — &lt;summary verb&gt;

**Policy enabled:** &lt;true | false&gt;
**Bucket source:** &lt;sibling rate-limiter | own fallback&gt;
**Active (session, skill):** &lt;sid::skill&gt;
**Capacity / refill:** &lt;n&gt; / &lt;r&gt;/sec
**Recent block:** &lt;ts&gt; — tokens reached 0.0

The shield is opt-in blocking; advisory velocity signals live in
pech-rate-limiter. Override of shared/foundations/conduct/hooks.md is logged in this
plugin's README.
</output_format>
