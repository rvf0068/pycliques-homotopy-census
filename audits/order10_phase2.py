#!/usr/bin/env python3
"""Independent, fail-closed audit of the 80 Phase-2 order-10 comparisons.

Rebuild K(G) from each original ten-vertex graph6, without trusting a stored
pared core or the benchmark's discrete Morse homotopy claims. Compute the
reduced Euler characteristic by an independence-polynomial recurrence and,
when that agrees with G, compute exact simplicial homology over GF(2).
Historical census and Phase-1 files are only read, never modified.

Run: python audits/order10_phase2.py [--check]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from functools import cache
from itertools import combinations
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "followups/order10_phase1/results.tsv": "3e83181c6e47e51e62d5af4f82cfeb1e5feacbf8",
    "followups/order10_phase1/representatives.tsv": "0da9d8cf5ebd01bf2e7144faafcb6aac919f22e2",
    "followups/order10_phase2_benchmark.jsonl": "b84b264dfcd19485ebf592036d7423d92524211e",
    "followups/order10_phase2_benchmark.jsonl.meta.json": "ab5356698ca6c069da86b57bcc858ffb3e9b66d6",
}
# Search dimensions, NOT assumed Betti values. Every rank is recalculated.
HOMOLOGY_DEGREES = {
    7923665: 3, 11537978: 3, 11650233: 3, 11656524: 3,
    11661308: 2, 11661348: 3, 11661524: 3, 11715924: 3,
    11716425: 2,
}
EXPECTED_STATUS = {"EXACT": 38, "TIMEOUT": 17, "LIMITED": 5}
RESULT_FIELDS = [
    "index", "graph6", "representative_index", "benchmark_status",
    "method", "chi_g", "chi_kg", "degree", "beta_g", "beta_kg", "comparison",
]
WITNESS_FIELDS = [
    "index", "representative_index", "degree", "g_faces", "g_rank_d",
    "g_rank_next", "g_beta", "kg_faces", "kg_rank_d", "kg_rank_next", "kg_beta",
]


def git_blob(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def load_inputs(root: Path = ROOT):
    for path, expected in SOURCES.items():
        if git_blob((root / path).read_bytes()) != expected:
            raise RuntimeError(f"Source blob mismatch: {path}")

    def read_tsv(path):
        with (root / path).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream, delimiter="\t"))

    cases = read_tsv("followups/order10_phase1/results.tsv")
    reps = read_tsv("followups/order10_phase1/representatives.tsv")
    journal = [
        json.loads(s)
        for s in (root / "followups/order10_phase2_benchmark.jsonl")
        .read_text(encoding="utf-8").splitlines()
    ]
    metadata = json.loads(
        (root / "followups/order10_phase2_benchmark.jsonl.meta.json")
        .read_text(encoding="utf-8")
    )
    digest = hashlib.sha256(
        (root / "followups/order10_phase1/representatives.tsv").read_bytes()
    ).hexdigest()
    if (
        metadata.get("sha256_representatives") != digest
        or metadata.get("git_commit") != "edba0792ec904035b03487831f2fc280ba720799"
        or metadata.get("dong_seed") != 0
        or metadata.get("max_simplices") != 25000
        or metadata.get("max_vertices") != 64
        or metadata.get("timeout_seconds") != 120
    ):
        raise RuntimeError("Benchmark provenance mismatch")
    return cases, reps, journal


def reconstruct_k(graph: nx.Graph) -> nx.Graph:
    """Maximal completes as vertices, adjacency by nonempty intersection."""
    cliques = [frozenset(q) for q in nx.find_cliques(graph)]
    k = nx.Graph()
    k.add_nodes_from(range(len(cliques)))
    k.add_edges_from(
        (i, j) for i, j in combinations(range(len(cliques)), 2)
        if cliques[i] & cliques[j]
    )
    return k


def reduced_euler(graph: nx.Graph) -> int:
    """-I_complement(-1), computed by exact deletion/closed-neighborhood."""
    complement = nx.complement(nx.convert_node_labels_to_integers(graph))
    neighbors = [
        sum(1 << v for v in complement.neighbors(i))
        for i in range(len(complement))
    ]

    @cache
    def independence(mask: int) -> int:
        if not mask:
            return 1
        bit = mask & -mask
        v = bit.bit_length() - 1
        return independence(mask ^ bit) - independence(mask & ~(bit | neighbors[v]))

    return -independence((1 << len(complement)) - 1)


def exact_wedge(signature: str) -> dict[int, int]:
    if signature == "0":
        return {}
    result = {}
    for token in signature.split(";"):
        d, count = map(int, token.split(":"))
        if d < 0 or count < 1 or d in result:
            raise ValueError("Invalid exact wedge signature")
        result[d] = count
    return result


def wedge_euler(spheres: dict[int, int]) -> int:
    return sum((-1) ** d * number for d, number in spheres.items())


def gf2_rank(columns) -> int:
    """Exact binary Gaussian elimination, storing one column per pivot."""
    pivots = {}
    for column in columns:
        while column:
            bit = column & -column
            if bit not in pivots:
                pivots[bit] = column
                break
            column ^= pivots[bit]
    return len(pivots)


def homology_degree(graph: nx.Graph, degree: int) -> tuple[int, int, int, int]:
    """(dim C_d, rank boundary_d, rank boundary_{d+1}, beta_d), mod 2."""
    graph = nx.convert_node_labels_to_integers(graph)
    faces = defaultdict(list)
    for clique in nx.enumerate_all_cliques(graph):
        d = len(clique) - 1
        if d > degree + 1:
            break  # NetworkX enumerates by increasing cardinality.
        faces[d].append(sum(1 << int(v) for v in clique))

    def boundary_rank(d: int) -> int:
        row = {simplex: i for i, simplex in enumerate(faces[d - 1])}

        def columns():
            for simplex in faces[d]:
                boundary, bits = 0, simplex
                while bits:
                    bit = bits & -bits
                    bits ^= bit
                    boundary ^= 1 << row[simplex ^ bit]
                yield boundary

        return gf2_rank(columns())

    f = len(faces[degree])
    low, high = boundary_rank(degree), boundary_rank(degree + 1)
    return f, low, high, f - low - high


def tsv(rows: list[dict], columns: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t",
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def audit(cases: list[dict], reps: list[dict], journal: list[dict]) -> dict[str, bytes]:
    if len(cases) != 176 or Counter(row["comparison"] for row in cases) != {
        "DISTINCT": 85, "EQUIVALENT": 11, "UNCLASSIFIED": 80,
    }:
        raise RuntimeError("Unexpected Phase-1 comparison counts")
    by_index = {int(row["index"]): row for row in cases}
    by_rep = {int(row["representative_index"]): row for row in reps}
    by_benchmark = {row["representative_index"]: row for row in journal}
    if (len(by_index) != 176 or len(by_rep) != 60 or len(reps) != 60
            or len(by_benchmark) != 60 or len(journal) != 60
            or set(by_rep) != set(by_benchmark)
            or Counter(row["status"] for row in journal) != EXPECTED_STATUS):
        raise RuntimeError("Duplicate, missing, or unexpected input records")

    members = []
    for i, rep in by_rep.items():
        record = by_benchmark[i]
        ids = rep["members"].split(";")
        if (int(ids[0]) != i or len(ids) != len(set(ids))
                or record.get("source_graph6") != rep["graph6"]
                or record.get("core_graph6") != rep["core_graph6"]
                or record.get("members") != ids):
            raise RuntimeError(f"Benchmark core identity mismatch: {i}")
        if record["status"] == "EXACT":
            spheres = record.get("certified_spheres")
            if (
                record.get("is_exact") is not True or record.get("is_limited") is not False
                or not isinstance(spheres, dict)
                or any(not d.isdecimal() or type(n) is not int or n < 1
                       for d, n in spheres.items())
            ):
                raise RuntimeError(f"Malformed exact result: {i}")
        elif record.get("certified_spheres") is not None:
            raise RuntimeError(f"Inexact record claiming a sphere certificate: {i}")
        for member in ids:
            x = int(member)
            if (x not in by_index or by_index[x]["comparison"] != "UNCLASSIFIED"
                    or by_index[x]["representative_index"] != str(i)):
                raise RuntimeError(f"Phase-1 group mismatch: {x}")
            members.append(x)
    if (len(members) != 80 or len(set(members)) != 80
            or set(members) != {
                i for i, row in by_index.items() if row["comparison"] == "UNCLASSIFIED"
            }):
        raise RuntimeError("Phase-2 coverage of source indices is incomplete")

    core_eulers = {}
    results = []
    homology_witnesses = []
    equal_reps = set()
    methods = Counter()
    for index in sorted(members):
        row = by_index[index]
        representative_index = int(row["representative_index"])
        rep = by_rep[representative_index]
        record = by_benchmark[representative_index]
        graph = nx.from_graph6_bytes(row["graph6"].encode("ascii"))
        if len(graph) != 10:
            raise RuntimeError(f"Unexpected original graph order: {index}")
        kgraph = reconstruct_k(graph)
        chi_g, chi_k = reduced_euler(graph), reduced_euler(kgraph)
        original_wedge = exact_wedge(row["htype_g"])
        if chi_g != wedge_euler(original_wedge):
            raise RuntimeError(f"Original type contradicts Euler characteristic: {index}")
        if representative_index not in core_eulers:
            core = nx.from_graph6_bytes(rep["core_graph6"].encode("ascii"))
            if (len(core) != int(rep["core_order"])
                    or len(core.edges) != int(rep["core_edges"])):
                raise RuntimeError(f"Pared core metadata invalid: {representative_index}")
            core_eulers[representative_index] = reduced_euler(core)
        if chi_k != core_eulers[representative_index]:
            raise RuntimeError(f"Reconstructed K(G) and stored core disagree: {index}")
        if record["status"] == "EXACT":
            spheres = {int(d): n for d, n in record["certified_spheres"].items()}
            if chi_k != wedge_euler(spheres):
                raise RuntimeError(f"Benchmark sphere vector contradicts Euler: {index}")

        result = {
            "index": index, "graph6": row["graph6"],
            "representative_index": representative_index,
            "benchmark_status": record["status"], "chi_g": chi_g,
            "chi_kg": chi_k, "comparison": "DISTINCT",
            "degree": "", "beta_g": "", "beta_kg": "",
        }
        if chi_g != chi_k:
            result["method"] = "EULER"
        else:
            equal_reps.add(representative_index)
            degree = HOMOLOGY_DEGREES.get(representative_index)
            if degree is None:
                raise RuntimeError(f"No distinguishing homology dimension: {index}")
            gf, gr, gn, gb = homology_degree(graph, degree)
            kf, kr, kn, kb = homology_degree(kgraph, degree)
            if gb != original_wedge.get(degree, 0) or gb == kb:
                raise RuntimeError(f"GF(2) ranks do not certify DISTINCT: {index}")
            result.update(method="MOD2_HOMOLOGY", degree=degree, beta_g=gb, beta_kg=kb)
            homology_witnesses.append({
                "index": index, "representative_index": representative_index,
                "degree": degree, "g_faces": gf, "g_rank_d": gr,
                "g_rank_next": gn, "g_beta": gb, "kg_faces": kf,
                "kg_rank_d": kr, "kg_rank_next": kn, "kg_beta": kb,
            })
        methods[result["method"]] += 1
        results.append(result)
    if (methods != {"EULER": 68, "MOD2_HOMOLOGY": 12}
            or equal_reps != set(HOMOLOGY_DEGREES)
            or len(results) != 80):
        raise RuntimeError("Unexpected independent proof counts")
    summary = {
        "source_git_blobs": SOURCES,
        "original_order10_unresolved": 176,
        "phase1_equivalent": 11, "phase1_distinct": 85,
        "phase2_original_graphs": 80, "phase2_representatives": 60,
        "benchmark_status": EXPECTED_STATUS,
        "phase2_euler_distinct": methods["EULER"],
        "phase2_homology_distinct": methods["MOD2_HOMOLOGY"],
        "phase2_euler_inconclusive_representatives": sorted(equal_reps),
        "final_equivalent": 11, "final_distinct": 165, "final_unresolved": 0,
        "comparison_scope": (
            "Delta(G) vs Delta(K(G)); full homotopy type of K(G) not always known"
        ),
    }
    return {
        "summary.json": (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode(),
        "results.tsv": tsv(results, RESULT_FIELDS),
        "homology_witnesses.tsv": tsv(homology_witnesses, WITNESS_FIELDS),
    }


def publish(root: Path, outputs: dict[str, bytes], *, check: bool) -> None:
    destination = root / "followups/order10_phase2"
    if check:
        for name, content in outputs.items():
            path = destination / name
            if not path.is_file() or path.read_bytes() != content:
                raise RuntimeError(f"Derived artifact mismatch: {path}")
        print("Phase-2 audit artifacts match independently recomputed bytes")
        return
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        path = destination / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    print("Wrote " + ", ".join(str(destination / name) for name in outputs))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true",
                        help="Compare recomputed output with committed derived artifacts")
    args = parser.parse_args()
    outputs = audit(*load_inputs(args.root))
    publish(args.root, outputs, check=args.check)
    print(json.dumps({
        k: v for k, v in json.loads(outputs["summary.json"]).items()
        if k in {"final_distinct", "final_equivalent", "final_unresolved",
                 "phase2_euler_distinct", "phase2_homology_distinct"}
    }, sort_keys=True))


if __name__ == "__main__":
    main()
