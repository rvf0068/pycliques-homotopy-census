"""Guard dependency updates and identify historical runner commits.

The digest reproduces provenance.manifest(): sorted scripts/*.py, then
scripts/*.sh, then config/pycliques_commit.txt, each with NUL separators.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

STAGES = {
    "through6": (1, 2, 3, 4, 5, 6),
    "7": (7,), "8": (8,), "9": (9,), "10": (10,),
}
COUNTS = {
    1: 1, 2: 1, 3: 2, 4: 6, 5: 21, 6: 112,
    7: 853, 8: 11117, 9: 261080, 10: 11716571,
}


def stage_directory(root: Path, stage: str) -> Path:
    return root / "runs" / ("through6" if stage == "through6" else f"order{stage}")


def read_manifest(root: Path, stage: str) -> dict:
    path = stage_directory(root, stage) / "manifest.json"
    if not path.is_file():
        raise RuntimeError(f"Missing stage manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def committed_runner_sha(root: Path, revision: str) -> tuple[str, str]:
    names = subprocess.check_output([
        "git", "-C", str(root), "ls-tree", "-r", "--name-only",
        revision, "--", "scripts", "config",
    ], text=True).splitlines()
    py = sorted(p for p in names if p.startswith("scripts/")
                and p.count("/") == 1 and p.endswith(".py"))
    sh = sorted(p for p in names if p.startswith("scripts/")
                and p.count("/") == 1 and p.endswith(".sh"))
    pin_path = "config/pycliques_commit.txt"
    if pin_path not in names:
        raise RuntimeError(f"No dependency pin at census revision {revision}")
    digest = hashlib.sha256()
    pin = ""
    for path in [*py, *sh, pin_path]:
        data = subprocess.check_output([
            "git", "-C", str(root), "show", f"{revision}:{path}",
        ])
        digest.update(path.encode("utf-8") + b"\0")
        digest.update(data + b"\0")
        if path == pin_path:
            pin = data.decode("ascii").strip()
    return digest.hexdigest(), pin


def historical_runner_revision(root: Path, run_manifest: dict) -> str:
    """Find the original, committed census scripts matching the manifest."""
    revisions = subprocess.check_output([
        "git", "-C", str(root), "rev-list", "--all", "HEAD",
    ], text=True).splitlines()
    for revision in dict.fromkeys(revisions):
        digest, pin = committed_runner_sha(root, revision)
        if (digest == run_manifest["runner_sha256"]
                and pin == run_manifest["monorepo_commit"]):
            return revision
    raise RuntimeError(
        "The recorded runner is absent from committed Git history. "
        "Fetch full history (git fetch --unshallow, if shallow), or restore "
        "the exact original scripts and dependency pin before updating."
    )


def verify_stage_complete(root: Path, stage: str) -> dict:
    """Require a validated summary and all intact completed batches."""
    directory = stage_directory(root, stage)
    info = read_manifest(root, stage)
    if (directory / "STOP_COUNTEREXAMPLE.json").exists():
        raise RuntimeError(f"Stage {stage} has a counterexample witness; investigate first")
    summary_file = directory / "summary.json"
    if not summary_file.is_file():
        raise RuntimeError(f"Stage {stage} is not yet validated: {summary_file}")
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    orders = STAGES[stage]
    if info.get("orders") != list(orders) or summary.get("manifest") != info:
        raise RuntimeError(f"Stage {stage} validation manifest mismatch")
    rows = summary.get("orders", [])
    if len(rows) != len(orders) or {
        x["order"]: x["counts"]["graphs"] for x in rows
    } != {n: COUNTS[n] for n in orders}:
        raise RuntimeError(f"Stage {stage} validation is incomplete")
    if any(directory.rglob("*.partial.tsv")) or any(directory.rglob("*.tmp")):
        raise RuntimeError(f"Unfinished checkpoint in stage {stage}")
    for n in orders:
        folder = directory / f"order{n}"
        total = COUNTS[n]
        batch = 100000 if n == 10 else 10000
        stems = {
            f"{start:08d}-{min(start + batch, total) - 1:08d}"
            for start in range(0, total, batch)
        }
        actual_done = {
            p.name.removesuffix(".done.json")
            for p in (folder / "completed").glob("*.done.json")
        }
        actual_data = {
            p.name.removesuffix(".tsv.gz")
            for p in (folder / "chunks").glob("*.tsv.gz")
        }
        if actual_done != stems or actual_data != stems:
            raise RuntimeError(f"Missing/extra completed batches for order {n}")
        for start in range(0, total, batch):
            end = min(start + batch, total) - 1
            stem = f"{start:08d}-{end:08d}"
            archive = folder / "chunks" / f"{stem}.tsv.gz"
            marker = folder / "completed" / f"{stem}.done.json"
            h = hashlib.sha256()
            with archive.open("rb") as stream:
                for data in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(data)
            if json.loads(marker.read_text(encoding="utf-8")) != {
                "sha256": h.hexdigest(), "rows": end - start + 1,
            }:
                raise RuntimeError(f"Corrupt batch {archive}")
    revision = historical_runner_revision(root, info)
    return {
        "stage": stage,
        "runner": revision,
        "upstream": info["monorepo_commit"],
    }


def check_all_stage_completions(root: Path) -> list[dict]:
    runs = root / "runs"
    if not runs.exists():
        return []
    recognized = {stage_directory(root, stage).name: stage for stage in STAGES}
    checks = []
    for path in sorted(runs.iterdir()):
        if path.is_file() and path.name == ".gitkeep":
            continue
        if not path.is_dir() or path.name not in recognized:
            raise RuntimeError(f"Unexpected run artifact: {path}")
        checks.append(verify_stage_complete(root, recognized[path.name]))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--stage", choices=tuple(STAGES))
    options = parser.parse_args()
    try:
        root = options.root.resolve()
        checks = ([verify_stage_complete(root, options.stage)]
                  if options.stage else check_all_stage_completions(root))
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Dependency update refused: {exc}\n")
    for check in checks:
        print(f"Stage {check['stage']} complete: "
              f"runner {check['runner'][:12]}, upstream {check['upstream'][:12]}")
    print("All started stages are complete and reproducible")


if __name__ == "__main__":
    main()
