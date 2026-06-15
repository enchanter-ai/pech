#!/usr/bin/env python3
"""
check_budget.py — PostToolUse hook entry point for budget-watcher's L2 Budget Boundary Detection.

Reads the most recent ledger row, updates per-scope counters, compares against ceilings in
plugins/budget-watcher/state/budgets.json, and emits pech.budget.threshold.crossed (via
pech_publish) the *first* time each threshold is crossed within each scope-window.

Debounce state lives in plugins/budget-watcher/state/thresholds.jsonl (append-only audit).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, date
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
COST_STATE = PECH_ROOT / "plugins" / "cost-tracker" / "state"
BUDGET_STATE = PECH_ROOT / "plugins" / "budget-watcher" / "state"
BUDGETS_FILE = BUDGET_STATE / "budgets.json"
COUNTERS_FILE = BUDGET_STATE / "counters.json"
THRESHOLDS_LOG = BUDGET_STATE / "thresholds.jsonl"

THRESHOLDS = (0.50, 0.80, 1.00)


def log_threshold(entry: dict) -> None:
    try:
        BUDGET_STATE.mkdir(parents=True, exist_ok=True)
        with open(THRESHOLDS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception:
        pass  # fail-open


def latest_ledger_row() -> dict:
    """Tail the current month's ledger, return the last row. Empty dict if none."""
    now = datetime.now(timezone.utc)
    ledger = COST_STATE / f"ledger-{now.strftime('%Y-%m')}.jsonl"
    if not ledger.exists():
        return {}
    try:
        with open(ledger, "rb") as f:
            f.seek(0, 2)  # end
            size = f.tell()
            if size == 0:
                return {}
            # Walk back to find the last newline
            buf = bytearray()
            pos = size - 1
            while pos >= 0:
                f.seek(pos)
                byte = f.read(1)
                if byte == b"\n" and buf:
                    break
                buf[:0] = byte
                pos -= 1
            return json.loads(buf.decode("utf-8"))
    except Exception:
        return {}


def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def atomic_write_json(path: Path, data) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def update_counters(row: dict) -> dict:
    """Increment per-scope counters. Returns updated counters dict."""
    counters = load_json(COUNTERS_FILE, {})

    now = datetime.now(timezone.utc)
    session_id = row.get("attribution", {}).get("session_id", "unknown")
    tier = row.get("attribution", {}).get("agent_tier", "unknown")
    model = row.get("attribution", {}).get("model", "unknown")
    cost = float(row.get("cost", {}).get("total_cost_usd", 0.0))

    scopes = {
        ("session", session_id): cost,
        ("hour", now.strftime("%Y-%m-%dT%H")): cost,
        ("day", now.strftime("%Y-%m-%d")): cost,
        ("month", now.strftime("%Y-%m")): cost,
    }

    for (scope, key), amount in scopes.items():
        counters.setdefault(scope, {})
        counters[scope].setdefault(key, {"total": 0.0, "by_tier": {}, "by_model": {}})
        c = counters[scope][key]
        c["total"] = round(c["total"] + amount, 6)
        c["by_tier"][tier] = round(c["by_tier"].get(tier, 0.0) + amount, 6)
        c["by_model"][model] = round(c["by_model"].get(model, 0.0) + amount, 6)

    atomic_write_json(COUNTERS_FILE, counters)
    return counters


