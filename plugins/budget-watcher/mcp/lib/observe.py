#!/usr/bin/env python3
"""
observe.py — Pech's PostToolUse hook entry point.

Reads the hook payload from stdin (Claude Code's hook contract), parses the API response's
usage field, looks up the rate, applies prompt-cache modifiers, and appends a ledger row.

Stdlib only — no external deps per brand invariant.
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
LEDGER_DIR = PECH_ROOT / "plugins" / "cost-tracker" / "state"
SESSION_FILE = LEDGER_DIR / "session.json"
RATE_CARD_FILE = PECH_ROOT / "shared" / "rate-card.json"
OBSERVE_LOG = LEDGER_DIR / "observe.log"


def log(msg: str) -> None:
    """Log to file, never stdout (stdout pollutes conversation)."""
    try:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        with open(OBSERVE_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except Exception:
        pass  # fail-open per @shared/vis/conduct/hooks.md


def load_rate_card() -> dict:
    """Load and return rate card. Empty dict if missing or corrupt (caller handles)."""
    try:
        with open(RATE_CARD_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"rate-card load failed: {e}")
        return {}


def parse_attribution() -> dict:
    """Read ENCHANTED_ATTRIBUTION env. Return empty dict (orphan) if missing/invalid."""
    raw = os.environ.get("ENCHANTED_ATTRIBUTION", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception as e:
        log(f"attribution parse failed: {e}")
        return {}


def extract_usage(hook_payload: dict) -> dict:
    """Walk the hook payload to find the API response's usage field.

    Claude Code hook payload shape varies by tool. The usage field lives at:
      hook_payload["tool_response"]["usage"]  (for model-invoking tools)
    """
    try:
        return hook_payload.get("tool_response", {}).get("usage", {}) or {}
    except Exception:
        return {}


def compute_cost(usage: dict, rate_card: dict, model: str, is_batch: bool = False) -> dict:
    """Compute cost breakdown for one API call. Returns {input_cost, output_cost, cache_write_cost, cache_read_cost, total_cost}."""
    if not rate_card:
        return {"total_cost_usd": 0.0, "rate_card_stale": True, "error": "no_rate_card"}

    models = rate_card.get("models", {})
    modifiers = rate_card.get("modifiers", {})
    fallback = rate_card.get("fallback_model_rate", {})

    rate = models.get(model)
    stale = False
    if rate is None:
        rate = fallback
        stale = True
        log(f"model {model!r} not in rate card; using fallback")

    input_rate = rate.get("input_rate_per_mtok", 0.0)
    output_rate = rate.get("output_rate_per_mtok", 0.0)
    cache_write_mod = modifiers.get("cache_write_modifier", 1.25)
    cache_read_mod = modifiers.get("cache_read_modifier", 0.10)
    batch_discount = modifiers.get("batch_discount", 1.0) if is_batch else 1.0

    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    cache_write_tokens = int(usage.get("cache_creation_input_tokens", 0))
    cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))

    input_cost = input_tokens * input_rate / 1_000_000
    output_cost = output_tokens * output_rate / 1_000_000
    cache_write_cost = cache_write_tokens * input_rate * cache_write_mod / 1_000_000
    cache_read_cost = cache_read_tokens * input_rate * cache_read_mod / 1_000_000

    total = (input_cost + output_cost + cache_write_cost + cache_read_cost) * batch_discount

    return {
        "input_cost_usd": round(input_cost * batch_discount, 6),
        "output_cost_usd": round(output_cost * batch_discount, 6),
        "cache_write_cost_usd": round(cache_write_cost * batch_discount, 6),
        "cache_read_cost_usd": round(cache_read_cost * batch_discount, 6),
        "total_cost_usd": round(total, 6),
        "is_batch": is_batch,
        "rate_card_stale": stale,
    }


def ledger_path() -> Path:
    now = datetime.now(timezone.utc)
    return LEDGER_DIR / f"ledger-{now.strftime('%Y-%m')}.jsonl"


def atomic_append(path: Path, line: str) -> bool:
    """Append a line to a file. Per @shared/vis/conduct/tool-use.md § Bash hygiene, do it safely."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")
        return True
    except Exception as e:
        log(f"ledger append failed: {e}")
        return False


def update_session_snapshot(row: dict) -> None:
    """Update session.json with running totals. Atomic rename via tmp file."""
    try:
        existing = {}
        if SESSION_FILE.exists():
            with open(SESSION_FILE, encoding="utf-8") as f:
                existing = json.load(f)

        existing.setdefault("session_id", row.get("attribution", {}).get("session_id", "unknown"))
        existing["last_updated"] = row["timestamp"]
        existing["cost_usd"] = round(existing.get("cost_usd", 0.0) + row["cost"]["total_cost_usd"], 6)
        existing["n_calls"] = existing.get("n_calls", 0) + 1
        existing["orphan_count"] = existing.get("orphan_count", 0) + (1 if row["attribution"].get("orphan") else 0)

        tmp = SESSION_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, SESSION_FILE)
    except Exception as e:
        log(f"session snapshot update failed: {e}")


def main() -> int:
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}

    usage = extract_usage(payload)
    if not usage:
        # No API call in this hook event (e.g. PostToolUse for Bash without a model round-trip).
        return 0  # fail-open

    attribution = parse_attribution()
    orphan = not attribution

    model = attribution.get("model", usage.get("model", "unknown"))
    is_batch = attribution.get("is_batch", False)

    rate_card = load_rate_card()
    cost = compute_cost(usage, rate_card, model, is_batch)

    row = {
        "row_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": {
            "plugin": attribution.get("plugin", ""),
            "sub_plugin": attribution.get("sub_plugin", ""),
            "skill": attribution.get("skill", ""),
            "agent_tier": attribution.get("agent_tier", ""),
            "model": model,
            "session_id": attribution.get("session_id", ""),
            "orphan": orphan,
        },
        "cache_behavior": _cache_behavior(usage),
        "usage": usage,
        "cost": cost,
        "rate_card_effective_from": rate_card.get("effective_from", "unknown"),
    }

    atomic_append(ledger_path(), json.dumps(row, separators=(",", ":")))
    update_session_snapshot(row)
    return 0  # always fail-open


def _cache_behavior(usage: dict) -> str:
    if int(usage.get("cache_creation_input_tokens", 0)) > 0:
        return "write"
    if int(usage.get("cache_read_input_tokens", 0)) > 0:
        return "read"
    return "none"


if __name__ == "__main__":
    sys.exit(main())
