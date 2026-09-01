# Changelog

All notable changes to `pech` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-04-23

First public release: pech identity, standardized origin format.

### Added
- 7 sub-plugins tallying AI-assisted development spend across providers, models, and sessions, plus a `full` meta-plugin that installs them together.
- Named engines L1 through L5 — Exponential Smoothing as the defining engine for budget forecasting; Budget Boundary for per-project spend gates.
- Integration with Emu's runway algorithm for token accounting.
- Tier-1 governance docs: `SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.
- `.github/` scaffold: issue templates, PR template, CODEOWNERS, dependabot config.
- Tier-2 docs: `docs/getting-started.md`, `docs/installation.md`, `docs/troubleshooting.md`, `docs/adr/README.md`.

Track progress in [ROADMAP.md](docs/ROADMAP.md) and the [ecosystem map](docs/ecosystem.md).

[Unreleased]: https://github.com/enchanter-ai/pech/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/enchanter-ai/pech/releases/tag/v1.0.0
