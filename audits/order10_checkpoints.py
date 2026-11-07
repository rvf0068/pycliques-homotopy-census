"""Safely store and recover order-10 partial journals as small gzip snapshots.

This tool lives outside scripts/ so existing provenance-hashed census manifests
remain valid. It never changes the classification settings, source order or
the authoritative completed census archives.

Usage:
  .venv/bin/python audits/order10_checkpoints.py snapshot
  .venv/bin/python audits/order10_checkpoints.py restore
  .venv/bin/python audits/order10_checkpoints.py status
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from census import COLUMNS  # noqa: E402

BATCH_SIZE = 100_000
TOTAL = 11_716_571
PARTIAL_NAME = re.compile(r"^(\d{8})-(\d{8})\.partial\.tsv$")
SNAPSHOT_NAME = re.compile(r"^(\d{8})-(\d{8})\.snapshot\.json$")
COMPRESSED_WARNING_LIMIT = 50 * 1024 * 1024


def order_dir(root: Path) -> Path:
    return root / "runs" / "order10" / "order10"


def snapshot_dir(root: Path) -> Path:
    return root / "checkpoints" / "order10"


def checksum(path: Path) -> str:
    hash_ = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hash_.update(block)
    return hash_.hexdigest()


def manifest_checksum(root: Path) -> str:
    manifest = root / "runs" / "order10" / "manifest.json"
    if not manifest.is_file():
        raise RuntimeError("Order-10 manifest is missing; do not snapshot this run")
    return checksum(manifest)


def bounds(stem: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{8})-(\d{8})", stem)
    if match is None:
        raise RuntimeError(f"Invalid order-10 checkpoint stem: {stem}")
    start, end = (int(s) for s in match.groups())
    if start >= TOTAL or start % BATCH_SIZE or end != min(start + BATCH_SIZE, TOTAL) - 1:
        raise RuntimeError(f"Unexpected original source-index range: {stem}")
    return start, end


def journal_paths(root: Path) -> list[Path]:
    base = order_dir(root) / "partial"
    if not base.is_dir():
        return []
    paths = sorted(base.glob("*.partial.tsv"))
    for path in paths:
        match = PARTIAL_NAME.fullmatch(path.name)
        if not match:
            raise RuntimeError(f"Unexpected partial journal filename: {path}")
        bounds(path.name.removesuffix(".partial.tsv"))
    if len(paths) > 1:
        raise RuntimeError("Multiple order-10 partial journals; inspect before archiving")
    return paths


def inspect_journal(path: Path, stem: str) -> int:
    """Require a complete sequential TSV prefix, without modifying it."""
    start, end = bounds(stem)
    if not path.is_file():
        raise RuntimeError(f"Journal does not exist: {path}")
    if path.stat().st_size:
        with path.open("rb") as source:
            source.seek(-1, os.SEEK_END)
            if source.read(1) != b"\n":
                raise RuntimeError(
                    "Journal has a torn last line. Resume the census runner "
                    "once to apply its existing torn-line recovery before snapshotting."
                )
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise RuntimeError("Journal schema differs from the original census")
        count = 0
        for row in reader:
            if (
                count > end - start
                or row.get("order") != "10"
                or row.get("index") != str(start + count)
                or not row.get("graph6")
                or any(row.get(field) is None for field in COLUMNS)
            ):
                raise RuntimeError(f"Malformed journal record {start + count}")
            count += 1
    return count


def verify_snapshot(root: Path, meta_path: Path) -> tuple[dict, Path]:
    info = json.loads(meta_path.read_text(encoding="utf-8"))
    stem = meta_path.name.removesuffix(".snapshot.json")
    if SNAPSHOT_NAME.fullmatch(meta_path.name) is None:
        raise RuntimeError(f"Invalid snapshot metadata name: {meta_path}")
    start, end = bounds(stem)
    if (
        info.get("schema") != 1
        or info.get("stem") != stem
        or info.get("start") != start
        or info.get("end") != end
        or info.get("manifest_sha256") != manifest_checksum(root)
        or not isinstance(info.get("rows"), int)
        or not (0 <= info["rows"] <= end - start + 1)
        or not isinstance(info.get("bytes"), int)
        or info["bytes"] <= 0
    ):
        raise RuntimeError(f"Snapshot manifest/count does not match current run: {stem}")
    archive = snapshot_dir(root) / (stem + ".partial.tsv.gz")
    if not archive.is_file() or checksum(archive) != info.get("gzip_sha256"):
        raise RuntimeError(f"Missing or corrupted compressed snapshot: {stem}")
    return info, archive


def ensure_git_tracks_backup(root: Path, files: list[Path], old_journal: Path) -> None:
    """Stage backup first, then untrack the raw TSV without deleting it locally."""
    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=check,
            capture_output=True, text=True,
        )

    if git("rev-parse", "--show-toplevel", check=False).returncode != 0:
        raise RuntimeError("Git repository unavailable; checkpoint exists but is not staged")
    relative = [p.relative_to(root).as_posix() for p in files]
    git("add", "--", *relative)
    rel_raw = old_journal.relative_to(root).as_posix()
    if git("ls-files", "--error-unmatch", "--", rel_raw, check=False).returncode == 0:
        git("rm", "--cached", "--", rel_raw)
        print(
            "Untracked large raw journal in Git index; the local TSV remains intact.",
            flush=True,
        )


def verified_completed_batch(root: Path, stem: str) -> bool:
    """Trust a completed batch only when its gzip and marker agree."""
    start, end = bounds(stem)
    marker = order_dir(root) / "completed" / (stem + ".done.json")
    archive = order_dir(root) / "chunks" / (stem + ".tsv.gz")
    if not marker.is_file():
        return False
    if not archive.is_file():
        raise RuntimeError(f"Completion marker without archive: {stem}")
    expected = {"rows": end - start + 1, "sha256": checksum(archive)}
    if json.loads(marker.read_text(encoding="utf-8")) != expected:
        raise RuntimeError(f"Invalid completed-batch certificate: {stem}")
    return True


def prune_completed(root: Path, *, stage_git: bool = True) -> int:
    """Remove obsolete snapshots only when a completed census batch is verified."""
    destination = snapshot_dir(root)
    if not destination.is_dir():
        return 0
    removed = []
    for meta in sorted(destination.glob("*.snapshot.json")):
        stem = meta.name.removesuffix(".snapshot.json")
        if not verified_completed_batch(root, stem):
            continue
        # The completed batch supersedes this obsolete backup, even if the
        # old snapshot itself became corrupted or disappeared. Never block
        # completed work merely because an obsolete cache is damaged.
        compressed = destination / (stem + ".partial.tsv.gz")
        compressed.unlink(missing_ok=True)
        meta.unlink()
        removed.extend([compressed, meta])
    if removed and stage_git:
        relative = [p.relative_to(root).as_posix() for p in removed]
        subprocess.run(["git", "-C", str(root), "add", "-A", "--", *relative],
                       check=True)
    if removed:
        print(f"Removed {len(removed)//2} obsolete snapshots for completed batches")
    return len(removed)//2


def snapshot(root: Path = ROOT, *, stage_git: bool = True) -> dict | None:
    """Snapshot a fsynced journal; never delete the original local data."""
    manifest_hash = manifest_checksum(root)
    partials = journal_paths(root)
    if not partials:
        prune_completed(root, stage_git=stage_git)
        print("No unfinished journal; nothing to snapshot", flush=True)
        return None
    raw = partials[0]
    stem = raw.name.removesuffix(".partial.tsv")
    start, end = bounds(stem)
    if verified_completed_batch(root, stem):
        raise RuntimeError(f"Journal conflicts with a completed batch: {stem}")
    rows = inspect_journal(raw, stem)
    original_sha = checksum(raw)
    size = raw.stat().st_size
    dest = snapshot_dir(root)
    dest.mkdir(parents=True, exist_ok=True)
    gz = dest / (stem + ".partial.tsv.gz")
    meta = dest / (stem + ".snapshot.json")
    temp = gz.with_suffix(gz.suffix + ".tmp")
    try:
        with temp.open("wb") as compressed:
            with gzip.GzipFile(
                fileobj=compressed, filename="", mode="wb", mtime=0
            ) as encoder:
                with raw.open("rb") as original:
                    for block in iter(lambda: original.read(1024 * 1024), b""):
                        encoder.write(block)
            compressed.flush()
            os.fsync(compressed.fileno())
        if temp.stat().st_size >= COMPRESSED_WARNING_LIMIT:
            raise RuntimeError(
                "Compressed snapshot is >=50 MiB; do not stage this Git file"
            )
        # Do not accept a concurrent writer or a truncated gzip stream.
        if raw.stat().st_size != size or checksum(raw) != original_sha:
            raise RuntimeError("Journal changed while being snapshot; stop the runner")
        digest = hashlib.sha256()
        restored_bytes = 0
        with gzip.open(temp, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
                restored_bytes += len(block)
        if restored_bytes != size or digest.hexdigest() != original_sha:
            raise RuntimeError("Compressed snapshot failed round-trip verification")
        os.replace(temp, gz)
    finally:
        temp.unlink(missing_ok=True)
    info = {
        "schema": 1, "stem": stem, "start": start, "end": end,
        "rows": rows, "bytes": size,
        "original_sha256": original_sha,
        "gzip_sha256": checksum(gz),
        "manifest_sha256": manifest_hash,
    }
    meta_temp = meta.with_suffix(meta.suffix + ".tmp")
    try:
        with meta_temp.open("w", encoding="utf-8") as out:
            json.dump(info, out, indent=2, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(meta_temp, meta)
    finally:
        meta_temp.unlink(missing_ok=True)
    verify_snapshot(root, meta)
    if stage_git:
        ensure_git_tracks_backup(root, [gz, meta], raw)
    prune_completed(root, stage_git=stage_git)
    print(
        f"Snapshot {stem}: {rows:,} graphs, "
        f"{size/1024**2:.1f} MiB raw -> {gz.stat().st_size/1024**2:.2f} MiB gzip",
        flush=True,
    )
    return info


def restore(root: Path = ROOT) -> int:
    """Recover a missing raw journal from a matching verified gzip snapshot."""
    dest = snapshot_dir(root)
    if not dest.is_dir():
        return 0
    journals = journal_paths(root)
    records = sorted(dest.glob("*.snapshot.json"))
    count = 0
    for meta in records:
        stem = meta.name.removesuffix(".snapshot.json")
        # Do not restore finished work; completed batches are authoritative.
        if verified_completed_batch(root, stem):
            continue
        info, gz = verify_snapshot(root, meta)
        raw = order_dir(root) / "partial" / (stem + ".partial.tsv")
        if raw.exists():
            # Never overwrite local progress. A crash may leave a torn
            # unterminated last line; only census.read_partial() may trim it.
            # Check the snapshot's immutable byte prefix here, without
            # parsing or modifying any trailing local records.
            if raw.stat().st_size < info["bytes"]:
                raise RuntimeError(
                    f"Local journal is older than the compressed snapshot {stem}. "
                    "Preserve both and inspect before resuming."
                )
            digest = hashlib.sha256()
            remaining = info["bytes"]
            with raw.open("rb") as original:
                while remaining:
                    block = original.read(min(1024 * 1024, remaining))
                    if not block:
                        raise RuntimeError(f"Truncated journal prefix: {stem}")
                    digest.update(block)
                    remaining -= len(block)
            if digest.hexdigest() != info["original_sha256"]:
                raise RuntimeError(
                    f"Local journal differs from the saved snapshot {stem}; "
                    "refusing to overwrite either checkpoint."
                )
            print(f"Retaining existing local journal {raw}", flush=True)
            continue
        if journals:
            raise RuntimeError(
                f"Refusing to restore {stem} alongside another partial journal"
            )
        raw.parent.mkdir(parents=True, exist_ok=True)
        temp = raw.with_suffix(raw.suffix + ".tmp")
        try:
            digest = hashlib.sha256()
            size = 0
            with gzip.open(gz, "rb") as source, temp.open("wb") as out:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    out.write(block)
                    digest.update(block)
                    size += len(block)
                out.flush()
                os.fsync(out.fileno())
            if (
                size != info["bytes"]
                or digest.hexdigest() != info["original_sha256"]
                or inspect_journal(temp, stem) != info["rows"]
            ):
                raise RuntimeError(f"Restoration checksum/row count failure: {stem}")
            os.replace(temp, raw)
        finally:
            temp.unlink(missing_ok=True)
        journals = [raw]
        count += 1
        print(f"Restored {info['rows']:,} journaled graphs for batch {stem}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "restore", "status"))
    args = parser.parse_args()
    if args.action == "snapshot":
        snapshot()
    elif args.action == "restore":
        restore()
    else:
        destination = snapshot_dir(ROOT)
        metas = sorted(destination.glob("*.snapshot.json")) if destination.is_dir() else []
        for meta in metas:
            info, archive = verify_snapshot(ROOT, meta)
            print(
                f"{info['stem']}: {info['rows']:,} graphs, "
                f"{archive.stat().st_size/1024**2:.2f} MiB compressed"
            )
        if not metas:
            print("No compressed order-10 snapshots")


if __name__ == "__main__":
    main()
