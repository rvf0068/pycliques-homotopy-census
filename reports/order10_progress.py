"""Read-only progress, disk, and allowance planning for order-10 census."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TOTAL = 11_716_571
BATCH = 100_000
ROOT = Path(__file__).resolve().parents[1]


def progress(root: Path = ROOT) -> dict:
    directory = root / "runs" / "order10" / "order10"
    done_dir = directory / "completed"
    chunk_dir = directory / "chunks"
    partial_dir = directory / "partial"
    completed = 0
    disk_bytes = 0
    for start in range(0, TOTAL, BATCH):
        end = min(start + BATCH, TOTAL) - 1
        stem = f"{start:08d}-{end:08d}"
        marker = done_dir / f"{stem}.done.json"
        archive = chunk_dir / f"{stem}.tsv.gz"
        if not marker.exists():
            break
        if not archive.is_file():
            raise RuntimeError("Completed marker missing archive: " + stem)
        info = json.loads(marker.read_text(encoding="utf-8"))
        if info["rows"] != end - start + 1:
            raise RuntimeError("Invalid completed row count: " + stem)
        completed += info["rows"]
        disk_bytes += archive.stat().st_size
    journals = sorted(partial_dir.glob("*.partial.tsv"))
    if len(journals) > 1:
        raise RuntimeError("Multiple partial journals; investigate the census")
    pending = 0
    if journals:
        journal = journals[0]
        start = int(journal.name.split("-")[0])
        if start != completed:
            raise RuntimeError("Partial journal is not after completed prefix")
        with journal.open("rb") as stream:
            # Only newlines are durably completed records; ignore torn tail.
            line_count = sum(block.count(b"\n") for block in
                             iter(lambda: stream.read(256 * 1024), b""))
        pending = max(0, line_count - 1)
        disk_bytes += journal.stat().st_size
    return {
        "completed_batches": (completed + BATCH - 1) // BATCH,
        "completed_graphs": completed,
        "journal_graphs": pending,
        "durably_recorded_graphs": completed + pending,
        "remaining_graphs": TOTAL - completed - pending,
        "percent": round(100 * (completed + pending) / TOTAL, 4),
        "result_bytes_on_disk": disk_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    state = progress()
    if args.json:
        print(json.dumps(state, indent=2))
    else:
        print(
            f"Order 10: {state['durably_recorded_graphs']:,} / {TOTAL:,} "
            f"({state['percent']:.2f}%) in "
            f"{state['completed_batches']} complete batches and "
            f"{state['journal_graphs']:,} journaled graphs."
        )
        print(
            f"Remaining {state['remaining_graphs']:,}; "
            f"completed/partial output uses "
            f"{state['result_bytes_on_disk']/1024**2:.2f} MiB."
        )


if __name__ == "__main__":
    main()
