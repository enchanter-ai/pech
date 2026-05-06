#!/usr/bin/env python3
"""
rate-shield: OPT-IN BLOCKING token-bucket rate limiter.

Sibling of pech-rate-limiter (advisory). On every PreToolUse, decrements
the active (session, skill) bucket. When the bucket is empty:

  - exits 2 (block)  → policy.enabled is true
  - exits 0 (allow)  → policy disabled, malformed policy (fail-safe), or
                       sibling rate-limiter buckets.json present but
                       unparseable (graceful degrade)

Bucket source preference:
  1. pech-rate-limiter/state/buckets.json  (sibling, if present and
     parseable — uses its existing per-skill overrides for parity).
  2. <this-plugin>/state/buckets.json       (own state, created on first
     run when sibling is absent).

Decrement model:
  - Token bucket per (session, skill) key.
  - capacity / refill_per_sec come from policy.per_skill[skill] when set,
    else policy.default_*.
  - tokens = min(capacity, tokens + dt * refill); if >= 1 → consume,
    exit 0; else → record empty, stderr advisory, exit 2.

Fail-safe contract:
  ANY exception (parse failure, IO error, missing field) → exit 0.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or SCRIPT_DIR.parent)
POLICY_PATH = PLUGIN_ROOT / "state" / "rate-policy.json"

# Sibling rate-limiter's bucket file (preferred when present).
SIBLING_BUCKETS_PATH = PLUGIN_ROOT.parent / "rate-limiter" / "state" / "buckets.json"
# Fallback: own state file, created if sibling absent.
OWN_BUCKETS_PATH = PLUGIN_ROOT / "state" / "buckets.json"

BLOCK_HEADER = "=== rate-shield (BLOCKED) ==="


# ── locking (cross-platform) ───────────────────────────────────────────────


def _lock_file(fh) -> None:
    if sys.platform == "win32":
        import msvcrt
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _unlock_file(fh) -> None:
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


# ── identity helpers ───────────────────────────────────────────────────────


def session_id() -> str:
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    seed = f"{os.getcwd()}:{os.getppid()}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def current_skill() -> str:
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        parts = parent.parts
        for i, p in enumerate(parts):
            if p == "skills" and i + 1 < len(parts):
                return parts[i + 1]
    return "ungated"


# ── policy loading ─────────────────────────────────────────────────────────


def load_policy() -> dict | None:
    if not POLICY_PATH.is_file():
        return None
    try:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_bucket_config(policy: dict, skill: str) -> tuple[float, float]:
    per_skill = policy.get("per_skill") or {}
    if isinstance(per_skill, dict) and skill in per_skill:
        cfg = per_skill[skill] or {}
        return (
            float(cfg.get("capacity", policy.get("default_capacity", 60))),
            float(cfg.get("refill_per_sec", policy.get("default_refill_per_sec", 1.0))),
        )
    return (
        float(policy.get("default_capacity", 60)),
        float(policy.get("default_refill_per_sec", 1.0)),
    )


# ── bucket-state IO ────────────────────────────────────────────────────────


def choose_bucket_path() -> Path:
    """Prefer sibling rate-limiter's buckets.json when present; else own."""
    if SIBLING_BUCKETS_PATH.is_file():
        return SIBLING_BUCKETS_PATH
    OWN_BUCKETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not OWN_BUCKETS_PATH.exists():
        OWN_BUCKETS_PATH.write_text("{}", encoding="utf-8")
    return OWN_BUCKETS_PATH


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


# ── main ───────────────────────────────────────────────────────────────────


def main() -> int:
    policy = load_policy()
    if not policy:
        return 0
    if not bool(policy.get("enabled", False)):
        return 0

    sid = session_id()
    skill = current_skill()
    bucket_key = f"{sid}::{skill}"
    capacity, refill = get_bucket_config(policy, skill)
    now = time.time()

    bucket_path = choose_bucket_path()

    blocked = False
    try:
        with bucket_path.open("r+", encoding="utf-8") as fh:
            _lock_file(fh)
            try:
                state = load_state(fh)
                buckets = state.setdefault("_buckets", {})
                b = buckets.get(bucket_key)
                if b is None:
                    tokens = capacity
                    last = now
                else:
                    last = float(b.get("last", now))
                    tokens = float(b.get("tokens", capacity))
                    tokens = min(capacity, tokens + max(0.0, now - last) * refill)

                if tokens >= 1.0:
                    tokens -= 1.0
                else:
                    blocked = True
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
    except Exception:
        # Fail-safe: graceful degrade.
        return 0

    if blocked:
        print(BLOCK_HEADER, file=sys.stderr)
        print(
            f"Bucket empty for skill={skill} (capacity={int(capacity)}, "
            f"refill={refill}/sec). Tool call blocked to prevent runaway "
            "loop. To unblock: wait for refill, raise the limit in "
            "state/rate-policy.json (per_skill override), or set "
            "enabled:false to disable the shield.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Fail-safe: never block on shield's own bug.
        sys.exit(0)
