"""Independent Phase-2 comparison proofs and fail-closed data checks."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "order10_phase2", ROOT / "audits" / "order10_phase2.py"
)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class Phase2Tests(unittest.TestCase):
    def test_euler_and_homology_of_small_flag_complexes(self):
        for n in (4, 5, 7):
            graph = nx.cycle_graph(n)
            self.assertEqual(audit.reduced_euler(graph), -1)
            self.assertEqual(audit.homology_degree(graph, 1)[-1], 1)
        self.assertEqual(audit.reduced_euler(nx.complete_graph(5)), 0)
        self.assertEqual(audit.homology_degree(nx.complete_graph(5), 2)[-1], 0)
        self.assertEqual(audit.reduced_euler(nx.octahedral_graph()), 1)
        self.assertEqual(audit.homology_degree(nx.octahedral_graph(), 2)[-1], 1)

    def test_graph6_clique_graph_conventions(self):
        graph = nx.cycle_graph(5)
        kgraph = audit.reconstruct_k(graph)
        self.assertTrue(nx.is_isomorphic(graph, kgraph))
        graph = nx.complete_graph(5)
        self.assertEqual(len(audit.reconstruct_k(graph)), 1)
        graph = nx.path_graph(4)
        self.assertEqual(len(audit.reconstruct_k(graph)), 3)

    def test_certificate_homology_and_zero_column(self):
        graph = nx.cycle_graph(4)
        self.assertEqual(audit.homology_degree(graph, 1), (4, 3, 0, 1))
        self.assertEqual(audit.gf2_rank([0, 0, 0]), 0)
        self.assertEqual(audit.gf2_rank([1, 2, 3]), 2)

    def test_original_provenance_is_pinned(self):
        data = b"test"
        self.assertEqual(
            audit.git_blob(data),
            "30d74d258442c7c65512eafab474568dd706c430",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for relative in audit.SOURCES:
                target = path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"not the validated census")
            with self.assertRaisesRegex(RuntimeError, "Source blob mismatch"):
                audit.load_inputs(path)

    def test_full_committed_input_replay(self):
        cases, reps, journal = audit.load_inputs(ROOT)
        result = audit.audit(cases, reps, journal)
        summary = json.loads(result["summary.json"])
        self.assertEqual(summary["final_distinct"], 165)
        self.assertEqual(summary["final_equivalent"], 11)
        self.assertEqual(summary["final_unresolved"], 0)
        self.assertEqual(summary["phase2_euler_distinct"], 68)
        self.assertEqual(summary["phase2_homology_distinct"], 12)
        self.assertEqual(summary["phase2_euler_inconclusive_representatives"],
                         sorted(audit.HOMOLOGY_DEGREES))
        self.assertEqual(len(result["results.tsv"].splitlines()), 81)
        self.assertEqual(len(result["homology_witnesses.tsv"].splitlines()), 13)
        dest = ROOT / "followups/order10_phase2"
        if all((dest / name).exists() for name in result):
            for name, data in result.items():
                self.assertEqual((dest / name).read_bytes(), data)

    def test_missing_or_modified_benchmark_row_rejected(self):
        cases, reps, journal = audit.load_inputs(ROOT)
        altered = copy.deepcopy(journal)
        altered[0]["source_graph6"] = "not a source graph"
        with self.assertRaisesRegex(RuntimeError, "core identity mismatch"):
            audit.audit(cases, reps, altered)
        altered = copy.deepcopy(journal)
        altered[0]["members"] = ["0"]
        with self.assertRaisesRegex(RuntimeError, "core identity mismatch"):
            audit.audit(cases, reps, altered)
        with self.assertRaisesRegex(RuntimeError, "Duplicate, missing"):
            audit.audit(cases, reps, journal[:-1])


if __name__ == "__main__":
    unittest.main()
