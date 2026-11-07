"""Regressions for order-10 budgets, resumable pilot and split reports."""

from __future__ import annotations

import csv
import gzip
import hashlib
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import census

from audits.benchmark_order10 import analyze, sample_indices
from reports.order10_progress import progress
from reports.order10_split import (
    build_index,
    render_batch,
)


class Order10PreparationTests(unittest.TestCase):
    def test_even_sample_indices_are_stable_and_spread(self):
        self.assertEqual(sample_indices(5, 21), [0, 4, 8, 12, 16])
        self.assertEqual(sample_indices(1, 21), [0])
        with self.assertRaises(ValueError):
            sample_indices(0, 21)

    def test_whole_graph_budget_preserves_finished_partial_results(self):
        limits = {"max_graph_seconds": 0.02, "max_homotopy_seconds": 0}
        def slow(_g6, _n, _idx, _limits, progress=None):
            progress.update({
                "helly_g": "TRUE", "status_g": "EXACT",
                "htype_g": "0", "betti_g": "0", "reason_g": "known",
            })
            time.sleep(0.15)
            self.fail("Signal did not interrupt blocked classification")
        with mock.patch.object(census, "classify", side_effect=slow):
            row = census.classify_with_graph_budget("Dhc", 5, 4, limits)
        self.assertEqual(row["status_g"], "EXACT")
        self.assertEqual(row["htype_g"], "0")
        self.assertEqual(row["status_kg"], "LIMITED")
        self.assertEqual(row["helly_kg"], "UNKNOWN")
        self.assertEqual(row["comparison"], "UNRESOLVED")

    def test_graceful_pause_journal_and_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "runs" / "order10"
            limits = {"flush_every": 1, "max_graph_seconds": 0}
            def records(_n):
                return iter(("Dhc", "Dhc", "Dhc"))
            def result(g6, n, idx, _limits):
                row = census.graph_timeout_row(g6, n, idx, 0)
                row.update(
                    helly_g="FALSE", helly_kg="FALSE",
                    status_g="EXACT", status_kg="EXACT",
                    htype_g="0", htype_kg="0",
                    betti_g="0", betti_kg="0",
                    comparison="EQUIVALENT",
                )
                return row
            with (
                mock.patch.dict(census.EXPECTED_COUNTS, {10: 3}),
                mock.patch.object(census, "batch_size", return_value=3),
                mock.patch.object(census, "graphs6", side_effect=records),
                mock.patch.object(census, "classify_with_graph_budget",
                                  side_effect=result),
            ):
                complete = census.run_order(
                    10, directory, limits, deadline=time.monotonic() - 1
                )
                self.assertFalse(complete)
                journal = (
                    directory / "order10" / "partial" /
                    "00000000-00000002.partial.tsv"
                )
                self.assertTrue(journal.is_file())
                self.assertEqual(len(journal.read_text().splitlines()), 1)
                self.assertTrue(census.run_order(10, directory, limits))
                self.assertFalse(journal.exists())
                archive = (
                    directory / "order10" / "chunks" /
                    "00000000-00000002.tsv.gz"
                )
                self.assertTrue(archive.exists())
                with gzip.open(archive, "rt") as stream:
                    rows = list(csv.DictReader(stream, delimiter="\t"))
                self.assertEqual(len(rows), 3)

    def test_split_report_is_bounded_and_incremental(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "input.tsv.gz"
            expected = ["Dhc"] * 12
            with gzip.open(archive, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=census.COLUMNS,
                    delimiter="\t", lineterminator="\n"
                )
                writer.writeheader()
                for i, g6 in enumerate(expected):
                    row = census.graph_timeout_row(g6, 10, i, 0)
                    row.update(
                        helly_g="FALSE", helly_kg="TRUE",
                        status_g="EXACT", status_kg="EXACT",
                        htype_g="1:1", htype_kg="1:1",
                        betti_g="1:1", betti_kg="1:1",
                        comparison="EQUIVALENT",
                    )
                    writer.writerow(row)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            meta = render_batch(root, 0, 11, archive, digest, max_bytes=600)
            self.assertGreater(len(meta["parts"]), 1)
            self.assertEqual(meta["counts"]["nonhelly_g"], 12)
            self.assertEqual(meta["counts"]["nonhelly_g_helly_kg"], 12)
            self.assertEqual(meta["archive_sha256"], digest)
            self.assertEqual(
                render_batch(root, 0, 11, archive, digest, max_bytes=600), meta
            )
            index = build_index(root, [meta])
            self.assertIn("**Non-Helly G:** 12.", index.read_text())
            with self.assertRaisesRegex(RuntimeError, "different input"):
                render_batch(root, 0, 11, archive, digest, max_bytes=700)

    def test_progress_counts_only_completed_and_durable_journal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "runs" / "order10" / "order10"
            (base / "partial").mkdir(parents=True)
            (base / "partial" / "00000000-00099999.partial.tsv").write_text(
                "header\nrow1\nrow2\n"
            )
            state = progress(root)
            self.assertEqual(state["completed_graphs"], 0)
            self.assertEqual(state["journal_graphs"], 2)
            self.assertEqual(state["durably_recorded_graphs"], 2)

    def test_pilot_projection_reports_only_measured_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "pilot.tsv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=(
                        "index", "graph6", "seconds", "status_g",
                        "status_kg", "comparison", "helly_g",
                        "helly_kg", "k_order",
                    ),
                    delimiter="\t",
                )
                writer.writeheader()
                for i, sec in enumerate((0.2, 1.0, 2.0)):
                    writer.writerow({
                        "index": i, "graph6": "Dhc", "seconds": sec,
                        "status_g": "EXACT", "status_kg": "EXACT",
                        "comparison": "EQUIVALENT",
                        "helly_g": "TRUE", "helly_kg": "TRUE", "k_order": 4,
                    })
            stats = analyze(source, planned=10, total=100)
            self.assertEqual(stats["completed_samples"], 3)
            self.assertEqual(stats["p90_seconds"], 2)
            self.assertAlmostEqual(stats["mean_seconds"], 3.2 / 3)


if __name__ == "__main__":
    unittest.main()
