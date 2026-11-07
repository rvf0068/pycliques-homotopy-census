"""Reproducible, resumable, evenly spaced pilot for order-10 classifications.

Writes under benchmarks/ (not runs/), so the pilot cannot create an order-10
manifest or modify historical datasets. For a full census, use scripts/run.sh.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from census import classify_with_graph_budget  # noqa: E402
from graph_sources import EXPECTED_COUNTS, graphs6  # noqa: E402

COLUMNS = (
    "index", "graph6", "seconds", "status_g", "status_kg", "comparison",
    "helly_g", "helly_kg", "k_order",
)


def sample_indices(count: int, total: int = EXPECTED_COUNTS[10]) -> list[int]:
    if count < 1 or count > total:
        raise ValueError("samples must be between 1 and the graph count")
    return [(i * total) // count for i in range(count)]


def percentiles(values: list[float], p: float) -> float:
    numbers = sorted(values)
    if not numbers:
        return 0
    # Nearest-rank quantile; robust for small samples.
    return numbers[max(0, math.ceil(p * len(numbers)) - 1)]


def check_environment():
    from pycombtop import graph_morse_certificate  # noqa: F401

    checkout = ROOT / ".deps" / "pycliques-project"
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    recorded = (ROOT / "config" / "pycliques_commit.txt").read_text().strip()
    if revision != recorded:
        raise RuntimeError("Installed dependency differs from the committed pin")
    return revision


def pilot_source_digest(root: Path = ROOT) -> str:
    """Hash all census runner scripts and this pilot, including local edits.

    Git HEAD alone is insufficient: committing results changes HEAD without
    changing the algorithm, while uncommitted edits can change the algorithm.
    The digest is sensitive to the actual source bytes used by the pilot.
    """
    sources = sorted((root / "scripts").glob("*.py"))
    sources += sorted((root / "scripts").glob("*.sh"))
    sources += [
        root / "audits" / "benchmark_order10.py",
        root / "config" / "pycliques_commit.txt",
    ]
    digest = hashlib.sha256()
    for source in sources:
        if not source.is_file():
            raise RuntimeError(f"Missing pilot provenance source: {source}")
        digest.update(source.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(source.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def recover_pilot_rows(output: Path, selected: list[int]) -> dict[int, str]:
    """Discard a torn, unterminated last line and validate all other rows."""
    data = output.read_bytes()
    if data and not data.endswith(b"\n"):
        data = data[: data.rfind(b"\n") + 1]
        output.write_bytes(data)
    if not data:
        return {}
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter="\t")
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise RuntimeError("Pilot CSV column mismatch")
        done = {}
        for row in reader:
            if not row or any(row.get(key) in (None, "") for key in COLUMNS):
                raise RuntimeError("Incomplete newline-terminated pilot CSV row")
            idx = int(row["index"])
            if len(done) >= len(selected) or idx != selected[len(done)]:
                raise RuntimeError("Pilot rows are not a contiguous sampled prefix")
            float(row["seconds"])
            done[idx] = row["graph6"]
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise RuntimeError("Malformed pilot CSV; check sample provenance") from exc
    return done


def analyze(csv_path: Path, planned: int, total: int) -> dict:
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    times = [float(row["seconds"]) for row in rows]
    def count(field, value):
        return sum(row[field] == value for row in rows)
    return {
        "requested_samples": planned,
        "completed_samples": len(rows),
        "total_order10_graphs": total,
        "mean_seconds": statistics.mean(times) if times else 0,
        "median_seconds": statistics.median(times) if times else 0,
        "p90_seconds": percentiles(times, .90),
        "p99_seconds": percentiles(times, .99),
        "worst_seconds": max(times, default=0),
        "projected_full_run_days_single_worker": (
            statistics.mean(times) * total / 86400 if times else None
        ),
        "unresolved": count("comparison", "UNRESOLVED"),
        "limited_g": count("status_g", "LIMITED"),
        "limited_kg": count("status_kg", "LIMITED"),
        "distinct": count("comparison", "DISTINCT"),
        "unknown_helly_g": count("helly_g", "UNKNOWN"),
    }


def pilot(
    output: Path,
    *,
    samples: int = 120,
    max_graph_seconds: float = 120,
    max_run_hours: float = 1,
    flush_every: int = 1,
) -> dict:
    if (
        max_graph_seconds <= 0 or not math.isfinite(max_graph_seconds)
        or max_run_hours <= 0 or not math.isfinite(max_run_hours)
        or flush_every <= 0
    ):
        raise ValueError("Positive finite budgets and flush_every are required")
    revision = check_environment()
    total = EXPECTED_COUNTS[10]
    selected = sample_indices(samples, total)
    wanted = set(selected)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = output.with_suffix(".meta.json")
    summary = output.with_suffix(".summary.json")
    settings = {
        "samples": samples, "max_graph_seconds": max_graph_seconds,
        "upstream_revision": revision,
        "pilot_source_sha256": pilot_source_digest(),
        "python_version": sys.version.split()[0],
        "max_ht_vertices": 64, "max_ht_simplices": 25000,
        "max_k_vertices": 128, "max_k_edges": 5000,
    }
    if metadata.exists():
        if json.loads(metadata.read_text()) != settings:
            raise RuntimeError("Pilot settings changed; choose a different output")
    elif output.exists():
        raise RuntimeError("Existing pilot CSV lacks metadata")
    else:
        metadata.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n")

    done = recover_pilot_rows(output, selected) if output.exists() else {}

    limits = {
        "max_k_vertices": 128, "max_k_edges": 5000,
        "max_ht_vertices": 64, "max_ht_simplices": 25000,
        "max_homotopy_seconds": 0, "max_graph_seconds": max_graph_seconds,
        "flush_every": flush_every,
    }
    deadline = time.monotonic() + max_run_hours * 3600
    observed = 0
    with output.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, delimiter="\t",
                                lineterminator="\n")
        if output.stat().st_size == 0:
            writer.writeheader()
        for idx, graph6 in enumerate(graphs6(10)):
            if idx not in wanted:
                continue
            observed += 1
            if idx in done:
                if done[idx] != graph6:
                    raise RuntimeError(f"Pilot graph6 changed at index {idx}")
                continue
            if time.monotonic() >= deadline:
                print("Pilot paused at session budget; resume with same settings")
                break
            start = time.perf_counter()
            result = classify_with_graph_budget(graph6, 10, idx, limits)
            elapsed = time.perf_counter() - start
            writer.writerow({
                "index": idx, "graph6": graph6, "seconds": f"{elapsed:.6f}",
                **{key: result[key] for key in (
                    "status_g", "status_kg", "comparison",
                    "helly_g", "helly_kg", "k_order",
                )},
            })
            stream.flush()
            os.fsync(stream.fileno())
            print(f"pilot {idx:,}: {elapsed:.2f}s {result['comparison']}", flush=True)
        else:
            if observed != len(selected):
                raise RuntimeError("McKay source incomplete during pilot")
    stats = analyze(output, samples, total)
    stats["upstream_revision"] = revision
    stats["note"] = (
        "Sample-based single-process projection, not a runtime guarantee. "
        "Soft signal timers can be delayed by C code."
    )
    temp = summary.with_suffix(".json.tmp")
    temp.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    os.replace(temp, summary)
    print(f"Pilot results: {output}; summary: {summary}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=120)
    parser.add_argument("--max-graph-seconds", type=float, default=120)
    parser.add_argument("--max-run-hours", type=float, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "order10_pilot.tsv")
    args = parser.parse_args()
    pilot(
        args.output, samples=args.samples,
        max_graph_seconds=args.max_graph_seconds,
        max_run_hours=args.max_run_hours,
    )


if __name__ == "__main__":
    main()
