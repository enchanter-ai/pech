#!/usr/bin/env python3
"""
pech_publish.py — enchanted-mcp event-bus publisher (stub).

Reads an event payload from stdin (JSON), rate-limits per the brand contract (no per-call
emission — threshold crossings + rollups only), and dispatches to the bus.

In this v0.1.0 scaffold, the dispatcher is a stub that logs to state/published-events.jsonl
since the enchanted-mcp bus wire protocol is not yet finalized. Real implementation will
POST to the local bus endpoint. The rate-limiter contract is fully implemented here
because it's load-bearing regardless of transport.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
PUBLISH_STATE = PECH_ROOT / "plugins" / "budget-watcher" / "state"
PUBLISHED_LOG = PUBLISH_STATE / "published-events.jsonl"
RATE_LIMIT_STATE = PUBLISH_STATE / "publish-rate-limit.json"

# Per-event-type minimum interval between publishes (per scope-key)
RATE_LIMITS = {
    "pech.budget.threshold.crossed": timedelta(minutes=1),   # debounced by scope anyway
    "pech.anomaly.detected": timedelta(seconds=30),
    "pech.session.cost.finalized": timedelta(seconds=0),     # one per session, never rate-limit
    "pech.rate_card.refreshed": timedelta(seconds=0),
    "pech.rate_card.stale.warning": timedelta(days=1),
    "pech.attribution.orphan_rate.crossed": timedelta(minutes=5),
    "pech.learning.pattern.updated": timedelta(seconds=0),
}


def load_rate_limit_state() -> dict:
    if not RATE_LIMIT_STATE.exists():
        return {}
    try:
        with open(RATE_LIMIT_STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_rate_limit_state(state: dict) -> None:
    try:
        PUBLISH_STATE.mkdir(parents=True, exist_ok=True)
        tmp = RATE_LIMIT_STATE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, RATE_LIMIT_STATE)
    except Exception:
        pass


def rate_key(event: dict) -> str:
    name = event.get("event", "unknown")
    scope = event.get("scope", "")
    scope_key = event.get("scope_key", "")
    return f"{name}|{scope}|{scope_key}"


def should_publish(event: dict, state: dict) -> bool:
    name = event.get("event", "")
    min_interval = RATE_LIMITS.get(name)
    if min_interval is None or min_interval.total_seconds() == 0:
        return True  # no rate limit

    key = rate_key(event)
    last_iso = state.get(key)
    if not last_iso:
        return True

    try:
        last = datetime.fromisoformat(last_iso)
    except Exception:
        return True

    return datetime.now(timezone.utc) - last >= min_interval


def log_event(event: dict, published: bool, reason: str) -> None:
    try:
        PUBLISH_STATE.mkdir(parents=True, exist_ok=True)
        with open(PUBLISHED_LOG, "a", encoding="utf-8") as f:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "published": published,
                "reason": reason,
                "event": event,
            }
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception:
        pass


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception as e:
        print(f"pech_publish: invalid event JSON on stdin: {e}", file=sys.stderr)
        return 1

    if "event" not in event:
        print("pech_publish: event payload missing 'event' field", file=sys.stderr)
        return 1

    state = load_rate_limit_state()

    if not should_publish(event, state):
        log_event(event, published=False, reason="rate_limited")
        return 0  # silent skip — rate-limited is not an error

    # TODO: wire into enchanted-mcp bus when protocol lands. For now, log as the durable record.
    log_event(event, published=True, reason="dispatched")
    state[rate_key(event)] = datetime.now(timezone.utc).isoformat()
    save_rate_limit_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
