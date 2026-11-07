"""Incremental, size-bounded order-10 non-Helly reports.

Reads only completed checksummed 100,000-graph census batches. The authoritative
census in runs/ is read-only. Reruns reuse per-batch report metadata and produce
a small root index. No full-census completion is needed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path

if __package__:
    from .non_helly import ROOT, readable_type, safe_graph6, sha256_file
else:
    from non_helly import ROOT, readable_type, safe_graph6, sha256_file

TOTAL = 11_716_571
BATCH = 100_000
PART_DIR = "reports/order10_parts"
INDEX_NAME = "non_helly_order10_index.md"
HEADER = (
    "| Index | graph6 | Homotopy type of G | Homotopy type of K(G) | K(G) Helly? |\n"
    "|---:|:---|:---|:---|:---:|\n"
)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(value, encoding="utf-8")
    os.replace(temp, path)


def completed_batches(root: Path):
    """Yield only a contiguous prefix of completed, SHA-256 checked batches."""
    base = root / "runs" / "order10" / "order10"
    gap = False
    for start in range(0, TOTAL, BATCH):
        end = min(start + BATCH, TOTAL) - 1
        stem = f"{start:08d}-{end:08d}"
        archive = base / "chunks" / f"{stem}.tsv.gz"
        marker = base / "completed" / f"{stem}.done.json"
        if not marker.exists() and not archive.exists():
            gap = True
            continue
        if gap:
            raise RuntimeError("Nonconsecutive completed order-10 batches")
        if not archive.is_file() or not marker.is_file():
            raise RuntimeError(f"Partially committed batch {stem}")
        meta = json.loads(marker.read_text(encoding="utf-8"))
        digest = sha256_file(archive)
        if meta != {"sha256": digest, "rows": end - start + 1}:
            raise RuntimeError(f"Invalid completed batch checksum {stem}")
        yield start, end, archive, digest


def _rows_to_part(
    root: Path, stem: str, part_no: int, lines: list[str], start: int, end: int,
) -> str:
    name = f"{stem}_p{part_no:03d}.md"
    title = f"# Non-Helly order-10 graphs: indices {start:,}–{end:,}\n\n"
    text = title + HEADER + "".join(lines)
    atomic_text(root / PART_DIR / name, text)
    return name


def render_batch(
    root: Path, start: int, end: int, archive: Path, digest: str,
    max_bytes: int,
) -> dict:
    stem = f"{start:08d}-{end:08d}"
    dest = root / PART_DIR
    sidecar = dest / f"{stem}.json"
    if sidecar.exists():
        state = json.loads(sidecar.read_text(encoding="utf-8"))
        if state.get("archive_sha256") != digest or state.get("max_bytes") != max_bytes:
            raise RuntimeError(f"Existing report generated from different input: {stem}")
        hashes = state.get("parts_sha256")
        if not isinstance(hashes, dict) or set(hashes) != set(state["parts"]):
            raise RuntimeError(f"Missing report-part checksums for batch {stem}")
        for filename in state["parts"]:
            part = dest / filename
            if not part.is_file() or sha256_file(part) != hashes[filename]:
                raise RuntimeError(f"Corrupt or missing report part: {filename}")
        return state

    selection: list[str] = []
    size = len(HEADER.encode("utf-8")) + 140
    first = last = None
    parts = []
    counters = Counter()
    idx = start
    part = 1

    with gzip.open(archive, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        needed = {
            "order", "index", "graph6", "helly_g", "helly_kg",
            "status_g", "status_kg", "htype_g", "htype_kg", "comparison",
        }
        if not needed.issubset(reader.fieldnames or []):
            raise RuntimeError(f"Missing fields in order-10 batch {stem}")
        for row in reader:
            if row["order"] != "10" or int(row["index"]) != idx:
                raise RuntimeError(f"Index mismatch in {stem} at {idx}")
            if row["helly_g"] not in {"TRUE", "FALSE", "UNKNOWN"}:
                raise RuntimeError(f"Invalid Helly flag in {stem}")
            if row["comparison"] not in {"EQUIVALENT", "DISTINCT", "UNRESOLVED"}:
                raise RuntimeError(f"Invalid comparison in {stem}")
            counters["graphs"] += 1
            counters["comparison_" + row["comparison"]] += 1
            counters["status_g_" + row["status_g"]] += 1
            counters["status_kg_" + row["status_kg"]] += 1
            if row["helly_g"] == "UNKNOWN":
                counters["unknown_helly_g"] += 1
            if row["helly_g"] == "FALSE" and row["helly_kg"] == "TRUE":
                counters["nonhelly_g_helly_kg"] += 1
            if row["helly_g"] != "FALSE":
                idx += 1
                continue
            counters["nonhelly_g"] += 1
            line = (
                f"| {idx} | {safe_graph6(row['graph6'])} | "
                f"{readable_type(row['status_g'], row['htype_g'])} | "
                f"{readable_type(row['status_kg'], row['htype_kg'])} | "
                f"{dict(TRUE='Yes', FALSE='No', UNKNOWN='Unknown')[row['helly_kg']]} |\n"
            )
            bytes_len = len(line.encode("utf-8"))
            if selection and size + bytes_len > max_bytes:
                parts.append(_rows_to_part(root, stem, part, selection, first, last))
                part += 1
                selection = []
                size = len(HEADER.encode("utf-8")) + 140
                first = None
            if first is None:
                first = idx
            last = idx
            selection.append(line)
            size += bytes_len
            idx += 1
    if idx != end + 1:
        raise RuntimeError(f"Wrong number of rows in batch {stem}")
    if selection:
        parts.append(_rows_to_part(root, stem, part, selection, first, last))
    hashes = {filename: sha256_file(dest / filename) for filename in parts}
    if any((dest / filename).stat().st_size > max_bytes for filename in parts):
        raise RuntimeError(f"Generated report exceeds size limit for {stem}")
    state = {
        "start": start, "end": end, "archive_sha256": digest,
        "max_bytes": max_bytes, "parts": parts, "parts_sha256": hashes,
        "counts": dict(sorted(counters.items())),
    }
    atomic_text(sidecar, json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state


def build_index(root: Path, records: list[dict]) -> Path:
    totals = Counter()
    for record in records:
        totals.update(record["counts"])
    text = [
        "# Non-Helly connected graphs of order 10",
        "",
        "Incremental, checksummed report. Only **completed** source batches "
        "are represented. Original census batches are never modified.",
        "",
        f"**Processed:** {totals['graphs']:,} / {TOTAL:,} connected graphs "
        f"({len(records)} completed batches).",
        f"**Non-Helly G:** {totals['nonhelly_g']:,}.",
        f"**Distinct types:** {totals['comparison_DISTINCT']:,}.",
        f"**Unresolved:** {totals['comparison_UNRESOLVED']:,}.",
        f"**G not Helly, K(G) Helly:** {totals['nonhelly_g_helly_kg']:,}.",
        f"**Unknown Helly(G) due to graph budget:** "
        f"{totals['unknown_helly_g']:,}.",
        "",
        "These totals cover only the processed prefix; they are **not** "
        "estimates of the remaining graphs.",
        "",
        "| Source indices | Processed | Non-Helly | Report parts |",
        "|---:|---:|---:|:---|",
    ]
    for record in records:
        links = ", ".join(
            f"[Part {i}]({PART_DIR}/{name})"
            for i, name in enumerate(record["parts"], 1)
        ) or "No non-Helly cases"
        text.append(
            f"| {record['start']:,}–{record['end']:,} | "
            f"{record['counts']['graphs']:,} | "
            f"{record['counts'].get('nonhelly_g', 0):,} | {links} |"
        )
    text.append("")
    destination = root / INDEX_NAME
    atomic_text(destination, "\n".join(text))
    return destination


def run(root: Path = ROOT, max_part_kib: int = 768) -> tuple[Path, int]:
    if max_part_kib < 2 or max_part_kib > 1024:
        raise ValueError("max_part_kib must be between 2 and 1024")
    max_bytes = 1024 * max_part_kib
    stage = root / "runs" / "order10"
    if not (stage / "manifest.json").is_file():
        raise RuntimeError("No started order-10 census")
    if (stage / "STOP_COUNTEREXAMPLE.json").exists():
        raise RuntimeError("Counterexample witness: inspect and stop, do not report")
    records = [
        render_batch(root, start, end, archive, digest, max_bytes)
        for start, end, archive, digest in completed_batches(root)
    ]
    return build_index(root, records), len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-part-kib", type=int, default=768)
    args = parser.parse_args()
    index, batches = run(max_part_kib=args.max_part_kib)
    print(f"Wrote {index} from {batches} completed order-10 batches")


if __name__ == "__main__":
    main()
