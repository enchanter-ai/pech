#!/usr/bin/env python3
"""
observe.py — Pech's PostToolUse hook entry point.

Reads the hook payload from stdin (Claude Code's hook contract), recovers the API
response's token usage from the session transcript, looks up the rate, applies
prompt-cache modifiers, and appends a ledger row.

Why the transcript and not the hook payload directly: PostToolUse's own payload
(`tool_response`) carries the tool's result, not the model's token usage — there is
no per-call usage field on that event. The transcript JSONL is the authoritative
source: each assistant turn is one line with `message.id`, `message.usage`, and a
`content[]` array of blocks that includes the `tool_use` block(s) issued in that
turn. See docs/adr/0001-telemetry-source.md for the full decision record.

Stdlib only — no external deps per brand invariant.
"""

import json
import os
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


PECH_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
LEDGER_DIR = PECH_ROOT / "plugins" / "cost-tracker" / "state"
SESSION_FILE = LEDGER_DIR / "session.json"
RATE_CARD_FILE = PECH_ROOT / "shared" / "rate-card.json"
OBSERVE_LOG = LEDGER_DIR / "observe.log"

# Dedup store: persists which assistant-turn message.ids have already been billed,
# across hook invocations (each PostToolUse fires a fresh process — see
# docs/adr/0001-telemetry-source.md § split policy).
DEDUP_STORE_FILE = LEDGER_DIR / "seen-message-ids.json"
DEDUP_LOCK_FILE = LEDGER_DIR / "seen-message-ids.lock"
DEDUP_STORE_CAP = 2000  # rotate: keep only the most recently seen N message.ids

# Bounded tail scan: how far back into the transcript we'll look for the tool_use
# id. Keeps extract_usage() inside the hook's 2-3s budget on large transcripts.
TRANSCRIPT_TAIL_LINES = 200


