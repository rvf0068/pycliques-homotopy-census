"""Replay the full types of every originally nonexact order-10 row."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from importlib.resources import files
from pathlib import Path

import networkx as nx
from pycombtop import homotopy_type_with_verdict
from pycombtop.recursive_wedges import recursive_wedge_certificate

import order10_phase1 as phase1

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "followups/order10_exact_types"
UPSTREAM = "6da348bc116c3630e0d8bea88470366fe6d0fa4d"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encode(spheres):
    return ";".join(f"{d}:{spheres[d]}" for d in sorted(spheres)) or "0"


def exact_type(graph):
    verdict = homotopy_type_with_verdict(graph, max_vertices=64, max_simplices=25000)
    require(
        verdict.is_exact and not verdict.is_limited,
        "Missing exact homotopy certificate",
    )
    return encode(verdict.wedge.spheres)


def exception_rows():
    rows = {}
    batches = sorted((ROOT / "reports/order10_exceptions").glob("*_nonexact.tsv.gz"))
    require(len(batches) == 118, "Incomplete historical exception index")
    for batch in batches:
        with gzip.open(batch, "rt", newline="") as source:
            for row in csv.DictReader(source, delimiter="\t"):
                i = int(row["index"])
                require(i not in rows, f"Duplicate source index {i}")
                rows[i] = row
    require(len(rows) == 177, "Unexpected exception count")
    # Read the original McKay file once. Only the graph6 bytes at the 177
    # historical zero-based offsets are needed; no graph is reclassified here.
    dataset = files("pyg6data").joinpath("data", "graph10c.g6.gz")
    seen = set()
    with dataset.open("rb") as compressed, gzip.GzipFile(fileobj=compressed) as source:
        for index, line in enumerate(source):
            if index in rows:
                require(
                    line.strip().decode("ascii") == rows[index]["graph6"],
                    f"Wrong graph6 at {index}",
                )
                seen.add(index)
                if len(seen) == len(rows):
                    break
    require(seen == set(rows), "Missing McKay source line")
    return rows


def generate():
    original = exception_rows()
    unresolved, _ = phase1.original_unresolved()
    pending = {int(row["index"]) for row in unresolved}
    for row in unresolved:
        original_row = original[int(row["index"])]
        require(
            row["graph6"] == original_row["graph6"]
            and row["status_g"] == "EXACT"
            and row["betti_g"] == original_row["htype_g"],
            f"Original exact source type differs at {row['index']}",
        )
    require(
        pending == {i for i, r in original.items() if r["status_kg"] == "LIMITED"},
        "Wrong residual clique graphs",
    )
    require(set(original) - pending == {7749135}, "Wrong residual source graph")
    certs = json.loads(
        (ROOT / "followups/order10_phase1/certificates.json").read_bytes()
    )
    require(
        certs["baseline_commit"] == phase1.BASELINE_COMMIT, "Wrong Phase-1 baseline"
    )
    cases = {case["index"]: case for case in certs["cases"]}
    require(
        set(cases) == pending and len(cases) == len(certs["cases"]),
        "Phase-1 rows differ",
    )
    cores = {}
    for i, case in cases.items():
        require(
            case["graph6"] == original[i]["graph6"], f"Phase-1 graph6 differs at {i}"
        )
        graph = nx.from_graph6_bytes(original[i]["graph6"].encode("ascii"))
        cores[i] = phase1.replay_folds(
            phase1.reconstruct_clique_graph(graph), case["folds"]
        )
        require(
            phase1.graph6(cores[i]) == case["core_graph6"], f"Incorrect core at {i}"
        )

    types = {}
    representatives = {}
    groups = certs["groups"]
    require(len(groups) == 60, "Wrong number of representatives")
    for group in groups:
        rep = group["representative_index"]
        rep_graph = cores[rep]
        require(
            group["core_graph6"] == phase1.graph6(rep_graph),
            f"Wrong representative {rep}",
        )
        indexed = nx.from_graph6_bytes(group["core_graph6"].encode("ascii"))
        proof = recursive_wedge_certificate(indexed)
        wedge = encode(proof.spheres) if proof is not None else exact_type(indexed)
        for i in group["members"]:
            require(
                i not in representatives and cases[i]["representative_index"] == rep,
                f"Wrong group for {i}",
            )
            pairs = group["isomorphism_maps"][str(i)]
            mapping = dict(pairs)
            require(
                len(mapping) == len(pairs) == len(rep_graph)
                and set(mapping) == set(cores[i])
                and set(mapping.values()) == set(rep_graph),
                f"Invalid bijection at {i}",
            )
            mapped = nx.relabel_nodes(cores[i], mapping, copy=True)
            require(nx.utils.graphs_equal(mapped, rep_graph), f"Edge mismatch at {i}")
            representatives[i] = rep
            types[i] = wedge
    require(len(representatives) == 80, "Wrong number of Phase-2 members")
    for i in pending - types.keys():
        exact = phase1.recognize_exact_join(phase1.complement_factors(cores[i]))
        require(
            exact and exact == cases[i]["exact_kg"], f"Missing structural proof for {i}"
        )
        types[i] = exact[
            "betti"
        ]  # This is the exact sphere vector of the verified join.

    # The separate Betti-only G is the suspension of two disjoint squares.
    special = original[7749135]
    require(
        special["status_g"] == "BETTI_ONLY" and special["status_kg"] == "EXACT",
        "Wrong special row",
    )
    graph = nx.from_graph6_bytes(special["graph6"].encode("ascii"))
    poles = {8, 9}
    base = graph.subgraph(set(graph) - poles)
    require(
        all(set(graph[p]) == set(base) for p in poles)
        and nx.is_isomorphic(
            base, nx.disjoint_union(nx.cycle_graph(4), nx.cycle_graph(4))
        ),
        "Incorrect two-square suspension",
    )
    require(
        exact_type(graph) == "1:1;2:2", "Suspension formula and classifier disagree"
    )
    require(
        exact_type(phase1.reconstruct_clique_graph(graph)) == special["htype_kg"],
        "Original clique-graph type differs for the two-square suspension",
    )
    with (ROOT / "followups/order10_phase2/results.tsv").open(newline="") as earlier:
        comparisons = {
            int(r["index"]): r["comparison"]
            for r in csv.DictReader(earlier, delimiter="\t")
        }
    require(
        comparisons.keys() == representatives.keys(),
        "Phase-2 comparison coverage differs",
    )
    rows = []
    for i, old in sorted(original.items()):
        g = "1:1;2:2" if i == 7749135 else old["htype_g"]
        k = old["htype_kg"] if i == 7749135 else types[i]
        require("UNKNOWN" not in (g, k), f"Incomplete types at {i}")
        comparison = "EQUIVALENT" if g == k else "DISTINCT"
        if i in representatives:
            prior = comparisons[i]
            method = "representative"
        elif i in pending:
            prior = cases[i]["comparison"]
            method = "phase1_join"
        else:
            prior = old["comparison"]
            method = "suspension_of_two_squares"
        require(prior == comparison, f"Independent comparison differs at {i}")
        rows.append(
            dict(
                index=i,
                graph6=old["graph6"],
                htype_g=g,
                htype_kg=k,
                comparison=comparison,
                representative_index=representatives.get(i, ""),
                proof=method,
            )
        )
    baseline = json.loads((ROOT / "runs/order10/summary.json").read_bytes())["orders"][
        0
    ]["counts"]
    require(
        baseline["status_g_BETTI_ONLY"] == 1 and baseline["status_kg_LIMITED"] == 176,
        "Historical counts differ",
    )
    delta = Counter(r["comparison"] for r in rows if r["index"] in pending)
    require(
        delta == {"EQUIVALENT": 11, "DISTINCT": 165},
        "Independent comparison audit disagrees",
    )
    n = baseline["graphs"]
    require(
        baseline["status_g_EXACT"] + 1
        == baseline["status_kg_EXACT"] + len(pending)
        == n,
        "Incomplete coverage",
    )
    summary = dict(
        order=10,
        connected_graphs=n,
        exact_G=n,
        exact_KG=n,
        unresolved_types=0,
        equivalent=baseline["comparison_EQUIVALENT"] + delta["EQUIVALENT"],
        distinct=baseline["comparison_DISTINCT"] + delta["DISTINCT"],
        verified_representatives=len(groups),
        original_nonexact_rows=len(rows),
        pycliques_project_commit=UPSTREAM,
    )
    return {
        "results.tsv": phase1.tsv_bytes(rows, list(rows[0])),
        "summary.json": (json.dumps(summary, indent=2) + "\n").encode(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Recompute and compare the committed files byte for byte",
    )
    args = parser.parse_args()
    output = generate()
    if args.check:
        for name, expected in output.items():
            require(
                (OUTPUT / name).read_bytes() == expected,
                f"Full-type audit differs: {name}",
            )
        print(
            "All 177 order-10 full-type records and their summary match the committed files."
        )
    else:
        phase1.publish(OUTPUT, output, check=False)
