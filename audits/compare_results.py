"""Compare two completed homotopy censuses, excluding narrative reason fields.

The original McKay graph6 indices, types, exactness, Betti vectors, Helly
flags, K(G) order, and conclusion must agree row-for-row for all graphs.
"""

from __future__ import annotations

import argparse
import csv
import gzip
from itertools import zip_longest
from pathlib import Path

STAGES = {
    "through6": range(1, 7),
    "7": (7,),
    "8": (8,),
    "9": (9,),
    "10": (10,),
}
FIELDS = (
    "order", "index", "graph6", "helly_g", "helly_kg", "k_order",
    "status_g", "htype_g", "betti_g", "status_kg", "htype_kg",
    "betti_kg", "comparison",
)


def rows(root: Path, stage: str):
    directory = root / (
        "through6" if stage == "through6" else f"order{stage}"
    )
    for order in STAGES[stage]:
        folder = directory / f"order{order}" / "chunks"
        files = sorted(folder.glob("*.tsv.gz"))
        if not files:
            raise RuntimeError(f"No completed batches for order {order}: {folder}")
        for path in files:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream, delimiter="\t")
                if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
                    raise RuntimeError(f"Wrong table schema: {path}")
                yield from reader


def compare(baseline: Path, candidate: Path, stage: str) -> int:
    count = 0
    for before, after in zip_longest(
        rows(baseline, stage), rows(candidate, stage)
    ):
        if before is None or after is None:
            raise RuntimeError(
                f"Different graph counts for stage {stage}: at row {count}"
            )
        for field in FIELDS:
            if before[field] != after[field]:
                raise RuntimeError(
                    f"Stage {stage} row {count}, original index "
                    f"{before['index']}: field {field} changed from "
                    f"{before[field]!r} to {after[field]!r}"
                )
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--stage", choices=tuple(STAGES), action="append", required=True
    )
    args = parser.parse_args()
    for stage in args.stage:
        count = compare(args.baseline, args.candidate, stage)
        print(f"Stage {stage}: {count:,} results identical in all scientific fields")


if __name__ == "__main__":
    main()
