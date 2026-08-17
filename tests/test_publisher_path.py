"""Regression test for the budget-watcher event publisher path resolution.

Guards the defect where check_budget.py / detect_anomaly.py invoked a subprocess
against ``pech_publish.py`` while the file on disk was named ``nook_publish.py``.
``subprocess.run`` does not raise on a missing script (no ``check=True``), so the
mismatch failed completely silently. These tests assert the referenced publisher
exists and actually runs on a representative event payload.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "shared" / "scripts"


class TestPublisherPathResolves(unittest.TestCase):
    def test_publisher_file_exists(self):
        """The publisher the call sites resolve to (sibling ``pech_publish.py``) must exist."""
        self.assertTrue(
            (SCRIPTS / "pech_publish.py").exists(),
            "shared/scripts/pech_publish.py missing — publisher call sites would fail silently",
        )

    def test_call_sites_reference_an_existing_sibling(self):
        """Every ``parent / \"<name>.py\"`` publisher reference must name a file that exists."""
        pattern = re.compile(r'parent\s*/\s*"([\w.]+\.py)"')
        for caller in ("check_budget.py", "detect_anomaly.py"):
            src = (SCRIPTS / caller).read_text(encoding="utf-8")
            names = pattern.findall(src)
            self.assertTrue(names, f"{caller}: expected a sibling publisher reference")
            for name in names:
                with self.subTest(caller=caller, publisher=name):
                    self.assertTrue(
                        (SCRIPTS / name).exists(),
                        f"{caller} references {name} but shared/scripts/{name} does not exist",
                    )

    def test_publisher_runs_on_representative_event(self):
        """Invoking the publisher with a valid event exits 0 (not a missing-script exit 2)."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "pech_publish.py")],
            input='{"event":"pech.rate_card.refreshed","scope":"test","scope_key":"regression"}',
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode, 0,
            f"publisher exited {result.returncode}: {result.stderr.strip()}",
        )


if __name__ == "__main__":
    unittest.main()
