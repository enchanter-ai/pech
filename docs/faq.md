# Frequently asked questions

Quick answers to questions that don't yet have their own doc. For anything deeper, follow the links — the full answer usually lives in a neighboring file.

## What's the difference between Pech and the other siblings?

Pech answers *"what did it cost?"* — it tallies every token, attributes by plugin × sub-plugin × agent tier × model, and forecasts with honest confidence bands. Sibling plugins answer different questions in the same session: Wixie engineers prompts, Emu tracks session context health, Crow watches change trust, Hydra scans for security surface, Sylph coordinates git workflow. All are independent installs. See [docs/ecosystem.md](ecosystem.md) for the full map.

## Do I need the other siblings to use Pech?

Not strictly. Pech runs standalone and tallies whatever Claude Code sessions it observes. But its per-tier attribution relies on peer plugins setting the `ENCHANTED_ATTRIBUTION` environment variable before dispatching work — without that, Pech can only attribute at the parent-thread level (the same thing Anthropic's console already does). With siblings present, Pech gets plugin + sub-plugin + agent tier granularity.

## How do I report a bug vs. ask a question vs. disclose a security issue?

- **Security vulnerability** — private advisory, never a public issue. See [SECURITY.md](../SECURITY.md).
- **Reproducible bug** — a bug report issue with repro steps + exact versions.
- **Usage question or half-formed idea** — [Discussions](https://github.com/enchanter-ai/pech/discussions).

The [SUPPORT.md](../SUPPORT.md) page has the exact links for each.

## Is Pech an official Anthropic product?

No. Pech is an independent open-source plugin for [Claude Code](https://github.com/anthropics/claude-code) (Anthropic's CLI). It's published by [enchanter-ai](https://github.com/enchanter-ai) under the MIT license and is not affiliated with, endorsed by, or supported by Anthropic.

## Is Pech available now?

No. Pech is Phase 1 #5 in the @enchanter-ai rollout and is pre-release. The README and engine IDs (L1 Exponential Smoothing, L2 Budget Boundary, L3-L5) describe the committed public surface, but no v0.1.0 tag has shipped yet. Track progress in [docs/ROADMAP.md](ROADMAP.md) and the [ecosystem map](https://github.com/enchanter-ai/wixie/blob/main/docs/ecosystem.md).

## How does Pech know the cost per agent tier if Anthropic's console doesn't?

At dispatch time, each peer plugin in the ecosystem sets `ENCHANTED_ATTRIBUTION` with the plugin / sub-plugin / skill / agent tier / model that originated the call. Pech's `PostToolUse` hook reads this env var, looks up the model in a committed `shared/rate-card.json`, applies prompt-cache modifiers (writes 1.25×, reads 0.1×, batch 0.5×), and appends a row to the ledger. What Anthropic's console shows as one "org total" line becomes thirty plugin-tier-model rows.
