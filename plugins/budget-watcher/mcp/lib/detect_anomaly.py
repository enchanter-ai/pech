#!/usr/bin/env python3
"""
detect_anomaly.py — L3 Z-Score Cost Anomaly Detection.

Runs after every ledger row. Computes z-score against the last 30 rows matching the same
attribution tuple. Falls back to pech-learning's persisted patterns if in-session N < 30.
Emits pech.anomaly.detected when |z| > 3 (both spikes and drops).
"""

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
COST_STATE = PECH_ROOT / "plugins" / "cost-tracker" / "state"
BUDGET_STATE = PECH_ROOT / "plugins" / "budget-watcher" / "state"
LEARNINGS_FILE = PECH_ROOT / "plugins" / "pech-learning" / "state" / "learnings.json"
ANOMALIES_LOG = BUDGET_STATE / "anomalies.jsonl"

Z_THRESHOLD = 3.0
MIN_N = 30


def latest_ledger_rows(n: int) -> list:
    """Read the last ~N*4 rows from the current month's ledger (overread to allow filtering)."""
    now = datetime.now(timezone.utc)
    ledger = COST_STATE / f"ledger-{now.strftime('%Y-%m')}.jsonl"
    if not ledger.exists():
        return []
    try:
        with open(ledger, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(line) for line in lines[-n*4:] if line.strip()]
    except Exception:
        return []


def match_tuple(row: dict, tup: dict) -> bool:
    a = row.get("attribution", {})
    return all(a.get(k) == tup[k] for k in tup)


def welford_stats(values: list) -> tuple:
    """Return (mean, population stdev) via stable online algorithm."""
    n = 0
    mean = 0.0
    m2 = 0.0
    for x in values:
        n += 1
        delta = x - mean
        mean += delta / n
        delta2 = x - mean
        m2 += delta * delta2
    if n < 2:
        return (mean, 0.0)
    return (mean, math.sqrt(m2 / n))


def historical_prior(tup: dict) -> dict:
    """Read pech-learning's persisted pattern. Returns None if not found."""
    if not LEARNINGS_FILE.exists():
        return None
    try:
        with open(LEARNINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        patterns = data.get("patterns", {})
        # Try exact: plugin:skill:tier → then less specific
        keys = [
            f"{tup.get('plugin')}:{tup.get('skill')}:{tup.get('agent_tier')}",
            f"{tup.get('plugin')}:{tup.get('agent_tier')}",
            tup.get("plugin", ""),
        ]
        for key in keys:
            if key and key in patterns:
                p = patterns[key]
                return {
                    "mu": p["mu_cost_usd"],
                    "sigma": p["sigma_cost_usd"],
                    "source": f"learnings:{key}",
                }
        return None
    except Exception:
        return None


def log_anomaly(entry: dict) -> None:
    try:
        ANOMALIES_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ANOMALIES_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _publish_anomaly(entry: dict, tup: dict) -> None:
    """Emit pech.anomaly.detected via pech_publish subprocess. Fail-open."""
    publish_py = Path(__file__).resolve().parent / "pech_publish.py"
    try:
        payload = json.dumps({
            "event": "pech.anomaly.detected",
            "session_id": os.environ.get("ENCHANTED_SESSION_ID", "unknown"),
            "plugin": tup.get("plugin", ""),
            "skill": tup.get("skill", ""),
            "agent_tier": tup.get("agent_tier", ""),
            "model": tup.get("model", ""),
            "z_score": entry.get("z_score"),
            "detected_at": entry.get("timestamp"),
        }, separators=(",", ":"))
        subprocess.run(
            [sys.executable, str(publish_py)],
            input=payload, text=True, timeout=5,
            capture_output=True,
        )
    except Exception as exc:
        print(f"[pech:detect_anomaly] publish failed (non-fatal): {exc}", file=sys.stderr)


def main() -> int:
    rows = latest_ledger_rows(MIN_N + 50)
    if not rows:
        return 0

    current = rows[-1]
    current_attr = current.get("attribution", {})

    # Skip orphans — anomalies require attribution
    if current_attr.get("orphan"):
        return 0

    tup = {
        "plugin": current_attr.get("plugin"),
        "sub_plugin": current_attr.get("sub_plugin"),
        "skill": current_attr.get("skill"),
        "agent_tier": current_attr.get("agent_tier"),
        "model": current_attr.get("model"),
    }
    if not all(tup.values()):
        return 0  # incomplete attribution → skip

    # In-session history
    matches = [r for r in rows[:-1] if match_tuple(r, tup)]
    costs = [float(r.get("cost", {}).get("total_cost_usd", 0.0)) for r in matches]

    mu = sigma = None
    source = "session"

    if len(costs) >= MIN_N:
        mu, sigma = welford_stats(costs)
    else:
        prior = historical_prior(tup)
        if prior:
            mu, sigma = prior["mu"], prior["sigma"]
            source = prior["source"]

    if mu is None or sigma is None or sigma <= 0:
        return 0  # insufficient data

    current_cost = float(current.get("cost", {}).get("total_cost_usd", 0.0))
    z = (current_cost - mu) / sigma

    if abs(z) <= Z_THRESHOLD:
        return 0  # not an anomaly

    entry = {
        "event": "pech.anomaly.detected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution_tuple": tup,
        "current_cost_usd": round(current_cost, 6),
        "rolling_mean_usd": round(mu, 6),
        "rolling_sigma_usd": round(sigma, 6),
        "z_score": round(z, 3),
        "direction": "spike" if z > 0 else "drop",
        "n_history": len(costs),
        "source": source,
    }
    log_anomaly(entry)
    _publish_anomaly(entry, tup)

    # Surface to developer via stderr (the only legitimate mid-session Pech signal)
    print(f"[pech] anomaly ({'spike' if z > 0 else 'drop'}): "
          f"{tup['plugin']}/{tup['skill']}/{tup['agent_tier']} at ${current_cost:.4f} "
          f"(|z|={abs(z):.1f}σ, μ=${mu:.4f})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