def log(msg: str) -> None:
    """Log to file, never stdout (stdout pollutes conversation)."""
    try:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        with open(OBSERVE_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except Exception:
        pass  # fail-open per @shared/vis/conduct/hooks.md


def load_rate_card() -> dict:
    """Load and return rate card. Empty dict if missing or corrupt (caller handles)."""
    try:
        with open(RATE_CARD_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"rate-card load failed: {e}")
        return {}


def parse_attribution() -> dict:
    """Read ENCHANTED_ATTRIBUTION env. Return empty dict (orphan) if missing/invalid."""
    raw = os.environ.get("ENCHANTED_ATTRIBUTION", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception as e:
        log(f"attribution parse failed: {e}")
        return {}


def _read_transcript_tail(transcript_path: str, max_lines: int = TRANSCRIPT_TAIL_LINES) -> list:
    """Read up to the last `max_lines` lines of the transcript JSONL.

    A bounded deque keeps this O(max_lines) in memory and time regardless of how
    long the transcript has grown — required to stay inside the hook's timeout.
    Returns [] on any failure (missing file, permission error, etc.) — never raises.
    """
    try:
        path = Path(transcript_path)
        if not transcript_path or not path.is_file():
            return []
        with open(path, encoding="utf-8") as f:
            return list(deque(f, maxlen=max_lines))
    except Exception as e:
        log(f"transcript read failed: {e}")
        return []


def extract_usage(hook_payload: dict) -> tuple:
    """Recover the issuing turn's token usage from the transcript.

    Reads `transcript_path` and the tool_use id off the hook payload, then scans the
    transcript tail (bounded, from the end — see TRANSCRIPT_TAIL_LINES) for the
    assistant line whose `message.content[]` contains a `tool_use` block with
    `id == tool_use_id`. That line's `message.usage` is the turn's real token usage;
    `message.id` is the turn identifier the dedup layer keys off of.

    Returns (usage: dict, message_id: str | None). On any miss — no transcript_path,
    no tool_use id, unreadable file, or the id isn't found within the bounded
    window — returns ({}, None). This is a valid "uncosted" outcome, not an error:
    the caller writes a zero-usage ledger row and moves on (LOCKED DESIGN point 4).
    """
    transcript_path = hook_payload.get("transcript_path", "")
    tool_use_id = hook_payload.get("tool_use_id", "")
    if not transcript_path or not tool_use_id:
        return {}, None

    lines = _read_transcript_tail(transcript_path)
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message") or {}
        content = message.get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == tool_use_id:
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    usage = {}  # JSON-valid but malformed usage (e.g. a list) — treat as uncosted, never crash compute_cost
                message_id = message.get("id")
                return usage, message_id

    return {}, None


def _acquire_dedup_lock(timeout: float = 0.5, poll: float = 0.02) -> bool:
    """Best-effort mutual exclusion for the read-modify-write on the dedup store.

    Each hook invocation is a fresh process, so concurrent PostToolUse calls for
    tool_use blocks in the same assistant turn can race on the dedup store. A plain
    exclusive-create lockfile closes that window in the common case. Fails open on
    timeout (returns False) — callers proceed without the lock rather than hang past
    the hook's 2-3s budget; a missed lock means, at worst, a rare double-bill, never
    a crash or a hang.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(DEDUP_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(poll)
        except Exception:
            return False
    return False


def _release_dedup_lock() -> None:
    try:
        DEDUP_LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _load_seen_message_ids() -> list:
    try:
        with open(DEDUP_STORE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [i for i in data.get("ids", []) if isinstance(i, str)]
    except Exception:
        return []


def _save_seen_message_ids(ids: list) -> None:
    try:
        DEDUP_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        capped = ids[-DEDUP_STORE_CAP:]  # rotate: drop the oldest once over the cap
        tmp = DEDUP_STORE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ids": capped}, f)
        os.replace(tmp, DEDUP_STORE_FILE)
    except Exception as e:
        log(f"dedup store write failed: {e}")


def claim_message_id(message_id: str) -> bool:
    """Split policy: first-call-gets-full-turn-cost (LOCKED DESIGN point 2).

    Returns True the first time `message_id` is claimed (caller bills the full turn
    usage) and False on every subsequent claim for the same id (caller must zero the
    usage — an earlier PostToolUse in this turn already billed it). A falsy
    message_id (transcript lookup missed) is treated as unclaimable and always
    returns True — there's nothing to dedup against.

    Fails open: if the store can't be locked/read/written, treats the id as unseen
    (bills it) rather than silently dropping cost. A rare double-count is a smaller
    honest-numbers violation than a rare silent undercount.
    """
    if not message_id:
        return True

    locked = _acquire_dedup_lock()
    try:
        seen = _load_seen_message_ids()
        if message_id in seen:
            return False
        seen.append(message_id)
        _save_seen_message_ids(seen)
        return True
    finally:
        if locked:
            _release_dedup_lock()


def compute_cost(usage: dict, rate_card: dict, model: str, is_batch: bool = False) -> dict:
    """Compute cost breakdown for one API call. Returns {input_cost, output_cost, cache_write_cost, cache_read_cost, total_cost}."""
    if not rate_card:
        return {"total_cost_usd": 0.0, "rate_card_stale": True, "error": "no_rate_card"}

    models = rate_card.get("models", {})
    modifiers = rate_card.get("modifiers", {})
    fallback = rate_card.get("fallback_model_rate", {})

    rate = models.get(model)
    stale = False
    if rate is None:
        rate = fallback
        stale = True
        log(f"model {model!r} not in rate card; using fallback")

    input_rate = rate.get("input_rate_per_mtok", 0.0)
    output_rate = rate.get("output_rate_per_mtok", 0.0)
    cache_write_mod = modifiers.get("cache_write_modifier", 1.25)
    cache_read_mod = modifiers.get("cache_read_modifier", 0.10)
    batch_discount = modifiers.get("batch_discount", 1.0) if is_batch else 1.0

    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    cache_write_tokens = int(usage.get("cache_creation_input_tokens", 0))
    cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))

    input_cost = input_tokens * input_rate / 1_000_000
    output_cost = output_tokens * output_rate / 1_000_000
    cache_write_cost = cache_write_tokens * input_rate * cache_write_mod / 1_000_000
    cache_read_cost = cache_read_tokens * input_rate * cache_read_mod / 1_000_000

    total = (input_cost + output_cost + cache_write_cost + cache_read_cost) * batch_discount

    return {
        "input_cost_usd": round(input_cost * batch_discount, 6),
        "output_cost_usd": round(output_cost * batch_discount, 6),
        "cache_write_cost_usd": round(cache_write_cost * batch_discount, 6),
        "cache_read_cost_usd": round(cache_read_cost * batch_discount, 6),
        "total_cost_usd": round(total, 6),
        "is_batch": is_batch,
        "rate_card_stale": stale,
    }


def ledger_path() -> Path:
    now = datetime.now(timezone.utc)
    return LEDGER_DIR / f"ledger-{now.strftime('%Y-%m')}.jsonl"


def atomic_append(path: Path, line: str) -> bool:
    """Append a line to a file. Per @shared/vis/conduct/tool-use.md § Bash hygiene, do it safely."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")
        return True
    except Exception as e:
        log(f"ledger append failed: {e}")
        return False


def update_session_snapshot(row: dict) -> None:
    """Update session.json with running totals. Atomic rename via tmp file."""
    try:
        existing = {}
        if SESSION_FILE.exists():
            with open(SESSION_FILE, encoding="utf-8") as f:
                existing = json.load(f)

        existing.setdefault("session_id", row.get("attribution", {}).get("session_id", "unknown"))
        existing["last_updated"] = row["timestamp"]
        existing["cost_usd"] = round(existing.get("cost_usd", 0.0) + row["cost"]["total_cost_usd"], 6)
        existing["n_calls"] = existing.get("n_calls", 0) + 1
        existing["orphan_count"] = existing.get("orphan_count", 0) + (1 if row["attribution"].get("orphan") else 0)

        tmp = SESSION_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, SESSION_FILE)
    except Exception as e:
        log(f"session snapshot update failed: {e}")


