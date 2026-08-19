"""Regression tests for observe.py's transcript-sourced usage meter (VF-12).

Guards the defect where extract_usage() read hook_payload["tool_response"]["usage"]
— a field PostToolUse never carries — so the ledger silently stayed empty. The fix
sources token usage from the transcript JSONL instead (see
docs/adr/0001-telemetry-source.md). These tests bundle a small synthetic transcript
rather than depending on a real ~/.claude/projects/... file on the machine.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "shared" / "scripts"


def _load_observe_module():
    """Import shared/scripts/observe.py as a standalone module (no package __init__)."""
    spec = importlib.util.spec_from_file_location("observe", SCRIPTS / "observe.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["observe"] = module
    spec.loader.exec_module(module)
    return module


observe = _load_observe_module()


def _write_transcript(path: Path, lines: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for entry in lines:
            f.write(json.dumps(entry) + "\n")


def _assistant_turn(message_id: str, tool_use_ids: list[str], usage: dict) -> dict:
    """Build a synthetic assistant transcript line shaped like a real one:
    message.id, message.usage, message.content[] with tool_use blocks.
    """
    content = [{"type": "text", "text": "..."}]
    for tid in tool_use_ids:
        content.append({"type": "tool_use", "id": tid, "name": "Bash", "input": {}})
    return {
        "type": "assistant",
        "message": {
            "id": message_id,
            "model": "claude-sonnet-5",
            "role": "assistant",
            "content": content,
            "usage": usage,
        },
    }


SAMPLE_USAGE = {
    "input_tokens": 5,
    "output_tokens": 120,
    "cache_creation_input_tokens": 300,
    "cache_read_input_tokens": 1000,
}


class TestExtractUsageFromTranscript(unittest.TestCase):
    """(a) and (c): first PostToolUse of a turn recovers the turn's full, correctly-parsed usage."""

    def setUp(self):
        self.tmp_dir = Path(self._tmp_dir_factory())
        self.transcript_path = self.tmp_dir / "session.jsonl"

    def _tmp_dir_factory(self):
        import tempfile
        return tempfile.mkdtemp(prefix="pech-observe-test-")

    def test_finds_usage_and_message_id_for_matching_tool_use(self):
        _write_transcript(
            self.transcript_path,
            [
                {"type": "user", "message": {"role": "user", "content": "hi"}},
                _assistant_turn("msg_A", ["toolu_1"], SAMPLE_USAGE),
            ],
        )
        payload = {"transcript_path": str(self.transcript_path), "tool_use_id": "toolu_1"}

        usage, message_id = observe.extract_usage(payload)

        self.assertEqual(message_id, "msg_A")
        self.assertEqual(usage["input_tokens"], 5)
        self.assertEqual(usage["output_tokens"], 120)
        self.assertEqual(usage["cache_creation_input_tokens"], 300)
        self.assertEqual(usage["cache_read_input_tokens"], 1000)

    def test_tool_use_id_not_found_in_window_is_uncosted_not_a_crash(self):
        """(d): unknown tool_use id -> ({}, None), no exception."""
        _write_transcript(
            self.transcript_path,
            [_assistant_turn("msg_A", ["toolu_1"], SAMPLE_USAGE)],
        )
        payload = {"transcript_path": str(self.transcript_path), "tool_use_id": "toolu_does_not_exist"}

        usage, message_id = observe.extract_usage(payload)

        self.assertEqual(usage, {})
        self.assertIsNone(message_id)

    def test_missing_transcript_path_is_uncosted_not_a_crash(self):
        payload = {"transcript_path": str(self.tmp_dir / "does-not-exist.jsonl"), "tool_use_id": "toolu_1"}

        usage, message_id = observe.extract_usage(payload)

        self.assertEqual(usage, {})
        self.assertIsNone(message_id)

    def test_scan_is_bounded_to_tail_window(self):
        """A tool_use id that only appears before the tail window is treated as not found."""
        lines = [_assistant_turn("msg_old", ["toolu_old"], SAMPLE_USAGE)]
        # Pad well past TRANSCRIPT_TAIL_LINES with unrelated assistant turns.
        for i in range(observe.TRANSCRIPT_TAIL_LINES + 50):
            lines.append(_assistant_turn(f"msg_pad_{i}", [f"toolu_pad_{i}"], {"input_tokens": 1, "output_tokens": 1}))
        _write_transcript(self.transcript_path, lines)

        payload = {"transcript_path": str(self.transcript_path), "tool_use_id": "toolu_old"}
        usage, message_id = observe.extract_usage(payload)

        self.assertEqual(usage, {})
        self.assertIsNone(message_id)


