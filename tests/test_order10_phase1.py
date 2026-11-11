"""Regression tests for order-10 structural follow-up and core grouping."""
from __future__ import annotations

import importlib.util
import hashlib
import tempfile
from pathlib import Path

import networkx as nx
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "order10_phase1", ROOT / "audits" / "order10_phase1.py"
)
assert SPEC and SPEC.loader
phase = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase)


class Order10Phase1Tests(unittest.TestCase):

    def test_domination_moves_replay_and_preserve_original(self):
        graph = nx.path_graph(6)
        original_edges = set(graph.edges)
        core, moves = phase.pare_with_witnesses(graph)
        assert set(graph.edges) == original_edges
        assert len(core) == 1
        assert len(moves) == 5
        assert set(phase.replay_folds(graph, moves)) == set(core)
        with self.assertRaisesRegex(ValueError, "Invalid dominated"):
            phase.replay_folds(nx.cycle_graph(4), [[0, 1]])
    
    
    def test_complement_factors_and_join_theorem(self):
        core = nx.complement(nx.disjoint_union_all([nx.path_graph(2)] * 4))
        factors = phase.complement_factors(core)
        assert sorted(f["kind"] for f in factors) == ["K2"] * 4
        assert phase.recognize_exact_join(factors)["betti"] == "3:1"
    
        core = nx.complement(nx.disjoint_union(nx.cycle_graph(6), nx.cycle_graph(6)))
        assert phase.recognize_exact_join(phase.complement_factors(core))["betti"] == "3:4"
    
        core = nx.complement(nx.disjoint_union(nx.cycle_graph(10), nx.cycle_graph(10)))
        assert phase.recognize_exact_join(phase.complement_factors(core))["betti"] == "5:1"
    
    
    def test_cone_factor_precedes_unknown(self):
        assert phase.recognize_exact_join([
            {"kind": "OTHER"}, {"kind": "K1"},
        ])["betti"] == "0"
        assert phase.recognize_exact_join([{"kind": "OTHER"}]) is None
    
    
    def test_real_graph6_sphere_and_helly_exception(self):
        g = nx.from_graph6_bytes(b"I?BFvz{}w")
        k = phase.reconstruct_clique_graph(g)
        core, moves = phase.pare_with_witnesses(k)
        assert phase.graph6(phase.replay_folds(k, moves)) == phase.graph6(core)
        assert len(k) == 19 and len(core) == 8
        assert phase.recognize_exact_join(phase.complement_factors(core))["betti"] == "3:1"
    
        g = nx.from_graph6_bytes(b"I?bvbrw|w")
        for graph in (g, phase.reconstruct_clique_graph(g)):
            core, moves = phase.pare_with_witnesses(graph)
            assert len(core) == 4
            assert nx.is_isomorphic(core, nx.cycle_graph(4))
            assert phase.graph6(phase.replay_folds(graph, moves)) == phase.graph6(core)
    
    
    def test_isomorphic_cores_are_grouped_only_after_exact_match(self):
        a = nx.disjoint_union(nx.cycle_graph(6), nx.cycle_graph(4))
        b = nx.relabel_nodes(a, {i: 10-i for i in a}, copy=True)
        c = nx.disjoint_union(nx.cycle_graph(5), nx.cycle_graph(5))
        cases = [
            {"index": 1, "graph6": "first", "representative_index": None},
            {"index": 2, "graph6": "second", "representative_index": None},
            {"index": 3, "graph6": "third", "representative_index": None},
        ]
        cores = {1: nx.complement(a), 2: nx.complement(b), 3: nx.complement(c)}
        groups = phase.group_unclassified(cases, cores)
        assert len(groups) == 2
        assert groups[0]["members"] == [1, 2]
        assert groups[1]["members"] == [3]
        assert cases[1]["representative_index"] == 1
        mapping = dict(groups[0]["isomorphism_maps"]["2"])
        assert set(mapping) == set(cores[2])
        assert all(
            cores[2].has_edge(u, v) == cores[1].has_edge(mapping[u], mapping[v])
            for u in cores[2] for v in cores[2] if u != v
        )
    
    
    def test_baseline_git_blob_identity_is_required(self):
        expected = b"test"
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "test.bin"
            p.write_bytes(expected)
            self.assertEqual(
                phase.git_blob_sha1(p),
                hashlib.sha1(b"blob 4\0test").hexdigest(),
            )
            base = Path(directory) / "runs" / "order10"
            base.mkdir(parents=True)
            (base / "summary.json").write_text("{}")
            (base / "unresolved_order10.tsv.gz").write_bytes(b"not the census")
            with self.assertRaisesRegex(RuntimeError, "Source differs from validated"):
                phase.original_unresolved(Path(directory))

    def test_fails_closed_if_exact_split_changes(self):
        cases = [{"comparison": name} for name, n in [
            ("EQUIVALENT", 10), ("DISTINCT", 86), ("UNCLASSIFIED", 80)
        ] for _ in range(n)]
        with self.assertRaisesRegex(RuntimeError, "Unexpected phase-1 totals"):
            phase.artifacts(cases, [{}] * 60, {})

    def test_census_phase1_output_matches_committed_data_when_available(self):
        summary = ROOT / "runs" / "order10" / "summary.json"
        unresolved = ROOT / "runs" / "order10" / "unresolved_order10.tsv.gz"
        if not (summary.exists() and unresolved.exists()):
            self.skipTest("Original order-10 census files not present")
        rows, provenance = phase.original_unresolved(ROOT)
        cases, groups = phase.analyze_rows(rows)
        data = phase.artifacts(cases, groups, provenance)
        assert len(cases) == 176
        assert len(groups) == 60
        assert sum(x["comparison"] == "EQUIVALENT" for x in cases) == 11
        assert sum(x["comparison"] == "DISTINCT" for x in cases) == 85
        assert sum(x["comparison"] == "UNCLASSIFIED" for x in cases) == 80
        assert [x["index"] for x in cases if x["original_helly_kg"] == "TRUE"] == [
            6074303, 7993989, 7994353, 11529569,
        ]
        dest = ROOT / "followups" / "order10_phase1"
        for name in ("results.tsv", "representatives.tsv"):
            if (dest / name).exists():
                assert (dest / name).read_bytes() == data[name]
    