"""Readable Markdown reports of graphs G that are not clique-Helly.

Only read completed, checksummed census batches.  This postprocessor lives
outside scripts/ so adding it does not change the existing census manifest:
a finished Codespaces stage NEVER needs to be discarded or recalculated.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STAGES = {
    "through6": tuple(range(1, 7)),
    "7": (7,),
    "8": (8,),
    "9": (9,),
    "10": (10,),
}
COUNTS = {
    1: 1,
    2: 1,
    3: 2,
    4: 6,
    5: 21,
    6: 112,
    7: 853,
    8: 11117,
    9: 261080,
    10: 11716571,
}
REQUIRED_COLUMNS = (
    "order",
    "index",
    "graph6",
    "helly_g",
    "helly_kg",
    "status_g",
    "htype_g",
    "status_kg",
    "htype_kg",
)


def wedge_latex(encoded: str) -> str:
    """Translate a *certified* sparse sphere vector into inline LaTeX."""
    if encoded == "0":
        return "Contractible"
    seen: set[int] = set()
    pieces: list[str] = []
    for part in encoded.split(";"):
        match = re.fullmatch(r"([0-9]+):([1-9][0-9]*)", part)
        if not match:
            raise ValueError(f"Malformed exact homotopy-type vector: {encoded!r}")
        dimension, count = (int(x) for x in match.groups())
        if dimension in seen:
            raise ValueError(f"Duplicate sphere dimension in {encoded!r}")
        seen.add(dimension)
        sphere = f"S^{{{dimension}}}"
        pieces.append(
            sphere if count == 1 else rf"\bigvee_{{{count}}} {sphere}"
        )
    if not pieces:
        raise ValueError("Empty exact sphere vector")
    return r"\(" + r" \vee ".join(pieces) + r"\)"


def readable_type(status: str, encoded: str) -> str:
    """Never mistake a Betti-only result for a homotopy equivalence."""
    if status == "EXACT":
        return wedge_latex(encoded)
    if encoded != "UNKNOWN":
        raise ValueError("An inexact homotopy type must be UNKNOWN")
    if status == "BETTI_ONLY":
        return "Undetermined (Betti numbers only)"
    if status == "LIMITED":
        return "Undetermined (resource limit)"
    raise ValueError(f"Unknown homotopy status: {status!r}")


def safe_graph6(value: str) -> str:
    """Inline HTML code avoids Markdown-table separators in graph6 strings.

    In particular graph6 may contain literal pipe characters and backticks.
    """
    if not value or any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
        raise ValueError("Invalid graph6 field")
    return "<code>" + html.escape(value, quote=True).replace("|", "&#124;") + "</code>"


def stage_directory(stage: str, root: Path) -> Path:
    return root / "runs" / ("through6" if stage == "through6" else f"order{stage}")


def output_path(stage: str, root: Path) -> Path:
    suffix = "through6" if stage == "through6" else f"order{stage}"
    return root / f"non_helly_{suffix}.md"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def iter_verified_rows(stage: str, root: Path):
    """Stream every completed record; do not rebuild graphs or rerun homotopy."""
    folder = stage_directory(stage, root)
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Missing census manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("orders") != list(STAGES[stage]):
        raise RuntimeError("Census manifest has unexpected stage orders")
    if (folder / "STOP_COUNTEREXAMPLE.json").exists():
        raise RuntimeError(
            "Counterexample stop witness exists; inspect it before reporting a completed stage"
        )

    for n in STAGES[stage]:
        total = COUNTS[n]
        batch = 100000 if n == 10 else 10000
        order_dir = folder / f"order{n}"
        expected_index = 0
        for start in range(0, total, batch):
            end = min(start + batch, total) - 1
            stem = f"{start:08d}-{end:08d}"
            archived = order_dir / "chunks" / f"{stem}.tsv.gz"
            done = order_dir / "completed" / f"{stem}.done.json"
            partial = order_dir / "partial" / f"{stem}.partial.tsv"
            if partial.exists():
                raise RuntimeError(f"Incomplete checkpoint: {partial}")
            if not archived.is_file() or not done.is_file():
                raise RuntimeError(f"Incomplete batch: order {n} indices {start}-{end}")
            metadata = json.loads(done.read_text(encoding="utf-8"))
            if metadata != {
                "sha256": sha256_file(archived),
                "rows": end - start + 1,
            }:
                raise RuntimeError(f"Invalid batch checksum or row count: {archived}")
            count = 0
            with gzip.open(archived, "rt", encoding="utf-8", newline="") as stream:
                rows = csv.DictReader(stream, delimiter="\t")
                if not rows.fieldnames or not set(REQUIRED_COLUMNS).issubset(
                    rows.fieldnames
                ):
                    raise RuntimeError(f"Missing census columns in {archived}")
                for row in rows:
                    if (
                        int(row["order"]) != n
                        or int(row["index"]) != expected_index
                    ):
                        raise RuntimeError(
                            f"Wrong graph index in {archived}: expected {expected_index}"
                        )
                    if row["helly_g"] not in {"TRUE", "FALSE"}:
                        raise RuntimeError("Missing/invalid Helly status for G")
                    if row["helly_kg"] not in {"TRUE", "FALSE", "UNKNOWN"}:
                        raise RuntimeError("Missing/invalid Helly status for K(G)")
                    if row["status_g"] not in {"EXACT", "BETTI_ONLY", "LIMITED"}:
                        raise RuntimeError("Unknown classification status for G")
                    if row["status_kg"] not in {"EXACT", "BETTI_ONLY", "LIMITED"}:
                        raise RuntimeError("Unknown classification status for K(G)")
                    yield row
                    expected_index += 1
                    count += 1
            if count != end - start + 1:
                raise RuntimeError(f"Truncated/overlong batch: {archived}")
        if expected_index != total:
            raise RuntimeError(f"Wrong number of records for order {n}")


def write_report(stage: str, root: Path = ROOT) -> tuple[Path, int]:
    if stage not in STAGES:
        raise ValueError(f"Unsupported stage: {stage}")
    destination = output_path(stage, root)
    temporary = destination.with_suffix(".md.partial")
    total = 0
    selected = 0
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            heading = "orders 1–6" if stage == "through6" else f"order {stage}"
            stream.write(f"# Non-Helly connected graphs — {heading}\n\n")
            stream.write(
                "Includes exactly the original connected graphs with **G not Helly** "
                "(not a filter on K(G)). Indices are zero-based and retain the "
                "source order. Homotopy types mean those of the clique complexes; "
                "an undetermined classification is never presented as an exact type.\n\n"
            )
            stream.write(
                "| Order | Index | graph6 | Homotopy type of G | "
                "Homotopy type of K(G) | K(G) Helly? |\n"
            )
            stream.write("|---:|---:|:---|:---|:---|:---:|\n")
            for row in iter_verified_rows(stage, root):
                total += 1
                if row["helly_g"] != "FALSE":
                    continue
                selected += 1
                helly_kg = {
                    "TRUE": "Yes",
                    "FALSE": "No",
                    "UNKNOWN": "Unknown",
                }[row["helly_kg"]]
                stream.write(
                    f"| {row['order']} | {row['index']} | "
                    f"{safe_graph6(row['graph6'])} | "
                    f"{readable_type(row['status_g'], row['htype_g'])} | "
                    f"{readable_type(row['status_kg'], row['htype_kg'])} | "
                    f"{helly_kg} |\n"
                )
            stream.write(
                f"\n**Total: {selected:,} non-Helly graphs "
                f"among {total:,} connected graphs in this stage.**\n"
            )
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination, selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", required=True, choices=tuple(STAGES),
    )
    args = parser.parse_args()
    report, count = write_report(args.stage)
    print(f"Wrote {report} with {count} non-Helly graphs", flush=True)


if __name__ == "__main__":
    main()
