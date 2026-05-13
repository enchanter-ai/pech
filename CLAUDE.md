# Pech — Agent Contract

Audience: Claude. Pech is the cost ledger for AI-assisted development — attributes every token, tool-use turn, prompt-cache hit/write, and batch job to the plugin / sub-plugin / skill / agent tier / model that fired it. Forecasts spend, fires budget thresholds, surfaces cache waste, learns per-developer patterns.

## Shared behavioral modules

These apply to every skill in every plugin. Load once; do not re-derive.

- @../foundations/packages/core/conduct/discipline.md — coding conduct: think-first, simplicity, surgical edits, goal-driven loops
- @../foundations/packages/core/conduct/capability-fidelity.md — contracts survive capability gaps: recover, escalate, or abort; never silently substitute
- @../foundations/packages/core/conduct/context.md — attention-budget hygiene, U-curve placement, checkpoint protocol
- @../foundations/packages/core/conduct/verification.md — independent checks, baseline snapshots, dry-run for destructive ops
- @../foundations/packages/core/conduct/doubt-engine.md — adversarial self-check before agreement; counter to F01 sycophancy; fires on user proposals AND your own prior framing
- @../foundations/packages/core/conduct/delegation.md — subagent contracts, tool whitelisting, parallel vs. serial rules
- @../foundations/packages/core/conduct/failure-modes.md — 14-code taxonomy for accumulated-learning logs
- @../foundations/packages/core/conduct/tool-use.md — tool-choice hygiene, error payload contract, parallel-dispatch rules
- @../foundations/packages/skills/conduct/formatting.md — per-target format (XML/Markdown/minimal/few-shot), prefill + stop sequences
- @../foundations/packages/skills/conduct/skill-authoring.md — SKILL.md frontmatter discipline, discovery test
- @../foundations/packages/core/conduct/hooks.md — advisory-only hooks, injection over denial, fail-open
- @../foundations/packages/core/conduct/precedent.md — log self-observed failures to `state/precedent-log.md`; consult before risky steps
- @../foundations/packages/core/conduct/tier-sizing.md — prompt verbosity scales inversely with model tier; Haiku needs mechanical steps, Opus runs on intent
- @../foundations/packages/web/conduct/web-fetch.md — external URL handling: cache, dedup, budget; WebFetch is Haiku-tier-only

When a module conflicts with a plugin-local instruction, the plugin wins — but log the override.

## Lifecycle

Pech is **hook-driven**. The observation loop never asks permission — every tool call is measured silently. Skill-invocation is only for developer-facing queries (`/pech-cost`, `/pech-forecast`, `/pech-attribute`, `/pech-report`).

| Event or Skill | Sub-plugin | Role |
|---|---|---|
| `SessionStart` | rate-card-keeper | Load rate-card.json; emit staleness warning if > 90 days old |
| `SessionStart` | cost-tracker | Initialize session ledger; reset in-memory rollup counters |
| `PostToolUse` (any tool) | cost-tracker | Read API `usage` field from the model response; read `ENCHANTED_ATTRIBUTION` env; write ledger row (L1 + L4 measurement) |
| `PostToolUse` (any tool) | budget-watcher | Increment per-scope counters; check thresholds (L2); check Z-score (L3); publish on crossing |
| `Stop` | cost-tracker | Finalize session rollup; publish `pech.session.cost.finalized` |
| `PreCompact` | pech-learning | Persist per-developer spend patterns (L5); export to `shared/learnings.json` |
| `/pech-cost [scope]` | cost-query | Display current spend (session by default; `--day`, `--month`) |
| `/pech-forecast [scope]` | cost-query | Display L1 forecast with confidence band |
| `/pech-attribute [tool]` | cost-query | Break down last N calls by plugin/tier/model |
| `/pech-report` | cost-query | Generate dark-themed PDF audit (Opus orchestrator for anomaly triage) |

See `./plugins/<name>/hooks/hooks.json` for matchers. Agents in `./plugins/<name>/agents/`.

## Algorithms

L1 Exponential Smoothing · L2 Budget Boundary Detection · L3 Z-Score Cost Anomaly · L4 Cache-Waste Measurement · L5 Gauss Learning (Pech). Derivations in `docs/science/README.md`. **Defining engine:** L1 — forecasting is what makes cost data actionable; raw ledgers are just bookkeeping.

