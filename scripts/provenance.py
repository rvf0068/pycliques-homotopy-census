"""Run manifest locks installed upstream code, runner and McKay datasets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import networkx as nx

from graph_sources import data_path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def manifest(orders: list[int], settings: dict) -> dict:
    source = ROOT / ".deps" / "pycliques-project"
    head = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    pin = (ROOT / "config" / "pycliques_commit.txt").read_text().strip()
    if head != pin:
        raise RuntimeError("Upstream checkout does not match pinned commit")
    h = hashlib.sha256()
    source_files = sorted((ROOT / "scripts").glob("*.py"))
    source_files += sorted((ROOT / "scripts").glob("*.sh"))
    source_files += [ROOT / "config" / "pycliques_commit.txt"]
    for file in source_files:
        h.update(str(file.relative_to(ROOT)).encode() + b"\0")
        h.update(file.read_bytes() + b"\0")
    return {
        "schema": 1,
        "orders": orders,
        "settings": settings,
        "source": "NetworkX atlas (1-5); pyg6data McKay connected files (6-10)",
        "indexing": "zero based, unchanged source order",
        "monorepo_commit": head,
        "monorepo_lock_sha256": sha256(source / "uv.lock"),
        "runner_sha256": h.hexdigest(),
        "data_sha256": {
            str(n): sha256(Path(str(data_path(n))))
            for n in orders if n >= 6
        },
        "python": sys.version.split()[0],
        "networkx": nx.__version__,
        "packages": {
            p: metadata.version(p)
            for p in ("pycliques", "pycombtop", "pyg6data", "mogutda")
        },
    }


def check_manifest(run_dir: Path, info: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "manifest.json"
    if path.is_file():
        if json.loads(path.read_text()) != info:
            raise RuntimeError(
                "Run manifest changed; use a new run directory, never mix provenance"
            )
        return
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
    os.replace(temp, path)
