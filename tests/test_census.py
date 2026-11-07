"""Regression tests for graph sources, homotopy certificates and checkpoints."""

from __future__ import annotations

import csv
import signal
import sys
import time
import tempfile
import unittest
from itertools import islice
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import networkx as nx

import census
from census import (
    COLUMNS, batch_size, classify, comparison, read_partial, run_order,
    stage_orders,
)
from graph_sources import EXPECTED_COUNTS, graph_from_string, graphs6

LIMITS = {
    "max_k_vertices": 128,
    "max_k_edges": 5000,
    "max_ht_vertices": 64,
    "max_ht_simplices": 25000,
    "flush_every": 10,
}


class CensusTests(unittest.TestCase):
    def test_stage_and_batch_rules(self):
        self.assertEqual(stage_orders("through6"), [1, 2, 3, 4, 5, 6])
        self.assertEqual(stage_orders("9"), [9])
        self.assertEqual(batch_size(7), 10000)
        self.assertEqual(batch_size(9), 10000)
        self.assertEqual(batch_size(10), 100000)

    def test_atlas_counts_and_graph6(self):
        for n in range(1, 6):
            encoded = list(graphs6(n))
            self.assertEqual(len(encoded), EXPECTED_COUNTS[n])
            self.assertTrue(all(
                nx.is_connected(graph_from_string(s)) for s in encoded
            ))

    def test_pyg6data_same_mckay_source_order(self):
        from pyg6data.lists import graph_generator

        for n in (6, 7, 8, 9, 10):
            raw = list(islice(graphs6(n), 8))
            official = [
                nx.to_graph6_bytes(g, header=False).decode().strip()
                for g in islice(graph_generator(n, connected=True), 8)
            ]
            self.assertEqual(raw, official)

    def test_helly_exact_consistency(self):
        examples = [
            nx.complete_graph(4), nx.path_graph(6), nx.cycle_graph(4)
        ]
        for g in examples:
            encoded = nx.to_graph6_bytes(
                g, header=False
            ).decode().strip()
            result = classify(encoded, len(g), 0, LIMITS)
            self.assertEqual(result["helly_kg"], "TRUE")
            self.assertEqual(result["comparison"], "EQUIVALENT")
            self.assertEqual(result["status_g"], "EXACT")
            self.assertEqual(result["status_kg"], "EXACT")

    def test_helly_shortcut_reuses_exact_type_without_classifying_k(self):
        """Prisner transfer is used only when G itself is Helly."""
        k4 = nx.complete_graph(4)
        encoded = nx.to_graph6_bytes(k4, header=False).decode().strip()
        with mock.patch.object(census, "homotopy", wraps=census.homotopy) as ht:
            row = classify(encoded, 4, 0, LIMITS)
        self.assertEqual(ht.call_count, 1)
        self.assertEqual(row["status_kg"], "EXACT")
        self.assertEqual(row["htype_g"], row["htype_kg"])
        self.assertEqual(row["helly_kg"], "TRUE")
        self.assertIn("Prisner", row["reason_kg"])

    def test_nonhelly_g_does_not_use_helly_shortcut(self):
        """K(G) Helly is not enough: that implication is the conjecture."""
        g = nx.from_graph6_bytes(b"EElw")
        encoded = nx.to_graph6_bytes(g, header=False).decode().strip()
        with mock.patch.object(census, "homotopy", wraps=census.homotopy) as ht:
            row = classify(encoded, 6, 55, LIMITS)
        self.assertEqual(row["helly_g"], "FALSE")
        self.assertEqual(row["helly_kg"], "TRUE")
        self.assertEqual(ht.call_count, 2)
        self.assertNotIn("Prisner", row["reason_kg"])

    def test_optional_homotopy_timeout_records_inconclusive(self):
        """Timeouts must never be reported as contractibility or a wedge."""
        graph = nx.cycle_graph(5)
        limits = {**LIMITS, "max_homotopy_seconds": 0.01}

        def too_slow(*_args, **_kwargs):
            time.sleep(0.2)
            raise AssertionError("The alarm failed to interrupt the classifier")

        with mock.patch(
            "pycombtop.homotopy_type.homotopy_type_with_verdict",
            side_effect=too_slow,
        ):
            verdict = census.homotopy(graph, "Dhc", "G", limits)
        self.assertEqual(verdict["status"], "LIMITED")
        self.assertEqual(verdict["htype"], "UNKNOWN")
        self.assertEqual(verdict["betti"], "UNKNOWN")
        self.assertIn("exceeded", verdict["reason"])

    def test_homotopy_alarm_handler_is_restored_after_exception(self):
        original = signal.getsignal(signal.SIGALRM)
        with self.assertRaisesRegex(RuntimeError, "test error"):
            with census.homotopy_time_limit(1):
                raise RuntimeError("test error")
        self.assertEqual(original, signal.getsignal(signal.SIGALRM))

    def test_octahedral_difference_not_counterexample(self):
        g = nx.octahedral_graph()
        encoded = nx.to_graph6_bytes(g, header=False).decode().strip()
        result = classify(encoded, 6, 0, LIMITS)
        self.assertEqual(result["comparison"], "DISTINCT")
        self.assertEqual(result["helly_kg"], "FALSE")

    def test_inexact_same_betti_is_not_certified_equivalence(self):
        inexact = {"betti": "1:1", "status": "BETTI_ONLY"}
        exact = {"betti": "1:1", "status": "EXACT"}
        self.assertEqual(comparison(inexact, exact), "UNRESOLVED")
        self.assertEqual(comparison(exact, exact), "EQUIVALENT")
        self.assertEqual(
            comparison(inexact, {"betti": "2:1", "status": "EXACT"}),
            "DISTINCT",
        )
        self.assertEqual(
            comparison(
                {"betti": "UNKNOWN", "status": "LIMITED"}, exact
            ), "UNRESOLVED"
        )

    def test_partial_checkpoint_strict_index_and_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.partial.tsv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, delimiter="\t",
                    fieldnames=COLUMNS, lineterminator="\n"
                )
                writer.writeheader()
                writer.writerow({
                    k: ("0" if k == "index" else "A?" if k == "graph6" else "")
                    for k in COLUMNS
                })
            self.assertEqual(read_partial(path, 0), ["A?"])
            with self.assertRaises(RuntimeError):
                read_partial(path, 1)

    def test_torn_checkpoint_truncates_only_last_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.tsv"
            path.write_bytes(
                ("\t".join(COLUMNS) + "\n").encode("ascii")
                + ("1\t0\tA?\t" + "\t".join([""] * (len(COLUMNS) - 3))
                   + "\n").encode("ascii")
                + b"1\t1\tBROKEN"
            )
            self.assertEqual(read_partial(path, 0), ["A?"])
            self.assertTrue(path.read_bytes().endswith(b"\n"))

    def test_counterexample_stops_with_a_durable_witness(self):
        n = 2
        g6 = nx.to_graph6_bytes(
            nx.path_graph(n), header=False
        ).decode().strip()
        fake = {
            "order": n, "index": 0, "graph6": g6,
            "helly_g": "FALSE", "helly_kg": "TRUE", "k_order": 2,
            "status_g": "EXACT", "htype_g": "1:1", "betti_g": "1:1",
            "reason_g": "test",
            "status_kg": "EXACT", "htype_kg": "0", "betti_kg": "0",
            "reason_kg": "test",
            "comparison": "DISTINCT",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(census, "graphs6", return_value=iter([g6])),
                mock.patch.dict(census.EXPECTED_COUNTS, {n: 1}),
                mock.patch.object(census, "classify", return_value=fake),
                mock.patch.object(
                    census, "witness_if_confirmed",
                    return_value={"verified": True},
                ),
            ):
                with self.assertRaises(SystemExit) as stopped:
                    run_order(n, Path(tmp), LIMITS)
                self.assertEqual(stopped.exception.code, 42)
            witness = Path(tmp) / "STOP_COUNTEREXAMPLE.json"
            self.assertTrue(witness.is_file())
            self.assertIn('"verified": true', witness.read_text().lower())


if __name__ == "__main__":
    unittest.main()