| ID | Name | Plugin | Algorithm |
|----|------|--------|-----------|
| L1 | Exponential Smoothing Forecast | cost-tracker | `ŷ_t+1 = α·y_t + (1−α)·ŷ_t`, α = 0.3. Horizons: session, day, month. Confidence: ±2σ over residual series. |
| L2 | Budget Boundary Detection | budget-watcher | Per-scope counters (session / hour / day / month, per tier, per model). Threshold crossings at 50/80/100% debounced once-per-window. |
| L3 | Z-Score Cost Anomaly | budget-watcher | Rolling mean μ + σ over last 30 calls of same attribution tuple. Anomaly when `|y − μ| > 3σ`. Alerts on spikes *and* drops (drops signal cache-hit regressions). |
| L4 | Cache-Waste Measurement | cost-tracker | Cache hit ratio = reads / (reads + writes + misses). Waste = writes with no downstream reads within session. Surfaces as `$X wasted on unread cache writes`. |
| L5 | Gauss Learning (Pech) | pech-learning | Weighted moving averages over per-developer spend signals (per skill, per session type). Emu-A4 atomic serialization. |

## Behavioral contracts

Markers: **[H]** hook-enforced (deterministic) · **[A]** advisory (relies on your adherence).

1. **IMPORTANT — Silent by default, loud at thresholds.** [A] Observation is invisible. Only 50/80/100% budget crossings and L3 anomalies surface to the developer. Raw per-call noise stays in the ledger. Breaking this floods the conversation and trains the developer to mute cost signal.
2. **YOU MUST consume Emu's A2 token counts — never re-tokenize.** [A] A2 Linear Runway Forecasting owns token counting. Pech reads the API response's `usage` field (authoritative) and Emu's published events (for in-flight estimates). Re-tokenizing duplicates CPU and creates a second counter that will drift out of sync.
3. **YOU MUST NOT emit per-call events on the bus.** [H] Event-bus traffic scales with threshold crossings + rollups, never with call volume. At 10k calls/day per-call emission floods every subscriber. Enforced by the `pech_publish` helper in `shared/constants.sh` which rate-limits to one event per scope-window.
4. **YOU MUST attribute per agent tier, not per parent thread.** [A] A Wixie `/converge` run fires Opus (~$0.06) → Sonnet loop (~$2.00) → Haiku validator (~$0.003). Naïve parent-thread attribution puts Sonnet under Opus's line, making Opus look 30× costlier. `ENCHANTED_ATTRIBUTION.agent_tier` is set at dispatch time.
5. **YOU MUST treat orphan spend as a bug signal, not a default bucket.** [A] A hook that fires a model call without setting `ENCHANTED_ATTRIBUTION` is broken. Surface orphan rate as a first-class health metric (`pech.attribution.orphan_rate.crossed` at > 1%). Do not quietly bucket orphans into a generic "other".
6. **ESCALATE on rate-card staleness > 90 days.** [A] The rate-card.json is committed; CI refreshes nightly via PR. If SessionStart finds a rate card older than 90 days, emit a warning and tag all downstream cost rows with `rate_card_stale: true` so forecasts flag themselves.
7. **Ask, don't guess.** [A] If `ENCHANTED_ATTRIBUTION` is missing for a call that is clearly part of a skill invocation, ask the developer which plugin/skill is responsible before writing the ledger row. Never fabricate attribution to clean up the orphan rate.
8. **ESCALATE on hard-budget fire mid-Sonnet-loop.** [A] If a hard budget fires during an in-progress executor loop, emit the threshold event and let the current iteration finish, then halt. Never kill mid-token — partial output with `budget_blocked` status is cheaper to reason about than a raw kill.

## Budget enforcement modes

| Mode | Trigger | Action | Escape hatch |
|------|---------|--------|--------------|
| Advisory (default) | Threshold at 50/80/100% | Emit `pech.budget.threshold.crossed`; peer plugins degrade (Wixie → Haiku; Sylph → defer PR polish) | None needed — advisory only |
| Hard (opt-in via `PECH_HARD_BUDGET=1`) | Threshold at 100% | Route to `sylph-gate` for dev confirmation to continue | `--yes-i-know-cost` flag for one invocation |
| Hybrid (opt-in via `PECH_HYBRID_BUDGET=1`) | Advisory for Sonnet/Haiku; hard for Opus > $5/hour | Per-tier enforcement | Per-tier escape hatches |

## State paths

