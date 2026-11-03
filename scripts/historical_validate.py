"""Revalidate old results with their original committed runner and dependency.

Historical Git worktrees stay under ignored .deps/; the active checkout,
current dependency pin and virtual environment are not changed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from versioning import (
    STAGES, historical_runner_revision, read_manifest, stage_directory,
)

ROOT = Path(__file__).resolve().parent.parent


def execute(args: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True,
    ).strip()


def worktree(base: Path, target: Path, revision: str) -> Path:
    """Construct/reuse an exact detached Git revision, never alter base HEAD."""
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        execute([
            "git", "-C", str(base), "worktree", "add",
            "--detach", str(target), revision,
        ])
    if git(target, "rev-parse", "HEAD") != revision:
        raise RuntimeError(f"Wrong historical worktree revision: {target}")
    if git(target, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError(f"Modified historical worktree: {target}")
    return target


def link_directory(source: Path, target: Path) -> None:
    source = source.resolve()
    if not source.is_dir():
        raise RuntimeError(f"Source data directory not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if target.resolve() != source:
            raise RuntimeError(f"Existing symlink points to wrong directory: {target}")
    elif target.exists():
        raise RuntimeError(f"Refusing to overwrite existing directory: {target}")
    else:
        target.symlink_to(source, target_is_directory=True)


def validate(stage: str, root: Path = ROOT) -> None:
    if stage not in STAGES:
        raise ValueError(f"Unsupported stage: {stage}")
    root = root.resolve()
    recorded = read_manifest(root, stage)
    original_runner = historical_runner_revision(root, recorded)
    original_upstream = recorded["monorepo_commit"]
    original_python = recorded["python"]
    print(f"Original census runner: {original_runner}", flush=True)
    print(f"Original pycliques-project: {original_upstream}", flush=True)

    census_copy = worktree(
        root, root / ".deps" / "census-history" / original_runner,
        original_runner,
    )
    current_upstream = root / ".deps" / "pycliques-project"
    if not (current_upstream / ".git").exists():
        raise RuntimeError("Bootstrap pycliques-project first: bash scripts/bootstrap.sh")
    # Reuse the active environment only when its Python patch version agrees
    # with the recorded run; otherwise isolate even the same upstream commit.
    current_python = current_upstream / ".venv" / "bin" / "python"
    current_python_version = (
        subprocess.check_output(
            [str(current_python), "-c", "import sys; print(sys.version.split()[0])"],
            text=True,
        ).strip()
        if current_python.exists()
        else None
    )
    if (
        git(current_upstream, "rev-parse", "HEAD") == original_upstream
        and current_python_version == original_python
    ):
        upstream_copy = current_upstream
    else:
        execute([
            "git", "-C", str(current_upstream), "fetch",
            "--no-tags", "origin", original_upstream,
        ])
        upstream_copy = worktree(
            current_upstream,
            root / ".deps" / "pycliques-history" / original_upstream,
            original_upstream,
        )

    # The original validator expects both paths beneath its own project root.
    # Only the requested stage's result directory is linked to the actual data.
    stage_name = stage_directory(root, stage).name
    link_directory(
        root / "runs" / stage_name, census_copy / "runs" / stage_name,
    )
    link_directory(upstream_copy, census_copy / ".deps" / "pycliques-project")

    # A frozen uv.lock recreates the original dependency environment.
    execute([
        "uv", "sync", "--frozen", "--no-dev", "--python", original_python,
    ], cwd=upstream_copy)
    python = upstream_copy / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"Cannot find historical Python environment: {python}")
    execute([
        str(python), str(census_copy / "scripts" / "validate.py"),
        "--stage", stage,
    ], cwd=census_copy)
    print(f"Successfully validated historical stage {stage}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=tuple(STAGES), required=True)
    args = parser.parse_args()
    try:
        validate(args.stage)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Historical validation failed: {exc}\n")


if __name__ == "__main__":
    main()