class TestDedupByMessageId(unittest.TestCase):
    """(a) and (b): first claim of a message_id bills full usage; a second claim of the
    same message_id must not double-bill.
    """

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="pech-observe-dedup-"))
        # Isolate the dedup store from any real plugin state directory.
        observe.LEDGER_DIR = self.tmp_dir
        observe.DEDUP_STORE_FILE = self.tmp_dir / "seen-message-ids.json"
        observe.DEDUP_LOCK_FILE = self.tmp_dir / "seen-message-ids.lock"

    def test_first_claim_returns_true(self):
        self.assertTrue(observe.claim_message_id("msg_turn_1"))

    def test_second_claim_of_same_message_id_returns_false(self):
        self.assertTrue(observe.claim_message_id("msg_turn_1"))
        self.assertFalse(observe.claim_message_id("msg_turn_1"))

    def test_second_claim_persists_across_fresh_process_simulation(self):
        """Each hook invocation is a fresh process; simulate that by reloading the module
        state (the store is file-backed, so a second "process" sees the first claim).
        """
        self.assertTrue(observe.claim_message_id("msg_turn_2"))

        # Re-exec the module fresh, pointed at the same on-disk store, to simulate a
        # brand-new hook process picking up the persisted dedup state.
        fresh = _load_observe_module()
        fresh.LEDGER_DIR = self.tmp_dir
        fresh.DEDUP_STORE_FILE = self.tmp_dir / "seen-message-ids.json"
        fresh.DEDUP_LOCK_FILE = self.tmp_dir / "seen-message-ids.lock"

        self.assertFalse(fresh.claim_message_id("msg_turn_2"))

    def test_different_message_ids_each_get_first_claim(self):
        self.assertTrue(observe.claim_message_id("msg_a"))
        self.assertTrue(observe.claim_message_id("msg_b"))

    def test_falsy_message_id_is_always_claimable(self):
        self.assertTrue(observe.claim_message_id(""))
        self.assertTrue(observe.claim_message_id(None))


class TestMainWritesZeroUsageRowOnDuplicateOrMiss(unittest.TestCase):
    """End-to-end through main(): duplicate message_id -> zero-usage ledger row (no
    double-bill); tool_use id not found -> uncosted ledger row, no crash.
    """

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="pech-observe-main-"))
        observe.PECH_ROOT = self.tmp_dir
        observe.LEDGER_DIR = self.tmp_dir / "state"
        observe.SESSION_FILE = observe.LEDGER_DIR / "session.json"
        observe.RATE_CARD_FILE = self.tmp_dir / "rate-card.json"
        observe.OBSERVE_LOG = observe.LEDGER_DIR / "observe.log"
        observe.DEDUP_STORE_FILE = observe.LEDGER_DIR / "seen-message-ids.json"
        observe.DEDUP_LOCK_FILE = observe.LEDGER_DIR / "seen-message-ids.lock"

        self.transcript_path = self.tmp_dir / "session.jsonl"
        _write_transcript(
            self.transcript_path,
            [_assistant_turn("msg_shared", ["toolu_1", "toolu_2"], SAMPLE_USAGE)],
        )

        # Minimal rate card so compute_cost() doesn't short-circuit on "no_rate_card".
        with open(observe.RATE_CARD_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "effective_from": "2026-01-01",
                    "models": {"unknown": {"input_rate_per_mtok": 3.0, "output_rate_per_mtok": 15.0}},
                    "modifiers": {"cache_write_modifier": 1.25, "cache_read_modifier": 0.10},
                },
                f,
            )

    def _run_hook(self, tool_use_id: str, monkeypatch_stdin, capsys=None) -> dict:
        payload = {"transcript_path": str(self.transcript_path), "tool_use_id": tool_use_id}
        import io
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(payload))
        try:
            observe.main()
        finally:
            sys.stdin = old_stdin

        ledger_file = observe.ledger_path()
        with open(ledger_file, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        return rows[-1]

    def test_first_call_of_turn_gets_full_usage_and_second_gets_zero(self):
        first_row = self._run_hook("toolu_1", None)
        second_row = self._run_hook("toolu_2", None)

        self.assertEqual(first_row["usage"]["input_tokens"], 5)
        self.assertGreater(first_row["cost"]["total_cost_usd"], 0)

        self.assertEqual(second_row["usage"], {})
        self.assertEqual(second_row["cost"]["total_cost_usd"], 0.0)

    def test_unmatched_tool_use_id_yields_uncosted_row_without_crash(self):
        row = self._run_hook("toolu_never_existed", None)

        self.assertEqual(row["usage"], {})
        self.assertEqual(row["cost"]["total_cost_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
