#!/usr/bin/env python3
"""Certify elementary reductions and select order-10 homotopy follow-up cores.

Only reads the checksummed order-10 census. Never modifies its manifests,
chunks, completion markers, original indexes, or validated summaries.

Run from the repository root:
    .venv/bin/python audits/order10_phase1.py
    .venv/bin/python audits/order10_phase1.py --check

A classified row is EXACT only when both sides have certified wedge types.
Equal Betti vectors alone do not establish equivalence in general; here the
original G verdict is EXACT and the recognized K(G) type is also a certified
wedge of spheres, so its entire homotopy type is specified by those vectors.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx
from networkx.algorithms.isomorphism import GraphMatcher

ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "8e768705fd8b41c5ca2cfea1ed9eedf633f5a43d"
BASELINE_UPSTREAM = "a51bc08974dd83b0ca411b68bd7d959e15789178"
EXPECTED_UNRESOLVED = 176
EXPECTED_ORIGINAL_GRAPHS = 11_716_571
EXPECTED_EXACT = 96
EXPECTED_UNCLASSIFIED = 80
EXPECTED_ISOMORPHISM_CLASSES = 60
REQUIRED_FIELDS = {
    "order", "index", "graph6", "helly_g", "helly_kg", "status_g",
    "status_kg", "comparison", "betti_g",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def original_unresolved(root: Path = ROOT) -> tuple[list[dict], dict]:
    folder = root / "runs" / "order10"
    summary_path = folder / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert len(summary["orders"]) == 1
    counts = summary["orders"][0]["counts"]
    if (counts.get("graphs"), counts.get("comparison_UNRESOLVED")) != (
        EXPECTED_ORIGINAL_GRAPHS, EXPECTED_UNRESOLVED
    ):
        raise RuntimeError("The census summary does not match the validated baseline")
    if summary["manifest"]["monorepo_commit"] != BASELINE_UPSTREAM:
        raise RuntimeError("Unexpected original monorepo pin")
    input_path = folder / "unresolved_order10.tsv.gz"
    with gzip.open(input_path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if not REQUIRED_FIELDS.issubset(set(reader.fieldnames or [])):
            raise RuntimeError("Unexpected unresolved TSV schema")
        rows = list(reader)
    if len(rows) != EXPECTED_UNRESOLVED:
        raise RuntimeError("Original unresolved-record count changed")
    indices = [int(r["index"]) for r in rows]
    if indices != sorted(set(indices)):
        raise RuntimeError("Duplicate or unsorted original indices")
    for row in rows:
        if (row["order"], row["status_g"], row["status_kg"],
            row["comparison"]) != ("10", "EXACT", "LIMITED", "UNRESOLVED"):
            raise RuntimeError(f"Unexpected original verdict at index {row['index']}")
    return rows, {
        "baseline_commit": BASELINE_COMMIT,
        "baseline_upstream": BASELINE_UPSTREAM,
        "original_summary_sha256": sha256(summary_path),
        "original_unresolved_sha256": sha256(input_path),
    }


def reconstruct_clique_graph(graph: nx.Graph) -> nx.Graph:
    """Use maximal complete sets as K(G)'s vertices, in a stable order."""
    maximal = [frozenset(v) for v in sorted(
        tuple(sorted(q)) for q in nx.find_cliques(graph)
    )]
    result = nx.Graph()
    result.add_nodes_from(range(len(maximal)))
    result.add_edges_from(
        (i, j) for i, j in combinations(result.nodes, 2)
        if not maximal[i].isdisjoint(maximal[j])
    )
    return result


def closed_neighborhood(graph: nx.Graph, v: int) -> set[int]:
    return set(graph[v]) | {v}


def pare_with_witnesses(graph: nx.Graph) -> tuple[nx.Graph, list[list[int]]]:
    """Produce the lexicographically first sequence of legal fold deletions."""
    remaining = graph.copy()
    moves: list[list[int]] = []
    while True:
        move = next((
            (v, u)
            for v in sorted(remaining)
            for u in sorted(remaining)
            if v != u and closed_neighborhood(remaining, v)
            <= closed_neighborhood(remaining, u)
        ), None)
        if move is None:
            return remaining, moves
        v, u = move
        moves.append([v, u])
        remaining.remove_node(v)


def replay_folds(graph: nx.Graph, moves: list[list[int]]) -> nx.Graph:
    """Independently validate every recorded N[v] subseteq N[u] witness."""
    remaining = graph.copy()
    for v, u in moves:
        if (v not in remaining or u not in remaining or v == u or
                not closed_neighborhood(remaining, v)
                <= closed_neighborhood(remaining, u)):
            raise ValueError(f"Invalid dominated-vertex move: {v}, {u}")
        remaining.remove_node(v)
    return remaining


def graph6(graph: nx.Graph) -> str:
    h = nx.convert_node_labels_to_integers(graph, ordering="sorted")
    return nx.to_graph6_bytes(h, header=False).decode("ascii").strip()