def prior_crossings(scope: str, scope_key: str) -> set:
    """Return set of (threshold, axis) tuples that have already fired this scope-window."""
    if not THRESHOLDS_LOG.exists():
        return set()
    fired = set()
    try:
        with open(THRESHOLDS_LOG, encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("action") != "fire":
                    continue
                if entry.get("scope") == scope and entry.get("scope_key") == scope_key:
                    fired.add((entry["threshold"], entry.get("axis", "total")))
    except Exception:
        pass
    return fired


def check_and_fire(counters: dict, budgets: dict) -> list:
    """Compare counters to budgets, fire on new crossings. Returns list of events fired."""
    now = datetime.now(timezone.utc)
    session_id = None
    # Use the session of the most recent scope key
    for scope_key in counters.get("session", {}):
        session_id = scope_key
        break

    scope_keys = {
        "session": session_id or "unknown",
        "hour": now.strftime("%Y-%m-%dT%H"),
        "day": now.strftime("%Y-%m-%d"),
        "month": now.strftime("%Y-%m"),
    }

    events = []
    for scope in ("session", "hour", "day", "month"):
        scope_budget = budgets.get(scope)
        if not scope_budget:
            continue
        scope_key = scope_keys[scope]
        scope_counters = counters.get(scope, {}).get(scope_key)
        if not scope_counters:
            continue

        already = prior_crossings(scope, scope_key)

        # Total budget
        total_ceiling = scope_budget.get("total_usd")
        if total_ceiling:
            ratio = scope_counters["total"] / total_ceiling
            for t in THRESHOLDS:
                if ratio >= t and (t, "total") not in already:
                    event = {
                        "event": "pech.budget.threshold.crossed",
                        "scope": scope,
                        "scope_key": scope_key,
                        "axis": "total",
                        "threshold": t,
                        "ceiling_usd": total_ceiling,
                        "current_usd": round(scope_counters["total"], 4),
                        "ratio": round(ratio, 4),
                    }
                    events.append(event)
                    log_threshold({"action": "fire", "timestamp": now.isoformat(), **event})
                    already.add((t, "total"))

        # Per-tier budgets (e.g. opus_usd)
        for tier in ("opus", "sonnet", "haiku"):
            ceiling = scope_budget.get(f"{tier}_usd")
            if not ceiling:
                continue
            tier_total = scope_counters.get("by_tier", {}).get("orchestrator" if tier == "opus" else ("executor" if tier == "sonnet" else "validator"), 0.0)
            if tier_total <= 0:
                continue
            ratio = tier_total / ceiling
            for t in THRESHOLDS:
                if ratio >= t and (t, tier) not in already:
                    event = {
                        "event": "pech.budget.threshold.crossed",
                        "scope": scope,
                        "scope_key": scope_key,
                        "axis": tier,
                        "threshold": t,
                        "ceiling_usd": ceiling,
                        "current_usd": round(tier_total, 4),
                        "ratio": round(ratio, 4),
                    }
                    events.append(event)
                    log_threshold({"action": "fire", "timestamp": now.isoformat(), **event})
                    already.add((t, tier))

    return events


def _publish_event(event: dict, publish_py: Path) -> None:
    """Invoke pech_publish.py subprocess with the event JSON on stdin. Fail-open."""
    try:
        payload = json.dumps({
            "event": event["event"],
            "scope": event.get("scope", ""),
            "scope_key": event.get("scope_key", ""),
            "session_id": event.get("scope_key", ""),
            "plugin": "budget-watcher",
            "skill": "check-budget",
            "threshold": event.get("threshold"),
            "spend_to_date": event.get("current_usd"),
            "budget": event.get("ceiling_usd"),
            "crossed_at": datetime.now(timezone.utc).isoformat(),
        }, separators=(",", ":"))
        subprocess.run(
            [sys.executable, str(publish_py)],
            input=payload, text=True, timeout=5,
            capture_output=True,
        )
    except Exception as exc:
        print(f"[pech:check_budget] publish failed (non-fatal): {exc}", file=sys.stderr)


def main() -> int:
    row = latest_ledger_row()
    if not row:
        return 0  # no ledger → nothing to check

    budgets = load_json(BUDGETS_FILE, {})
    if not budgets:
        return 0  # no budgets configured → no threshold checking

    counters = update_counters(row)
    events = check_and_fire(counters, budgets)

    # Emit events via the publisher helper. Rate-limiting is handled by pech_publish.
    _PUBLISH_PY = Path(__file__).resolve().parent / "pech_publish.py"
    for event in events:
        _publish_event(event, _PUBLISH_PY)
        print(f"[pech] budget {event['threshold']*100:.0f}% crossed: "
              f"{event['scope']}/{event['axis']} at ${event['current_usd']}/${event['ceiling_usd']:.2f}",
              file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
