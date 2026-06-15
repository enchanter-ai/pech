#!/usr/bin/env python3
"""
load_rate_card.py — SessionStart hook entry point for rate-card-keeper.

Loads shared/rate-card.json, validates schema, checks staleness, emits events.
Blocks SessionStart (exit non-zero) only if the card is > 180 days old — that's the one
place a Pech hook refuses to proceed, because observing against a dangerously stale
card produces silently-wrong cost data.

Stdlib only.
"""

import json
import os
import sys
from datetime import date
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
RATE_CARD_FILE = PECH_ROOT / "shared" / "rate-card.json"
LOG_FILE = PECH_ROOT / "plugins" / "rate-card-keeper" / "state" / "load.log"


def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


REQUIRED_TOP_KEYS = {"effective_from", "currency", "models", "modifiers", "fallback_model_rate"}
REQUIRED_MODEL_KEYS = {"input_rate_per_mtok", "output_rate_per_mtok"}
REQUIRED_MODIFIER_KEYS = {"cache_write_modifier", "cache_read_modifier", "batch_discount"}


def validate_schema(card: dict) -> list:
    """Return list of error strings; empty list = valid."""
    errors = []

    missing = REQUIRED_TOP_KEYS - set(card.keys())
    if missing:
        errors.append(f"missing top-level keys: {sorted(missing)}")
        return errors  # further validation is moot

    if not isinstance(card["models"], dict) or not card["models"]:
        errors.append("models must be a non-empty object")

    for model, rates in card.get("models", {}).items():
        if not isinstance(rates, dict):
            errors.append(f"model {model!r}: rates must be an object")
            continue
        missing_rate = REQUIRED_MODEL_KEYS - set(rates.keys())
        if missing_rate:
            errors.append(f"model {model!r}: missing {sorted(missing_rate)}")
        for k in REQUIRED_MODEL_KEYS:
            v = rates.get(k)
            if not isinstance(v, (int, float)) or v < 0:
                errors.append(f"model {model!r}: {k} must be a positive number, got {v!r}")

    modifiers = card.get("modifiers", {})
    missing_mod = REQUIRED_MODIFIER_KEYS - set(modifiers.keys())
    if missing_mod:
        errors.append(f"modifiers: missing {sorted(missing_mod)}")

    cw = modifiers.get("cache_write_modifier")
    cr = modifiers.get("cache_read_modifier")
    bd = modifiers.get("batch_discount")
    if isinstance(cw, (int, float)) and isinstance(cr, (int, float)):
        if not (cr < 1.0 < cw):
            errors.append(f"modifier sanity failed: expected cache_read_modifier ({cr}) < 1.0 < cache_write_modifier ({cw})")
    if isinstance(bd, (int, float)) and not (0 < bd <= 1.0):
        errors.append(f"batch_discount must be in (0, 1], got {bd!r}")

    return errors


def days_old(iso_date: str) -> int:
    try:
        d = date.fromisoformat(iso_date)
        return (date.today() - d).days
    except Exception:
        return -1


def main() -> int:
    if not RATE_CARD_FILE.exists():
        log(f"ERROR: rate-card not found at {RATE_CARD_FILE}")
        print(f"[pech] WARN: rate-card.json missing — cost attribution disabled until restored", file=sys.stderr)
        return 0  # fail-open

    try:
        with open(RATE_CARD_FILE, encoding="utf-8") as f:
            card = json.load(f)
    except Exception as e:
        log(f"ERROR: rate-card parse failed: {e}")
        print(f"[pech] ERROR: rate-card.json is not valid JSON: {e}", file=sys.stderr)
        return 0  # fail-open — better to lose one session's cost data than block the session

    errors = validate_schema(card)
    if errors:
        for err in errors:
            log(f"ERROR: {err}")
            print(f"[pech] rate-card schema error: {err}", file=sys.stderr)
        print("[pech] WARN: rate-card invalid — all ledger rows will be tagged rate_card_stale=true", file=sys.stderr)
        return 0  # fail-open; observation will flag rows as stale

    age = days_old(card.get("effective_from", ""))

    if age < 0:
        log(f"WARN: effective_from unparseable")
    elif age <= 60:
        log(f"OK: rate-card {age} days old")
    elif age <= 90:
        log(f"WARN: rate-card {age} days old (> 60)")
        print(f"[pech] rate-card.json is {age} days old — consider refreshing via the nightly CI job", file=sys.stderr)
    elif age <= 180:
        log(f"WARN: rate-card {age} days old (> 90) — tagging rows stale")
        print(f"[pech] WARN: rate-card.json is {age} days old. All ledger rows will be tagged rate_card_stale=true until refreshed.", file=sys.stderr)
    else:
        log(f"ERROR: rate-card {age} days old (> 180) — blocking")
        print(f"[pech] ERROR: rate-card.json is {age} days old (> 180). Refusing to observe — cost data would be dangerously wrong.", file=sys.stderr)
        print("[pech] Run the nightly CI refresh workflow or manually update shared/rate-card.json before continuing.", file=sys.stderr)
        return 1  # block SessionStart

    return 0


if __name__ == "__main__":
    sys.exit(main())
