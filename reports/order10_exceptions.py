"""Incremental index of unresolved or nonexact order-10 graph records.

Only reads completed, SHA-256 checked census batches. Unlike the
non-Helly Markdown report, this postprocessor also includes G with unknown
Helly status and any BETTI_ONLY classifications. It never modifies runs/.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import json
import os
from pathlib import Path

if __package__:
    from .non_helly import ROOT
    from .order10_split import atomic_text, completed_batches
else:
    from non_helly import ROOT
    from order10_split import atomic_text, completed_batches

DIRECTORY = "reports/order10_exceptions"
INDEX = "order10_exceptions_index.md"
FIELDS = (
    "index", "graph6", "helly_g", "helly_kg", "status_g", "status_kg",
    "betti_g", "betti_kg", "htype_g", "htype_kg", "comparison",
    "reason_g", "reason_kg",
)


def process_batch(root: Path, start: int, end: int, archive: Path, digest: str) -> dict:
    stem = f"{start:08d}-{end:08d}"
    base = root / DIRECTORY
    base.mkdir(parents=True, exist_ok=True)
    marker = base / f"{stem}.json"
    result = base / f"{stem}_nonexact.tsv.gz"
    if marker.exists():
        data = json.loads(marker.read_text(encoding="utf-8"))
        if data.get("archive_sha256") != digest or not result.is_file():
            raise RuntimeError("Exception report no longer matches batch " + stem)
        return data

    temp = result.with_suffix(".gz.tmp")
    counts = Counter()
    with (
        gzip.open(archive, "rt", encoding="utf-8", newline="") as stream,
        gzip.open(temp, "wt", encoding="utf-8", newline="") as target,
    ):
        rows = csv.DictReader(stream, delimiter="\t")
        if not set(FIELDS).issubset(rows.fieldnames or ()):
            raise RuntimeError(f"Missing census columns in batch {stem}")
        writer = csv.DictWriter(
            target, fieldnames=FIELDS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for expected, row in enumerate(rows, start):
            if expected > end or row["order"] != "10" or int(row["index"]) != expected:
                raise RuntimeError(f"Source index mismatch in batch {stem}")
            counts["graphs"] += 1
            if row["helly_g"] == "FALSE" and row["helly_kg"] == "TRUE":
                counts["nonhelly_g_helly_kg"] += 1
            if row["comparison"] == "DISTINCT":
                counts["distinct"] += 1
            nonexact = row["status_g"] != "EXACT" or row["status_kg"] != "EXACT"
            if nonexact:
                writer.writerow({field: row[field] for field in FIELDS})
                counts["nonexact"] += 1
            if row["comparison"] == "UNRESOLVED":
                counts["unresolved"] += 1
        if counts["graphs"] != end - start + 1:
            raise RuntimeError("Truncated census batch " + stem)
    os.replace(temp, result)
    info = {
        "start": start, "end": end, "archive_sha256": digest,
        "file": result.name, "counts": dict(sorted(counts.items())),
    }
    atomic_text(marker, json.dumps(info, indent=2, sort_keys=True) + "\n")
    return info


def run(root: Path = ROOT) -> tuple[Path, int]:
    stage = root / "runs" / "order10"
    if not (stage / "manifest.json").exists():
        raise RuntimeError("Order-10 census has not started")
    if (stage / "STOP_COUNTEREXAMPLE.json").exists():
        raise RuntimeError("Investigate stop witness before generating further reports")
    records = [
        process_batch(root, start, end, archive, digest)
        for start, end, archive, digest in completed_batches(root)
    ]
    totals = Counter()
    for item in records:
        totals.update(item["counts"])
    lines = [
        "# Order-10 unresolved and nonexact cases",
        "",
        "Generated from **completed, SHA-256 checked batches only**. "
        "Original indices and graph6 strings are retained; no historical "
        "census files are modified.",
        "",
        f"Processed graphs: {totals['graphs']:,}. "
        f"Not exactly classified: {totals['nonexact']:,}. "
        f"Unresolved comparisons: {totals['unresolved']:,}.",
        f"Distinct reduced-homotopy records: {totals['distinct']:,}. "
        f"G non-Helly with K(G) Helly: "
        f"{totals['nonhelly_g_helly_kg']:,}.",
        "",
        "Nonexact TSV files include Betti-only and time-limited rows "
        "(including records where Helly(G) is unknown). They may be "
        "used for a separate follow-up pass without overwriting the "
        "order-10 census.",
        "",
        "| Index range | Nonexact records | TSV.gz |",
        "|---:|---:|:---|",
    ]
    for entry in records:
        lines.append(
            f"| {entry['start']:,}–{entry['end']:,} | "
            f"{entry['counts'].get('nonexact', 0):,} | "
            f"[Records]({DIRECTORY}/{entry['file']}) |"
        )
    lines.append("")
    destination = root / INDEX
    atomic_text(destination, "\n".join(lines))
    return destination, len(records)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    destination, count = run()
    print(f"Wrote {destination} from {count} checked order-10 batches")


if __name__ == "__main__":
    main()
