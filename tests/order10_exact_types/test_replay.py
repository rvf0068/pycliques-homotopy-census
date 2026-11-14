"""Recompute the published order-10 types with the follow-up's pinned packages."""

import csv
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ExactTypeReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "audits"))
        try:
            import order10_exact_types
        finally:
            sys.path.pop(0)
        cls.output = order10_exact_types.generate()

    def test_all_published_files_match_byte_for_byte(self):
        directory = ROOT / "followups/order10_exact_types"
        expected = {"results.tsv", "remaining_types.jsonl", "summary.json"}
        self.assertEqual(set(self.output), expected)
        for name in sorted(expected):
            with self.subTest(file=name):
                self.assertEqual(self.output[name], (directory / name).read_bytes())

    def test_representative_transfer_and_separate_source_graph(self):
        rows = list(
            csv.DictReader(
                self.output["results.tsv"].decode().splitlines(), delimiter="\t"
            )
        )
        by_index = {row["index"]: row for row in rows}
        self.assertEqual(len(rows), 177)
        self.assertEqual(len(by_index), 177)
        self.assertEqual(
            Counter(row["proof"] for row in rows),
            {"representative": 80, "phase1_join": 96, "suspension_of_two_squares": 1},
        )
        members = [row for row in rows if row["proof"] == "representative"]
        self.assertEqual(len({r["representative_index"] for r in members}), 60)
        for row in members:
            with self.subTest(index=row["index"]):
                rep = by_index[row["representative_index"]]
                self.assertEqual(rep["representative_index"], rep["index"])
                self.assertEqual(row["htype_kg"], rep["htype_kg"])
        # A nontrivial transfer, and the sole exception on the G side.
        self.assertEqual(by_index["7994400"]["representative_index"], "1561859")
        self.assertEqual(by_index["7994400"]["htype_kg"], "3:14")
        special = by_index["7749135"]
        self.assertEqual(
            (special["htype_g"], special["htype_kg"]), ("1:1;2:2", "1:1;3:2")
        )
        self.assertEqual(special["comparison"], "DISTINCT")

    def test_residual_proofs_and_final_counts(self):
        residual = [
            json.loads(line)
            for line in self.output["remaining_types.jsonl"].splitlines()
        ]
        self.assertEqual(len({row["index"] for row in residual}), 20)
        self.assertEqual(
            Counter(row["method"] for row in residual),
            {"vertex_star": 18, "morse_shore": 1, "morse": 1},
        )
        summary = json.loads(self.output["summary.json"])
        for field in ("connected_graphs", "exact_G", "exact_KG"):
            with self.subTest(field=field):
                self.assertEqual(summary[field], 11_716_571)
        self.assertEqual(summary["equivalent"], 10_959_509)
        self.assertEqual(summary["distinct"], 757_062)
        self.assertEqual(summary["unresolved_types"], 0)