| State file | Owner | Purpose |
|---|---|---|
| `plugins/cost-tracker/state/ledger-YYYY-MM.jsonl` | cost-tracker | Append-only per-call cost rows, monthly rotation, 90-day retention |
| `plugins/cost-tracker/state/rollups/daily-YYYY-MM-DD.json` | cost-tracker | Daily pre-aggregated rollups, forever retention |
| `plugins/cost-tracker/state/session.json` | cost-tracker | In-memory snapshot of current session's counters |
| `plugins/budget-watcher/state/budgets.json` | budget-watcher | Per-scope budget ceilings (developer config) |
| `plugins/budget-watcher/state/thresholds.jsonl` | budget-watcher | Log of threshold crossings (for debounce state + audit) |
| `plugins/rate-card-keeper/state/rate-card.json` | rate-card-keeper | Per-model rates + modifiers + effective dates |
| `plugins/pech-learning/state/learnings.json` | pech-learning | Per-developer spend patterns (L5 Gauss Accumulation) |
| `plugins/<name>/state/precedent-log.md` | all | Self-observed operational failures (see @../foundations/packages/core/conduct/precedent.md) |
| `shared/learnings.json` | exporter | Cross-plugin aggregated learnings |

## Agent tiers

| Tier | Model | Used for |
|---|---|---|
| Orchestrator | Opus | `/pech-report` anomaly triage ("why did this session spike?"); L3 anomaly narrative generation |
| Executor | Sonnet | L1 forecasting loop over residual series; rollup aggregation; ledger compaction |
| Validator | Haiku | Rate-card schema validation at SessionStart; tag-completeness audit; ledger-row JSON validation |

Respect the tiering. Routing a Haiku validation task to Opus burns budget and breaks the cost contract — which is *especially* embarrassing for the plugin whose job is cost discipline.

## Anti-patterns

- **Re-tokenizing client-side.** Emu's A2 already does this; Anthropic's API returns authoritative `usage`. Two counters drift, CPU doubles, cost signal worsens.
- **Per-tool-call event bus emission.** At high volume, this defeats the purpose of the bus and turns every subscriber into infrastructure. Threshold + rollup only.
- **Silent orphan bucket.** A call without `ENCHANTED_ATTRIBUTION` is a bug upstream. Don't paper over it with a "misc" bucket that grows without bound.
- **Runtime rate-card fetch.** Adds a network call to the hot path, breaks offline dev, violates zero-deps brand standard. The rate card is committed JSON refreshed by CI.
- **Hard-block without developer opt-in.** Pech is showback by default. Surprise-blocking a `/converge` run mid-loop destroys trust; the developer owns the decision to enforce.
- **Inflated pseudo-precision.** Cost forecasts without confidence bands lie. L1 always reports ±2σ. Point estimates are banned.

---

## Brand invariants (survive unchanged into every sibling)

1. **Zero external runtime deps.** Hooks: bash + jq. Scripts: Python 3.8+ stdlib only. Rate-card.json is committed, refreshed by CI.
2. **Managed agent tiers.** Opus = judgment (anomaly triage). Sonnet = executor (forecasting loop). Haiku = validator (schema checks).
3. **Named formal algorithm per engine.** L-prefix, academic-style names: `[Method] [Domain] [Action]`.
4. **Emu-style marketplace.** 5 sub-plugins + `full` meta, each shipping `.claude-plugin/plugin.json` + `{agents,commands,hooks,skills,state}/` + `README.md`.
5. **Dark-themed PDF report.** `/pech-report` produces it via `docs/architecture/generate.py` + puppeteer.
6. **Gauss Accumulation learning.** L5 persists per-developer patterns; exported to `shared/learnings.json`.
7. **enchanted-mcp event bus.** Threshold crossings + rollups only, never per call.
8. **Diagrams from source of truth.** `docs/architecture/generate.py` reads `plugin.json` + `hooks.json` + `SKILL.md` → writes four mermaid diagrams + `index.html`. Never hand-edited.

Events this plugin publishes: `pech.budget.threshold.crossed`, `pech.session.cost.finalized`, `pech.rate_card.refreshed`, `pech.rate_card.stale`, `pech.attribution.orphan_rate.crossed`, `pech.anomaly.detected`
Events this plugin subscribes to: `emu.api.usage.observed` (primary cost input), `emu.runway.threshold.crossed` (forecast correlation), `wixie.prompt.crafted` (attribution context), `crow.change.classified` (attribution context), `hydra.prepush.secret.detected` (attribution context), `sylph.task.boundary.detected` (attribution context), `sylph.commit.committed` (attribution context)