def complement_factors(core: nx.Graph) -> list[dict]:
    complement = nx.complement(core)
    factors = []
    for component in sorted(nx.connected_components(complement), key=lambda c: min(c)):
        factor = complement.subgraph(component)
        n, m = factor.number_of_nodes(), factor.number_of_edges()
        if n == 1:
            kind = "K1"
        elif n == 2 and m == 1:
            kind = "K2"
        elif n in (6, 10) and m == n and all(d == 2 for _, d in factor.degree()):
            kind = f"C{n}"
        else:
            kind = "OTHER"
        factors.append({"kind": kind, "vertices": sorted(component)})
    return factors


def recognize_exact_join(factors: list[dict]) -> dict | None:
    """Contractible if there is a cone; otherwise recognize sphere joins."""
    kinds = [f["kind"] for f in factors]
    if "K1" in kinds:
        return {"type": "Contractible", "betti": "0", "dimension": None,
                "multiplicity": 0}
    if "OTHER" in kinds or not kinds:
        return None
    # Ind(K2)=S^0, Ind(C6)=S^1 v S^1, Ind(C10)=S^2.
    degrees = {"K2": (0, 1), "C6": (1, 2), "C10": (2, 1)}
    dimension, multiplicity = -1, 1
    for kind in kinds:
        dim, count = degrees[kind]
        dimension += dim + 1
        multiplicity *= count
    return {"type": f"{multiplicity} copies of S^{dimension}",
            "betti": f"{dimension}:{multiplicity}",
            "dimension": dimension, "multiplicity": multiplicity}


def invariant_key(core: nx.Graph) -> tuple:
    """Necessary invariants only; an exact isomorphism test is still required."""
    complement = nx.complement(core)
    return (len(core), core.number_of_edges(),
            tuple(sorted(d for _, d in complement.degree())),
            tuple(sorted(map(len, nx.connected_components(complement)))),
            nx.weisfeiler_lehman_graph_hash(complement, iterations=3))


def group_unclassified(cases: list[dict], cores: dict[int, nx.Graph]) -> list[dict]:
    """Verify isomorphism; store explicit vertex maps to the representative."""
    groups: list[dict] = []
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for case in sorted(cases, key=lambda x: x["index"]):
        index = case["index"]
        core = cores[index]
        key = invariant_key(core)
        for group in buckets[key]:
            rep = cores[group["representative_index"]]
            # Match sparse complements: dense-core matching can be exponentially slow.
            match = GraphMatcher(nx.complement(core), nx.complement(rep))
            if match.is_isomorphic():
                mapping = sorted([[int(a), int(b)] for a, b in match.mapping.items()])
                group["members"].append(index)
                group["isomorphism_maps"][str(index)] = mapping
                case["representative_index"] = group["representative_index"]
                break
        else:
            group = {
                "representative_index": index,
                "representative_graph6": case["graph6"],
                "core_graph6": graph6(core),
                "core_order": len(core),
                "core_edges": core.number_of_edges(),
                "members": [index],
                "isomorphism_maps": {
                    str(index): [[int(v), int(v)] for v in sorted(core)]
                },
            }
            case["representative_index"] = index
            buckets[key].append(group)
            groups.append(group)
    return groups


def analyze_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    audited: list[dict] = []
    remaining_cores: dict[int, nx.Graph] = {}
    for row in sorted(rows, key=lambda x: int(x["index"])):
        i = int(row["index"])
        g = nx.from_graph6_bytes(row["graph6"].encode("ascii"))
        if len(g) != 10 or not nx.is_connected(g):
            raise RuntimeError(f"Bad source graph at original index {i}")
        k = reconstruct_clique_graph(g)
        core, moves = pare_with_witnesses(k)
        replayed = replay_folds(k, moves)
        if set(replayed) != set(core) or set(replayed.edges) != set(core.edges):
            raise RuntimeError(f"Fold core mismatch at index {i}")
        factors = complement_factors(core)
        result = recognize_exact_join(factors)
        if result is None:
            comparison = "UNCLASSIFIED"
            remaining_cores[i] = core
        elif result["betti"] == row["betti_g"]:
            comparison = "EQUIVALENT"
        else:
            comparison = "DISTINCT"
        audited.append({
            "index": i, "graph6": row["graph6"],
            "original_helly_g": row["helly_g"],
            "original_helly_kg": row["helly_kg"],
            "original_betti_g": row["betti_g"],
            "original_htype_g": row.get("htype_g", row["betti_g"]),
            "clique_graph_order": len(k),
            "clique_graph_edges": k.number_of_edges(),
            "folds": moves,
            "core_vertices": sorted(core),
            "core_graph6": graph6(core),
            "core_order": len(core),
            "core_edges": core.number_of_edges(),
            "complement_factors": factors,
            "exact_kg": result,
            "comparison": comparison,
            "representative_index": None,
        })
    unknown = [case for case in audited if case["comparison"] == "UNCLASSIFIED"]
    groups = group_unclassified(unknown, remaining_cores)
    return audited, groups


