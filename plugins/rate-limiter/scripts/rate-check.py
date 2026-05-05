#!/usr/bin/env python3
"""rate-check.py — Advisory token-bucket rate limiter for PreToolUse.

Per (session, skill) bucket. Default 60 tokens, refill 1/sec. Each call
consumes 1. When empty: emit stderr advisory and continue (always exit 0).

Atomic read-modify-write of state/buckets.json with cross-platform locking.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or
                   Path(__file__).resolve().parent.parent)
STATE_FILE = PLUGIN_ROOT / "state" / "buckets.json"

DEFAULT_CONFIG = {"capacity": 60, "refill_per_sec": 1.0}


def session_id() -> str:
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    seed = f"{os.getcwd()}:{os.getppid()}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def current_skill() -> str:
    """Best-effort: most recently entered skills/<name>/ dir from cwd ancestry,
    else 'ungated'."""
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        if parent.name.startswith("skills") or parent.parent.name == "skills":
            # walk up to find a path component preceded by 'skills'
            parts = parent.parts
            for i, p in enumerate(parts):
                if p == "skills" and i + 1 < len(parts):
                    return parts[i + 1]
    return "ungated"


def _lock_file(fh):
    if sys.platform == "win32":
        import msvcrt
        # Lock 1 byte at start; LK_LOCK blocks until acquired.
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _unlock_file(fh):
    if sys.platform == "win32":
        import msvcrt
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def load_state(fh) -> dict:
    fh.seek(0)
    raw = fh.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def write_state(fh, data: dict) -> None:
    fh.seek(0)
    fh.truncate()
    fh.write(json.dumps(data, indent=2, sort_keys=True))
    fh.flush()
    os.fsync(fh.fileno())


def get_config(state: dict, skill: str) -> dict:
    per_skill = state.get("per_skill", {}) or {}
    if skill in per_skill:
        return per_skill[skill]
    return state.get("global_default", DEFAULT_CONFIG)


def main() -> int:
    if not STATE_FILE.exists():
        # Opt-in: hook should have caught this, but double-guard.
        return 0

    sid = session_id()
    skill = current_skill()
    bucket_key = f"{sid}::{skill}"
    now = time.time()

    # Open r+ to read-modify-write under exclusive lock.
    with STATE_FILE.open("r+", encoding="utf-8") as fh:
        _lock_file(fh)
        try:
            state = load_state(fh)
            cfg = get_config(state, skill)
            capacity = float(cfg.get("capacity", 60))
            refill = float(cfg.get("refill_per_sec", 1.0))

            buckets = state.setdefault("_buckets", {})
            b = buckets.get(bucket_key)
            if b is None:
                tokens = capacity
                last = now
            else:
                last = float(b.get("last", now))
                tokens = float(b.get("tokens", capacity))
                # Refill since last touch, capped at capacity.
                tokens = min(capacity, tokens + max(0.0, now - last) * refill)

            advisory = False
            if tokens >= 1.0:
                tokens -= 1.0
            else:
                advisory = True
                # Do not go negative; record the empty state.
                tokens = 0.0

            buckets[bucket_key] = {
                "tokens": round(tokens, 4),
                "last": now,
                "capacity": capacity,
                "refill_per_sec": refill,
            }
            write_state(fh, state)
        finally:
            _unlock_file(fh)

    if advisory:
        msg = (
            "=== rate-limiter (advisory) ===\n"
            f"Bucket empty for {skill}. Recent rate exceeds "
            f"{int(cfg.get('capacity', 60))}/min — possible runaway loop. "
            "Pausing... is your call. Tool will proceed.\n"
        )
        sys.stderr.write(msg)
        sys.stderr.flush()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail-open; never block a tool call
        sys.stderr.write(f"=== rate-limiter (advisory) === error: {exc}\n")
        sys.exit(0)
