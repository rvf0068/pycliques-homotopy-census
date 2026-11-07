"""Reproducible, checkpointed one-pass homotopy and Helly census.

A homology obstruction under the hypothesis that K(G) is clique-Helly
halts the run. Betti-only verdicts are never called homotopy types.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import gzip
import hashlib
import io
import json
import math
import os
import random
import signal
import time
from pathlib import Path

import networkx as nx

from graph_sources import EXPECTED_COUNTS, graph_from_string, graphs6
from provenance import ROOT, check_manifest, manifest, sha256

COLUMNS = (
    "order", "index", "graph6", "helly_g", "helly_kg", "k_order",
    "status_g", "htype_g", "betti_g", "reason_g",
    "status_kg", "htype_kg", "betti_kg", "reason_kg", "comparison",
)
COUNTEREXAMPLE_EXIT = 42


class _GraphTimeLimit(BaseException):
    """End one graph cleanly after its whole-graph wall-clock budget."""


class _HomotopyTimeLimit(BaseException):
    """Soft Linux/Codespaces timeout of one homotopy classification."""


@contextmanager
def homotopy_time_limit(seconds: float):
    """Temporarily bound an individual expensive homotopy computation.

    The census runs single-threaded in Linux Codespaces. The timer is
    restored unconditionally, even when pycombtop raises an exception.
    A disabled (zero) budget leaves the classifier fully unrestricted.
    """
    if seconds <= 0:
        yield
        return
    if not hasattr(signal, "setitimer"):
        raise RuntimeError("Homotopy time limits require POSIX signal timers")

    def alarm(_signum, _frame):
        raise _HomotopyTimeLimit()

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, alarm)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


@contextmanager
def graph_time_limit(seconds: float):
    """Apply a soft wall-clock limit to the entire graph classification.

    Do not nest with homotopy_time_limit: the same POSIX timer is shared.
    Signal delivery in long C calls can be delayed, so this is not a hard
    real-time guarantee.
    """
    if seconds <= 0:
        yield
        return
    if not hasattr(signal, "setitimer"):
        raise RuntimeError("Graph wall-time budgets require POSIX signal timers")

    def alarm(_signum, _frame):
        raise _GraphTimeLimit()

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, alarm)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def stage_orders(stage: str) -> list[int]:
    if stage == "through6":
        return list(range(1, 7))
    if stage in {"7", "8", "9", "10"}:
        return [int(stage)]
    raise ValueError(f"Unknown stage: {stage}")


def batch_size(n: int) -> int:
    return 100000 if n == 10 else 10000


def deterministic_seed(g6: str, tag: str) -> int:
    return int.from_bytes(
        hashlib.sha256((g6 + "\0" + tag).encode("ascii")).digest()[:8], "big"
    )


def homotopy(graph: nx.Graph, g6: str, tag: str, limits: dict) -> dict:
    """Use the pinned pycombtop classifier, preserving its exactness flag."""
    from pycombtop.homotopy_type import homotopy_type_with_verdict

    # Dong's matching shuffles vertices. This makes retries reproducible.
    random.seed(deterministic_seed(g6, tag))
    seconds = float(limits.get("max_homotopy_seconds", 0))
    try:
        with homotopy_time_limit(seconds):
            verdict = homotopy_type_with_verdict(
                graph,
                max_vertices=limits["max_ht_vertices"],
                max_simplices=limits["max_ht_simplices"],
            )
    except _HomotopyTimeLimit:
        return unavailable(
            f"Homotopy classifier exceeded {seconds:g} seconds"
        )
    if verdict.is_limited:
        return {
            "status": "LIMITED", "htype": "UNKNOWN", "betti": "UNKNOWN",
            "reason": " ".join(verdict.reason.split()),
        }
    spheres = {
        int(k): int(value)
        for k, value in verdict.wedge.spheres.items()
        if value
    }
    betti = ";".join(f"{k}:{spheres[k]}" for k in sorted(spheres)) or "0"
    exact = bool(verdict.is_exact)
    return {
        "status": "EXACT" if exact else "BETTI_ONLY",
        "htype": betti if exact else "UNKNOWN",
        "betti": betti,
        "reason": " ".join(verdict.reason.split()),
    }


def unavailable(reason: str) -> dict:
    return {
        "status": "LIMITED", "htype": "UNKNOWN",
        "betti": "UNKNOWN", "reason": reason,
    }


def comparison(a: dict, b: dict) -> str:
    """Only certified wedges establish equivalence; homology detects failures."""
    if a["betti"] != "UNKNOWN" and b["betti"] != "UNKNOWN":
        if a["betti"] != b["betti"]:
            return "DISTINCT"
        if a["status"] == "EXACT" and b["status"] == "EXACT":
            return "EQUIVALENT"
    return "UNRESOLVED"


def graph_timeout_row(g6: str, n: int, index: int, seconds: float) -> dict:
    """Lossless index entry when a whole-graph budget expires early."""
    reason = f"Whole-graph wall-time budget of {seconds:g} seconds exceeded"
    return {
        "order": n, "index": index, "graph6": g6,
        "helly_g": "UNKNOWN", "helly_kg": "UNKNOWN", "k_order": "UNKNOWN",
        "status_g": "LIMITED", "htype_g": "UNKNOWN", "betti_g": "UNKNOWN",
        "reason_g": reason,
        "status_kg": "LIMITED", "htype_kg": "UNKNOWN", "betti_kg": "UNKNOWN",
        "reason_kg": reason,
        "comparison": "UNRESOLVED",
    }


def classify(
    g6: str, n: int, index: int, limits: dict, progress: dict | None = None,
) -> dict:
    """Classify a connected graph, optionally preserving completed steps.

    A mutable progress row lets the outer wall timer preserve successful
    G and Helly calculations when a later K(G) calculation times out.
    """
    from pycliques import clique_graph
    from pycliques.helly import is_clique_helly

    row = progress if progress is not None else {}
    row.update(graph_timeout_row(g6, n, index, limits.get("max_graph_seconds", 0)))
    g = graph_from_string(g6)
    if len(g) != n or not nx.is_connected(g):
        raise RuntimeError(
            f"Source violates connected graph hypothesis: order={n}, index={index}"
        )
    hg = bool(is_clique_helly(g))
    row["helly_g"] = str(hg).upper()
    vg = homotopy(g, g6, "G", limits)
    row.update({
        "status_g": vg["status"], "htype_g": vg["htype"],
        "betti_g": vg["betti"], "reason_g": vg["reason"],
    })
    kg = clique_graph(
        g, bound=limits["max_k_vertices"], max_edges=limits["max_k_edges"]
    )
    if kg is None:
        vk = unavailable("K(G) exceeded clique-count or edge limit")
        hk, k_order = "UNKNOWN", "UNKNOWN"
    else:
        k_order = len(kg)
        row["k_order"] = k_order
        hk = str(bool(is_clique_helly(kg))).upper()
        row["helly_kg"] = hk
        if hg and hk != "TRUE":
            raise RuntimeError("Clique-Helly preservation theorem violated")
        if hg and vg["status"] == "EXACT":
            # Prisner's theorem transfers ONLY exact types when G is Helly.
            vk = {
                **vg,
                "reason": (
                    "Prisner clique-Helly homotopy equivalence; "
                    "transferred exact type of G. Original: " + vg["reason"]
                ),
            }
        else:
            vk = homotopy(kg, g6, "K(G)", limits)

    row.update({
        "helly_kg": hk, "k_order": k_order,
        "status_kg": vk["status"], "htype_kg": vk["htype"],
        "betti_kg": vk["betti"], "reason_kg": vk["reason"],
        "comparison": comparison(vg, vk),
    })
    if row["helly_g"] == "TRUE" and row["helly_kg"] == "FALSE":
        raise RuntimeError("Helly preservation theorem violated; abort")
    return row


def classify_with_graph_budget(g6: str, n: int, index: int, limits: dict) -> dict:
    """Apply one timer to G, K(G), both Helly tests, and both homotopy tests.

    Unlike a per-homotopy limit, this also accounts for clique construction.
    If interrupted, keep any exact subresult already completed.
    """
    seconds = float(limits.get("max_graph_seconds", 0))
    if seconds <= 0:
        return classify(g6, n, index, limits)
    local = dict(limits)
    local["max_homotopy_seconds"] = 0  # avoid nested SIGALRM timers
    row = graph_timeout_row(g6, n, index, seconds)
    try:
        with graph_time_limit(seconds):
            return classify(g6, n, index, local, progress=row)
    except _GraphTimeLimit:
        return row


def witness_if_confirmed(row: dict, limits: dict) -> dict | None:
    """Reconstruct and independently check unequal rational Betti vectors.

    The initial homotopy verdict is not sufficient for publication of a
    purported counterexample. Independently recompute Helly and rational
    homology from the original graph6 before writing the stop certificate.
    """
    if row["helly_kg"] != "TRUE" or row["comparison"] != "DISTINCT":
        return None
    n, index, g6 = int(row["order"]), int(row["index"]), row["graph6"]
    again = classify(g6, n, index, limits)
    if again["helly_kg"] != "TRUE" or again["comparison"] != "DISTINCT":
        raise RuntimeError("Potential counterexample was not reproducible")
    if (row["betti_g"], row["betti_kg"]) != (
        again["betti_g"], again["betti_kg"]
    ):
        raise RuntimeError("Counterexample candidate changed homology verdict")

    from pycliques import clique_graph
    from pycliques.helly import is_clique_helly
    from pycombtop.homotopy_type import betti_numbers_graph

    g = graph_from_string(g6)
    k = clique_graph(g)
    if k is None or not is_clique_helly(k):
        raise RuntimeError("Witness failed independent clique-Helly verification")
    actual_g = list(betti_numbers_graph(g))
    actual_k = list(betti_numbers_graph(k))
    while actual_g and actual_g[-1] == 0:
        actual_g.pop()
    while actual_k and actual_k[-1] == 0:
        actual_k.pop()
    if actual_g == actual_k:
        raise RuntimeError("Witness failed independent Betti-number verification")
    return {
        "status": "COUNTEREXAMPLE_CANDIDATE_VERIFIED_BY_HOMOLOGY",
        "meaning": "Delta(G), Delta(K(G)) have different reduced Betti numbers",
        "order": n, "index": index, "graph6": g6,
        "helly_g": row["helly_g"], "helly_kg": row["helly_kg"],
        "reduced_betti_g": actual_g, "reduced_betti_kg": actual_k,
        "census_row": row,
        "note": "Independently recheck before making a publication claim",
    }


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def paths(folder: Path, start: int, end: int) -> tuple[Path, Path, Path]:
    stem = f"{start:08d}-{end:08d}"
    return (
        folder / "chunks" / (stem + ".tsv.gz"),
        folder / "partial" / (stem + ".partial.tsv"),
        folder / "completed" / (stem + ".done.json"),
    )


def read_partial(path: Path, expected_start: int) -> list[str]:
    """Recover an fsynced journal, discarding only a torn final line."""
    if not path.is_file():
        return []
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        data = data[:data.rfind(b"\n") + 1]
        path.write_bytes(data)
    if not data:
        return []
    if not data.startswith(("\t".join(COLUMNS) + "\n").encode("ascii")):
        raise RuntimeError(f"Checkpoint header mismatch: {path}")
    try:
        records = list(
            csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter="\t")
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise RuntimeError(f"Malformed checkpoint: {path}") from exc
    for offset, row in enumerate(records):
        if row.get("index") is None or int(row["index"]) != expected_start + offset:
            raise RuntimeError(f"Wrong partial index in {path}")
        if any(row.get(field) is None for field in COLUMNS):
            raise RuntimeError(f"Malformed partial row in {path}")
    return [row["graph6"] for row in records]


def write_complete(journal: Path, gz: Path, done: Path, count: int) -> None:
    """Atomically commit a deterministic gzip batch with a checksum marker."""
    tmp = gz.with_suffix(".gz.tmp")
    with tmp.open("wb") as output:
        with gzip.GzipFile(fileobj=output, filename="", mode="wb", mtime=0) as zipped:
            with journal.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    zipped.write(block)
    os.replace(tmp, gz)
    atomic_json(done, {"sha256": sha256(gz), "rows": count})
    journal.unlink()


def check_completed(gz: Path, done: Path, count: int) -> bool:
    if not done.is_file():
        return False
    state = json.loads(done.read_text())
    if not gz.is_file() or state != {"sha256": sha256(gz), "rows": count}:
        raise RuntimeError(f"Completed batch integrity failure: {gz}")
    return True


def run_order(
    n: int, run_dir: Path, limits: dict, *, deadline: float | None = None,
    progress_every: int = 10000,
) -> bool:
    folder = run_dir / f"order{n}"
    for name in ("chunks", "partial", "completed"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    total, batch = EXPECTED_COUNTS[n], batch_size(n)
    current_start = -1
    skipped = False
    completed_prefix: list[str] = []
    handle = None
    writer = None
    written = 0
    observed = 0
    journal = gz = done = None
    prev_end = -1

    for idx, g6 in enumerate(graphs6(n)):
        if idx >= total:
            raise RuntimeError(f"Order {n} contains extra source graphs")
        start = (idx // batch) * batch
        end = min(start + batch, total) - 1
        if start != current_start:
            if current_start >= 0 and not skipped:
                assert handle is not None and journal is not None
                handle.flush()
                os.fsync(handle.fileno())
                handle.close()
                assert gz is not None and done is not None
                write_complete(journal, gz, done, prev_end - current_start + 1)
            current_start, prev_end = start, end
            gz, journal, done = paths(folder, start, end)
            skipped = check_completed(gz, done, end - start + 1)
            if skipped:
                # Crash between writing .done and unlinking the journal is safe.
                journal.unlink(missing_ok=True)
                print(f"order {n} indices {start}-{end}: completed batch", flush=True)
            else:
                completed_prefix = read_partial(journal, start)
                written = len(completed_prefix)
                if written > end - start + 1:
                    raise RuntimeError(f"Excess partial rows: {journal}")
                if not journal.exists() or journal.stat().st_size == 0:
                    with journal.open("w", encoding="utf-8", newline="") as output:
                        output.write("\t".join(COLUMNS) + "\n")
                handle = journal.open("a", encoding="utf-8", newline="")
                writer = csv.DictWriter(
                    handle, delimiter="\t", fieldnames=COLUMNS, lineterminator="\n"
                )
                print(
                    f"order {n} indices {start}-{end}: resume {written} records",
                    flush=True,
                )
        observed += 1
        if skipped:
            continue
        offset = idx - start
        if offset < written:
            if completed_prefix[offset] != g6:
                raise RuntimeError(
                    f"Source/index mismatch on resumed order {n}, index {idx}"
                )
            continue
        if deadline is not None and time.monotonic() >= deadline:
            assert handle is not None
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            print(
                f"Order {n} paused at index {idx}; partial journal fsynced. "
                "Resume with the same classification limits.",
                flush=True,
            )
            return False
        row = classify_with_graph_budget(g6, n, idx, limits)
        assert writer is not None and handle is not None
        writer.writerow(row)
        if (offset + 1) % limits["flush_every"] == 0:
            handle.flush()
            os.fsync(handle.fileno())

        if progress_every and (idx + 1) % progress_every == 0:
            print(f"order {n}: processed {idx + 1:,} of {total:,} graphs", flush=True)
        if row["helly_kg"] == "TRUE" and row["comparison"] == "DISTINCT":
            handle.flush()
            os.fsync(handle.fileno())
            witness = witness_if_confirmed(row, limits)
            if witness is not None:
                atomic_json(run_dir / "STOP_COUNTEREXAMPLE.json", witness)
                handle.close()
                raise SystemExit(COUNTEREXAMPLE_EXIT)
        if row["comparison"] == "DISTINCT" and row["helly_g"] == "TRUE":
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            raise RuntimeError(
                "Theorem-check failure: G is Helly but Betti numbers differ"
            )

    if observed != total:
        raise RuntimeError(f"Order {n}: expected {total}, found {observed}")
    if current_start >= 0 and not skipped:
        assert handle is not None and journal is not None
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        assert gz is not None and done is not None
        write_complete(journal, gz, done, prev_end - current_start + 1)
    print(f"Order {n} complete: {observed} connected graphs", flush=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", required=True, choices=("through6", "7", "8", "9", "10")
    )
    parser.add_argument("--max-k-vertices", type=int, default=128)
    parser.add_argument("--max-k-edges", type=int, default=5000)
    parser.add_argument("--max-ht-vertices", type=int, default=64)
    parser.add_argument("--max-ht-simplices", type=int, default=25000)
    parser.add_argument("--flush-every", type=int, default=100)
    parser.add_argument(
        "--max-homotopy-seconds", type=float, default=0,
        help="Optional POSIX wall-clock limit per homotopy calculation; 0 disables",
    )
    parser.add_argument(
        "--max-graph-seconds", type=float, default=0,
        help="Soft wall-clock budget for all work on one graph; 0 disables",
    )
    parser.add_argument(
        "--max-run-hours", type=float, default=0,
        help="Gracefully pause after this many session hours; 0 disables. "
             "May exceed by one graph. May be changed when resuming.",
    )
    parser.add_argument(
        "--progress-every", type=int, default=10000,
        help="Print progress after this many source graphs (0 disables)",
    )
    args = parser.parse_args()
    limits = {
        key: getattr(args, key)
        for key in (
            "max_k_vertices", "max_k_edges", "max_ht_vertices",
            "max_ht_simplices", "flush_every", "max_homotopy_seconds",
            "max_graph_seconds",
        )
    }
    if any(
        limits[key] <= 0 for key in (
            "max_k_vertices", "max_k_edges", "max_ht_vertices",
            "max_ht_simplices", "flush_every",
        )
    ) or (
        limits["max_homotopy_seconds"] < 0
        or not math.isfinite(limits["max_homotopy_seconds"])
        or limits["max_graph_seconds"] < 0
        or not math.isfinite(limits["max_graph_seconds"])
        or args.max_run_hours < 0
        or not math.isfinite(args.max_run_hours)
        or args.progress_every < 0
    ):
        parser.error("Resource limits must be positive; optional budgets >= 0")
    if limits["max_graph_seconds"] > 0 and limits["max_homotopy_seconds"] > 0:
        parser.error(
            "Choose either --max-graph-seconds or --max-homotopy-seconds, "
            "not both (they share a POSIX timer)"
        )
    orders = stage_orders(args.stage)
    run_dir = ROOT / "runs" / (
        "through6" if args.stage == "through6" else f"order{args.stage}"
    )
    if (run_dir / "STOP_COUNTEREXAMPLE.json").exists():
        raise SystemExit(
            "Counterexample witness exists; no automatic continuation permitted"
        )
    check_manifest(run_dir, manifest(orders, limits))
    deadline = (
        time.monotonic() + args.max_run_hours * 3600
        if args.max_run_hours else None
    )
    for n in orders:
        if not run_order(
            n, run_dir, limits, deadline=deadline,
            progress_every=args.progress_every,
        ):
            print("Session paused cleanly; full-stage validation not yet possible")
            return
    print("All requested orders completed; validate with scripts/validate.py")


if __name__ == "__main__":
    main()
