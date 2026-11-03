"""Independent streaming validation and per-order summaries of completed runs."""

from __future__ import annotations

import argparse
import collections
import csv
import gzip
import io
import json
import os

from census import COLUMNS, batch_size, comparison, paths, stage_orders
from graph_sources import EXPECTED_COUNTS, graphs6
from provenance import ROOT, check_manifest, manifest, sha256


def validate_order(n: int, directory, summary_dir) -> dict:
    total, batch = EXPECTED_COUNTS[n], batch_size(n)
    counters = collections.Counter()
    expected = 0
    unresolved_tmp = summary_dir / f"unresolved_order{n}.tsv.gz.tmp"
    unresolved_final = summary_dir / f"unresolved_order{n}.tsv.gz"

    with unresolved_tmp.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as out:
            with io.TextIOWrapper(
                out, encoding="utf-8", newline="", write_through=True
            ) as stream:
                writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
                writer.writerow([
                    "order", "index", "graph6", "helly_g", "helly_kg",
                    "comparison", "status_g", "status_kg", "betti_g", "betti_kg",
                ])
                graphs = iter(graphs6(n))
                for start in range(0, total, batch):
                    end = min(start + batch, total) - 1
                    compressed, journal, marker = paths(directory, start, end)
                    if journal.exists():
                        raise RuntimeError(f"Incomplete checkpoint: {journal}")
                    if not compressed.is_file() or not marker.is_file():
                        raise RuntimeError(f"Missing batch: order {n}, {start}-{end}")
                    meta = json.loads(marker.read_text())
                    if meta != {
                        "sha256": sha256(compressed), "rows": end - start + 1
                    }:
                        raise RuntimeError(f"Batch integrity check failed: {compressed}")

                    with gzip.open(
                        compressed, "rt", encoding="utf-8", newline=""
                    ) as rows_file:
                        reader = csv.DictReader(rows_file, delimiter="\t")
                        if reader.fieldnames != list(COLUMNS):
                            raise RuntimeError(f"Invalid TSV schema: {compressed}")
                        count = 0
                        for row in reader:
                            g6 = next(graphs, None)
                            if (
                                g6 is None
                                or row["graph6"] != g6
                                or int(row["index"]) != expected
                                or int(row["order"]) != n
                            ):
                                raise RuntimeError(
                                    f"Source/index mismatch at order {n} index {expected}"
                                )
                            if row["status_g"] not in (
                                "EXACT", "BETTI_ONLY", "LIMITED"
                            ):
                                raise RuntimeError("Invalid status for G")
                            if row["status_kg"] not in (
                                "EXACT", "BETTI_ONLY", "LIMITED"
                            ):
                                raise RuntimeError("Invalid status for K(G)")
                            if row["helly_g"] not in ("TRUE", "FALSE"):
                                raise RuntimeError("Invalid Helly status for G")
                            if row["helly_kg"] not in (
                                "TRUE", "FALSE", "UNKNOWN"
                            ):
                                raise RuntimeError("Invalid Helly status for K(G)")
                            for suffix in ("g", "kg"):
                                status = row[f"status_{suffix}"]
                                typ = row[f"htype_{suffix}"]
                                betti = row[f"betti_{suffix}"]
                                if status != "EXACT" and typ != "UNKNOWN":
                                    raise RuntimeError(
                                        "Nonexact type incorrectly presented as exact"
                                    )
                                if status == "EXACT" and typ != betti:
                                    raise RuntimeError(
                                        "Exact wedge not consistent with homology"
                                    )
                                if status == "LIMITED" and betti != "UNKNOWN":
                                    raise RuntimeError(
                                        "Limited verdict incorrectly has homology"
                                    )
                                if status == "BETTI_ONLY" and betti == "UNKNOWN":
                                    raise RuntimeError(
                                        "Betti-only verdict lacks homology"
                                    )
                            result = comparison(
                                {
                                    "status": row["status_g"],
                                    "betti": row["betti_g"],
                                },
                                {
                                    "status": row["status_kg"],
                                    "betti": row["betti_kg"],
                                },
                            )
                            if result != row["comparison"]:
                                raise RuntimeError("Comparison disagrees with verdicts")
                            if (
                                row["helly_g"] == "TRUE"
                                and row["helly_kg"] == "FALSE"
                            ):
                                raise RuntimeError("Known Helly implication violated")
                            if (
                                row["helly_kg"] == "TRUE"
                                and result == "DISTINCT"
                            ):
                                raise RuntimeError(
                                    "Completed batch contains unreported candidate"
                                )
                            counters["graphs"] += 1
                            for field in (
                                "helly_g", "helly_kg", "status_g", "status_kg"
                            ):
                                counters[f"{field}_{row[field]}"] += 1
                            counters[f"comparison_{result}"] += 1
                            if result == "UNRESOLVED":
                                writer.writerow([
                                    row[column]
                                    for column in (
                                        "order", "index", "graph6", "helly_g",
                                        "helly_kg", "comparison", "status_g",
                                        "status_kg", "betti_g", "betti_kg",
                                    )
                                ])
                            count += 1
                            expected += 1
                        if count != end - start + 1:
                            raise RuntimeError(
                                f"Wrong number of batch records: {compressed}"
                            )
                if next(graphs, None) is not None or expected != total:
                    raise RuntimeError(
                        f"Source graph count differs for order {n}: {expected}"
                    )
    os.replace(unresolved_tmp, unresolved_final)
    return {
        "order": n,
        "counts": dict(sorted(counters.items())),
        "unresolved": unresolved_final.relative_to(ROOT).as_posix(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", required=True, choices=("through6", "7", "8", "9", "10")
    )
    args = parser.parse_args()
    orders = stage_orders(args.stage)
    run_dir = ROOT / "runs" / (
        "through6" if args.stage == "through6" else f"order{args.stage}"
    )
    if (run_dir / "STOP_COUNTEREXAMPLE.json").exists():
        raise SystemExit("Counterexample witness saved; run intentionally stopped")
    info = json.loads((run_dir / "manifest.json").read_text())
    check_manifest(run_dir, manifest(orders, info["settings"]))
    summaries = [
        validate_order(n, run_dir / f"order{n}", run_dir) for n in orders
    ]
    destination = run_dir / "summary.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"manifest": info, "orders": summaries},
                   indent=2, sort_keys=True) + "\n"
    )
    os.replace(temporary, destination)
    for summary in summaries:
        print(
            f"Validated order {summary['order']}: "
            f"{summary['counts']['graphs']} original-indexed connected graphs"
        )
    print("Summary:", destination)


if __name__ == "__main__":
    main()
