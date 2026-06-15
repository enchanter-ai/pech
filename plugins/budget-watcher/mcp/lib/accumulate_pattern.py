#!/usr/bin/env python3
"""
accumulate_pattern.py — L5 Gauss Learning (Pech).

PreCompact hook. Reads the current session's ledger, groups by attribution key,
updates per-developer patterns in plugins/pech-learning/state/learnings.json with
slow exponential smoothing (α = 0.05). Exports a snapshot to shared/learnings.json.

Atomic write via temp-rename (Emu-A4 pattern).
"""

import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
COST_STATE = PECH_ROOT / "plugins" / "cost-tracker" / "state"
LEARNINGS_FILE = PECH_ROOT / "plugins" / "pech-learning" / "state" / "learnings.json"
SHARED_LEARNINGS = PECH_ROOT / "shared" / "learnings.json"

ALPHA = 0.05  # slow accumulator — one session doesn't skew patterns


def load_session_rows() -> list:
    now = datetime.now(timezone.utc)
    ledger = COST_STATE / f"ledger-{now.strftime('%Y-%m')}.jsonl"
    if not ledger.exists():
        return []
    try:
        with open(ledger, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []

    session_file = COST_STATE / "session.json"
    current_session = None
    if session_file.exists():
        try:
            with open(session_file, encoding="utf-8") as f:
                current_session = json.load(f).get("session_id")
        except Exception:
            pass
    if current_session:
        rows = [r for r in rows if r.get("attribution", {}).get("session_id") == current_session]
    return rows


def key_for(attr: dict) -> str:
    if not attr.get("plugin") or attr.get("orphan"):
        return None
    skill = attr.get("skill") or "hook"
    tier = attr.get("agent_tier") or "unknown"
    return f"{attr['plugin']}:{skill}:{tier}"


def group_session_stats(rows: list) -> dict:
    """Group session rows by attribution key, compute per-key session-local stats."""
    grouped = {}
    for r in rows:
        key = key_for(r.get("attribution", {}))
        if not key:
            continue
        grouped.setdefault(key, []).append(float(r.get("cost", {}).get("total_cost_usd", 0.0)))

    stats_by_key = {}
    for key, costs in grouped.items():
        if len(costs) < 2:
            stats_by_key[key] = {
                "session_mean": costs[0] if costs else 0.0,
                "session_stdev": 0.0,
                "session_n": len(costs),
                "session_p50": costs[0] if costs else 0.0,
                "session_p95": costs[0] if costs else 0.0,
            }
        else:
            costs_sorted = sorted(costs)
            stats_by_key[key] = {
                "session_mean": statistics.mean(costs),
                "session_stdev": statistics.pstdev(costs),
                "session_n": len(costs),
                "session_p50": statistics.median(costs_sorted),
                "session_p95": costs_sorted[min(len(costs_sorted) - 1, int(len(costs_sorted) * 0.95))],
            }
    return stats_by_key


def update_accumulator(stats_by_key: dict) -> dict:
    """Load prior learnings, update with session stats, return new learnings dict."""
    prior = {"version": 1, "n_sessions_accumulated": 0, "patterns": {}}
    if LEARNINGS_FILE.exists():
        try:
            with open(LEARNINGS_FILE, encoding="utf-8") as f:
                prior = json.load(f)
        except Exception:
            pass

    patterns = prior.get("patterns", {})
    now_iso = datetime.now(timezone.utc).isoformat()

    for key, s in stats_by_key.items():
        if key in patterns:
            p = patterns[key]
            # Slow exponential update — one session barely moves the learned pattern
            p["mu_cost_usd"] = (1 - ALPHA) * p["mu_cost_usd"] + ALPHA * s["session_mean"]
            p["sigma_cost_usd"] = (1 - ALPHA) * p["sigma_cost_usd"] + ALPHA * s["session_stdev"]
            p["p50"] = (1 - ALPHA) * p["p50"] + ALPHA * s["session_p50"]
            p["p95"] = (1 - ALPHA) * p["p95"] + ALPHA * s["session_p95"]
            p["n_observations"] = p.get("n_observations", 0) + s["session_n"]
            p["last_session"] = now_iso
        else:
            patterns[key] = {
                "n_observations": s["session_n"],
                "mu_cost_usd": s["session_mean"],
                "sigma_cost_usd": s["session_stdev"],
                "p50": s["session_p50"],
                "p95": s["session_p95"],
                "last_session": now_iso,
            }

    return {
        "version": 1,
        "last_updated": now_iso,
        "n_sessions_accumulated": prior.get("n_sessions_accumulated", 0) + 1,
        "patterns": patterns,
    }


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


def export_to_shared(learnings: dict) -> None:
    """Append Pech's section to shared/learnings.json without clobbering peer sections."""
    shared = {}
    if SHARED_LEARNINGS.exists():
        try:
            with open(SHARED_LEARNINGS, encoding="utf-8") as f:
                shared = json.load(f)
        except Exception:
            shared = {}
    shared["pech"] = {
        "last_updated": learnings["last_updated"],
        "n_sessions_accumulated": learnings["n_sessions_accumulated"],
        "patterns": learnings["patterns"],
    }
    atomic_write_json(SHARED_LEARNINGS, shared)


def main() -> int:
    rows = load_session_rows()
    if len(rows) < 5:
        return 0  # too few observations to learn from

    stats = group_session_stats(rows)
    if not stats:
        return 0  # all orphans → nothing to learn

    learnings = update_accumulator(stats)
    ok = atomic_write_json(LEARNINGS_FILE, learnings)
    if ok:
        export_to_shared(learnings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
