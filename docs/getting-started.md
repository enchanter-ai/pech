# Getting started with Pech

**Status: planned.** Pech has not shipped a public release yet. This page describes what the first release will look like. Until then, treat it as design intent, not documentation.

Pech is the ecosystem's cost tracker: every AI-assisted transaction tallied, every budget remembered, every forecast honest.

## Planned install

Once v0.1.0 ships:

```
/plugin marketplace add enchanter-ai/pech
/plugin install full@pech
```

## Planned commands

Commands already present in the repo tree:

| Command | What it will do |
|---------|-----------------|
| `/pech-cost` | Show current spend for this session, project, or time window. |
| `/pech-attribute` | Break spend down by provider, model, command, or sub-plugin. |
| `/pech-forecast` | Exponential-smoothing forecast (L1) of this week's / month's spend. |
| `/pech-report` | Full spend report — numbers, trends, top-3 cost sinks. |

## Planned engines

| ID | Name | Purpose |
|----|------|---------|
| L1 | Exponential Smoothing | Week-over-week spend forecast. |
| L2 | Budget Boundary | Per-project hard / soft spend caps with escalation. |
| L3–L5 | TBD | See [ROADMAP.md](ROADMAP.md). |

## Ecosystem fit

Pech answers the question *"What did it cost?"* in the Five Questions model (see [ecosystem.md](ecosystem.md)). It consumes Emu's token accounting and Hydra's audit trail, aggregates across sessions, and writes back to a per-project ledger.

## Until it ships

- Track progress in [ROADMAP.md](ROADMAP.md).
- Discuss design in [GitHub Discussions](https://github.com/enchanter-ai/pech/discussions).
- Report bugs against the planned interface only if you've read the source — the public API isn't stable yet.
