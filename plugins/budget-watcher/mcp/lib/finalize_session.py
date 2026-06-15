#!/usr/bin/env python3
"""
finalize_session.py — Stop hook entry point.

Produces a daily rollup from the current session's rows and emits pech.session.cost.finalized.
The only on-stop cost-tracker action — everything else happens per-PostToolUse.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
COST_STATE = PECH_ROOT / "plugins" / "cost-tracker" / "state"
ROLLUP_DIR = COST_STATE / "rollups"


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


def update_daily_rollup(rows: list) -> dict:
    """Append session to today's daily rollup. Returns the updated rollup dict."""
    now = datetime.now(timezone.utc)
    rollup_file = ROLLUP_DIR / f"daily-{now.strftime('%Y-%m-%d')}.json"
    ROLLUP_DIR.mkdir(parents=True, exist_ok=True)

    existing = {"date": now.strftime("%Y-%m-%d"), "sessions": [], "total_usd": 0.0, "n_calls": 0}
    if rollup_file.exists():
        try:
            with open(rollup_file, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    session_total = sum(float(r.get("cost", {}).get("total_cost_usd", 0.0)) for r in rows)
    session_id = rows[0].get("attribution", {}).get("session_id", "unknown") if rows else "unknown"

    # Avoid duplicate if this session already rolled up (rare but possible with multi-Stop)
    if not any(s.get("session_id") == session_id for s in existing["sessions"]):
        existing["sessions"].append({
            "session_id": session_id,
            "n_calls": len(rows),
            "total_usd": round(session_total, 6),
            "finalized_at": now.isoformat(),
        })
        existing["total_usd"] = round(existing["total_usd"] + session_total, 6)
        existing["n_calls"] = existing["n_calls"] + len(rows)

    tmp = rollup_file.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, rollup_file)
    return existing


def main() -> int:
    rows = load_session_rows()
    if not rows:
        return 0

    update_daily_rollup(rows)

    # Emit finalize event (stub — would dispatch to enchanted-mcp bus in full implementation)
    session_id = rows[0].get("attribution", {}).get("session_id", "unknown")
    total = sum(float(r.get("cost", {}).get("total_cost_usd", 0.0)) for r in rows)
    print(f"[pech] session finalized: {session_id} — {len(rows)} calls, ${total:.4f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