def main() -> int:
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}

    if not payload:
        # No hook event on stdin at all (e.g. a manual/interactive invocation) — nothing to record.
        return 0  # fail-open

    usage, message_id = extract_usage(payload)
    if message_id and not claim_message_id(message_id):
        # This turn's usage was already billed by an earlier tool_use in the same
        # turn (LOCKED DESIGN point 2). Still record the call for call-count, at zero cost.
        usage = {}

    attribution = parse_attribution()
    orphan = not attribution

    model = attribution.get("model", "unknown")
    is_batch = attribution.get("is_batch", False)

    rate_card = load_rate_card()
    cost = compute_cost(usage, rate_card, model, is_batch)

    row = {
        "row_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": {
            "plugin": attribution.get("plugin", ""),
            "sub_plugin": attribution.get("sub_plugin", ""),
            "skill": attribution.get("skill", ""),
            "agent_tier": attribution.get("agent_tier", ""),
            "model": model,
            "session_id": attribution.get("session_id", ""),
            "orphan": orphan,
        },
        "cache_behavior": _cache_behavior(usage),
        "usage": usage,
        "cost": cost,
        "rate_card_effective_from": rate_card.get("effective_from", "unknown"),
    }

    atomic_append(ledger_path(), json.dumps(row, separators=(",", ":")))
    update_session_snapshot(row)
    return 0  # always fail-open


def _cache_behavior(usage: dict) -> str:
    if int(usage.get("cache_creation_input_tokens", 0)) > 0:
        return "write"
    if int(usage.get("cache_read_input_tokens", 0)) > 0:
        return "read"
    return "none"


if __name__ == "__main__":
    sys.exit(main())
