#!/usr/bin/env python3
"""
publish.py — minimal Phase-1 event-bus publisher helper.

Accepts a topic string and a JSON payload dict, writes a single JSONL line to
$XDG_STATE_HOME/pech/<repo_id>/events.jsonl (fallback: pech/state/events.jsonl).

Usage (from Python):
    from publish import publish
    publish("pech.budget.threshold.crossed", {"session_id": ..., ...})

Usage (from shell — pipe JSON via stdin):
    echo '{"topic":"pech.anomaly.detected","payload":{...}}' | python publish.py

Fail-open: logs to stderr on any failure, never raises.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_id() -> str:
    """Derive a stable repo identifier from git HEAD + toplevel, fallback to cwd hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD", "--show-toplevel"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            combined = result.stdout.strip()
            return hashlib.sha1(combined.encode()).hexdigest()[:12]
    except Exception:
        pass
    return hashlib.sha1(os.getcwd().encode()).hexdigest()[:12]


def _events_path() -> Path:
    """Resolve the events.jsonl path: XDG_STATE_HOME/pech/<repo_id>/events.jsonl."""
    xdg = os.environ.get("XDG_STATE_HOME", "")
    if xdg:
        base = Path(xdg) / "pech" / _repo_id()
    else:
        # Fallback: pech/state/events.jsonl relative to this file's plugin root
        pech_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT",
                                        Path(__file__).resolve().parent.parent.parent))
        base = pech_root / "state"
    return base / "events.jsonl"


def publish(topic: str, payload: dict) -> None:
    """Write a single JSONL event line atomically (append + fsync). Fail-open."""
    try:
        entry = {
            "topic": topic,
            "payload": payload,
            "emitted_at": datetime.now(timezone.utc).isoformat(),
        }
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        path = _events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception as exc:
        print(f"[pech:publish] failed to emit {topic!r}: {exc}", file=sys.stderr)


def _main() -> int:
    """CLI entry point: read {topic, payload} JSON from stdin."""
    try:
        data = json.load(sys.stdin)
        topic = data["topic"]
        payload = data.get("payload", {})
    except Exception as exc:
        print(f"[pech:publish] bad stdin JSON: {exc}", file=sys.stderr)
        return 1
    publish(topic, payload)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
