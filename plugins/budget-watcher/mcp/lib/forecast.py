#!/usr/bin/env python3
"""
forecast.py — L1 Exponential Smoothing Forecast.

Invoked by /pech-forecast slash command (via forecast-cost skill). Reads the current
session's ledger, runs α-smoothing, projects forward to end-of-session/day/month with
±2σ confidence bands.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
COST_STATE = PECH_ROOT / "plugins" / "cost-tracker" / "state"

MIN_N = 3
DEFAULT_ALPHA = 0.3


def load_session_rows() -> list:
    """Read current session's ledger. Filter to current session_id if available."""
    now = datetime.now(timezone.utc)
    ledger = COST_STATE / f"ledger-{now.strftime('%Y-%m')}.jsonl"
    if not ledger.exists():
        return []
    try:
        with open(ledger, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []

    # Filter to current session if session.json tells us which one
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


def exponential_smoothing(series: list, alpha: float) -> tuple:
    """Return (smoothed_series, residuals_stdev)."""
    if not series:
        return ([], 0.0)
    smoothed = [series[0]]
    for y in series[1:]:
        smoothed.append(alpha * y + (1 - alpha) * smoothed[-1])
    residuals = [series[i] - smoothed[i] for i in range(1, len(series))]
    if len(residuals) < 2:
        return (smoothed, 0.0)
    mean_r = sum(residuals) / len(residuals)
    var = sum((r - mean_r) ** 2 for r in residuals) / len(residuals)
    return (smoothed, math.sqrt(var))


def project(scope: str, costs: list, alpha: float) -> dict:
    """Compute forecast for the requested scope."""
    if len(costs) < MIN_N:
        return {"insufficient_data": True, "n_observations": len(costs)}

    smoothed, sigma = exponential_smoothing(costs, alpha)
    last_smoothed = smoothed[-1]

    # Horizon steps depend on scope. Simple heuristic for session: extrapolate 1.5× current.
    if scope == "session":
        # Assume session continues at current rate; project 50% more calls
        remaining_calls = max(1, len(costs) // 2)
        point = sum(costs) + last_smoothed * remaining_calls
    elif scope == "day":
        now = datetime.now(timezone.utc)
        hours_remaining = 24 - now.hour
        # Current session's per-call rate × estimated remaining calls
        avg_per_call = sum(costs) / len(costs)
        calls_per_hour_est = max(1, len(costs) / max(1, now.hour or 1))
        point = sum(costs) + avg_per_call * calls_per_hour_est * hours_remaining
    elif scope == "month":
        now = datetime.now(timezone.utc)
        from calendar import monthrange
        days_in_month = monthrange(now.year, now.month)[1]
        days_remaining = days_in_month - now.day
        daily_est = sum(costs) / max(1, now.day)
        point = sum(costs) + daily_est * days_remaining
    else:
        return {"error": f"unknown scope {scope!r}"}

    # Confidence band: ±2σ scaled by projection variance (rough — real implementation
    # would accumulate variance per step).
    band = 2 * sigma * math.sqrt(max(1, len(costs)))

    return {
        "scope": scope,
        "n_observations": len(costs),
        "point_estimate_usd": round(point, 4),
        "sigma_usd": round(sigma, 6),
        "lower_band_usd": round(max(0, point - band), 4),
        "upper_band_usd": round(point + band, 4),
        "alpha": alpha,
    }


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description="L1 Exponential Smoothing Forecast")
    parser.add_argument("--scope", choices=["session", "day", "month"], default="session")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    rows = load_session_rows()
    costs = [float(r.get("cost", {}).get("total_cost_usd", 0.0)) for r in rows]

    result = project(args.scope, costs, args.alpha)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result.get("insufficient_data"):
            print(f"Pech forecast ({args.scope}): insufficient data "
                  f"(n={result['n_observations']}, need ≥ {MIN_N})")
        elif "error" in result:
            print(f"Pech forecast error: {result['error']}")
        else:
            print(f"Pech forecast ({args.scope})")
            print("─" * 60)
            print(f"  Point estimate:       ${result['point_estimate_usd']:.4f}")
            print(f"  ±2σ band:             [${result['lower_band_usd']:.4f}, ${result['upper_band_usd']:.4f}]")
            print(f"  σ per step:           ${result['sigma_usd']:.4f}")
            print(f"  Observations:         {result['n_observations']} calls")
            print(f"  α:                    {result['alpha']}")
            print("─" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
