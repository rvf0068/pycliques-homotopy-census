"""Order-9 Morse follow-up must never reinterpret historical rows silently."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from audits.resolve_order9_timeouts import (
    DEST,
    EXPECTED,
    ROOT,
    encode,
    historical_rows,
    latex,
    verified_morse_revision,
)


class Order9MorseFollowupTests(unittest.TestCase):
    def test_type_encoding_and_display(self):
        self.assertEqual(encode({}), "0")
        self.assertEqual(encode({3: 2, 2: 1}), "2:1;3:2")
        self.assertEqual(latex("0"), "Contractible")
        self.assertEqual(
            latex("2:1;3:2"), r"\(S^{2}\vee \bigvee_{2}S^{3}\)"
        )

    def test_historical_timeout_rows_have_expected_original_graph6(self):
        summary, rows = historical_rows()
        self.assertEqual(summary["orders"][0]["counts"]["graphs"], 261080)
        self.assertEqual(set(rows), set(EXPECTED))
        for index, row in rows.items():
            self.assertEqual(row["graph6"], EXPECTED[index])
            self.assertEqual(row["status_g"], "EXACT")
            self.assertEqual(row["status_kg"], "LIMITED")
            self.assertEqual(row["htype_kg"], "UNKNOWN")
            self.assertEqual(row["comparison"], "UNRESOLVED")

    def test_followup_results_are_outside_original_runs_directory(self):
        self.assertEqual(DEST, ROOT / "followups" / "order9_morse")
        self.assertFalse(DEST.is_relative_to(ROOT / "runs"))

    def test_direct_audit_requires_isolated_upstream(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError, "run_order9_morse_followup.sh"
            ):
                verified_morse_revision("0" * 40)


if __name__ == "__main__":
    unittest.main()
