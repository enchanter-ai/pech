#!/usr/bin/env python3
"""
session_init.py — SessionStart hook for cost-tracker.

Initializes session.json with a fresh session_id + zero counters. Rotates the previous
session's snapshot to session-prior.json so it's queryable for the first few calls of the
new session (useful when L3 needs a prior prior before learnings.json kicks in).
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
STATE_DIR = PECH_ROOT / "plugins" / "cost-tracker" / "state"
SESSION_FILE = STATE_DIR / "session.json"
PRIOR_SESSION_FILE = STATE_DIR / "session-prior.json"


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Rotate prior session snapshot if present
    if SESSION_FILE.exists():
        try:
            os.replace(SESSION_FILE, PRIOR_SESSION_FILE)
        except Exception:
            pass

    # Read session_id from ENCHANTED_ATTRIBUTION if available, else generate a fresh UUID
    session_id = str(uuid.uuid4())
    attr = os.environ.get("ENCHANTED_ATTRIBUTION", "")
    if attr:
        try:
            parsed = json.loads(attr)
            session_id = parsed.get("session_id") or session_id
        except Exception:
            pass

    initial = {
        "session_id": session_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "cost_usd": 0.0,
        "n_calls": 0,
        "orphan_count": 0,
    }
    tmp = SESSION_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(initial, f, indent=2)
    os.replace(tmp, SESSION_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