def tsv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, delimiter="\t", fieldnames=fields,
                            lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def artifacts(rows: list[dict], groups: list[dict], provenance: dict) -> dict[str, bytes]:
    counts = Counter(row["comparison"] for row in rows)
    if (len(rows), sum(v for k, v in counts.items() if k != "UNCLASSIFIED"),
            counts["UNCLASSIFIED"], len(groups)) != (
            EXPECTED_UNRESOLVED, EXPECTED_EXACT,
            EXPECTED_UNCLASSIFIED, EXPECTED_ISOMORPHISM_CLASSES):
        raise RuntimeError(f"Unexpected phase-1 totals: {counts}, {len(groups)} cores")
    if any(row["original_helly_kg"] == "TRUE" and
           row["comparison"] != "EQUIVALENT" for row in rows):
        raise RuntimeError("Unresolved clique-Helly exception not certified equivalent")
    summary = {
        **provenance,
        "input_unresolved": len(rows),
        "certified_equivalent": counts["EQUIVALENT"],
        "certified_distinct": counts["DISTINCT"],
        "unclassified": counts["UNCLASSIFIED"],
        "nonisomorphic_unclassified_cores": len(groups),
        "clique_helly_original_exceptions": [
            row["index"] for row in rows if row["original_helly_kg"] == "TRUE"
        ],
        "methods": {
            "folds": "Replay N[v] subseteq N[u] on the current clique graph",
            "join": "Delta(core) = join of independence complexes of complement components",
            "factors": "Ind(K2)=S0; Ind(C6)=S1 v S1; Ind(C10)=S2; K1 gives a cone",
            "comparison": "Both types are exact sphere wedges, so their reduced Betti vectors determine agreement",
            "isomorphism": "WL hashes only bucket candidates; exact GraphMatcher supplies explicit maps",
        },
    }
    reduced_rows = [{
        "index": row["index"], "graph6": row["graph6"],
        "helly_kg": row["original_helly_kg"],
        "k_order": row["clique_graph_order"],
        "core_order": row["core_order"],
        "core_graph6": row["core_graph6"],
        "factors": ";".join(sorted(f["kind"] for f in row["complement_factors"])),
        "htype_g": row["original_htype_g"],
        "betti_kg": row["exact_kg"]["betti"] if row["exact_kg"] else "UNKNOWN",
        "comparison": row["comparison"],
        "representative_index": row["representative_index"] or "",
    } for row in rows]
    group_rows = [{
        "representative_index": group["representative_index"],
        "graph6": group["representative_graph6"],
        "core_order": group["core_order"],
        "core_edges": group["core_edges"],
        "core_graph6": group["core_graph6"],
        "members": ";".join(map(str, group["members"])),
    } for group in groups]
    serialized = lambda data: (json.dumps(data, sort_keys=True, indent=2,
                                          ensure_ascii=True) + "\n").encode("utf-8")
    return {
        "summary.json": serialized(summary),
        "results.tsv": tsv_bytes(reduced_rows, [
            "index", "graph6", "helly_kg", "k_order", "core_order",
            "core_graph6", "factors", "htype_g", "betti_kg",
            "comparison", "representative_index",
        ]),
        "representatives.tsv": tsv_bytes(group_rows, [
            "representative_index", "graph6", "core_order", "core_edges",
            "core_graph6", "members",
        ]),
        "certificates.json": serialized({
            "baseline_commit": BASELINE_COMMIT,
            "cases": rows,
            "groups": groups,
        }),
    }


def publish(output: Path, generated: dict[str, bytes], *, check: bool) -> None:
    if check:
        for name, content in generated.items():
            path = output / name
            if not path.is_file() or path.read_bytes() != content:
                raise RuntimeError(f"Derived artifact differs from the audit: {path}")
        print("All phase-1 generated artifacts match their recomputed values")
        return
    output.mkdir(parents=True, exist_ok=True)
    for name, content in generated.items():
        target = output / name
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            tmp.write_bytes(content)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    print("Wrote " + ", ".join(str(output / n) for n in generated))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true",
                        help="Regenerate in memory and check every committed byte")
    args = parser.parse_args()
    rows, provenance = original_unresolved(args.root)
    cases, groups = analyze_rows(rows)
    files = artifacts(cases, groups, provenance)
    target = args.output or args.root / "followups" / "order10_phase1"
    publish(target, files, check=args.check)
    print(json.dumps({k: v for k, v in json.loads(files["summary.json"]).items()
                      if k in ("input_unresolved", "certified_equivalent", "certified_distinct",
                               "unclassified", "nonisomorphic_unclassified_cores")},
                     sort_keys=True))


if __name__ == "__main__":
    main()