"""Follow-up only for the six order-9 timeout records.

Requires a newly pinned pycliques-project with facet Morse certificates.
Never overwrites the historical runs/order9 census, its summaries, or
its checksummed chunks. Results are recorded as a six-row overlay.
"""

from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import io
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "runs" / "order9"
DEST = ROOT / "runs" / "order9_morse_followup"
EXPECTED = {
    108411: "H?o~f~}",
    145941: "H?~vf~}",
    239843: "HCrbf~}",
    256373: "HEzvf^m",
    256477: "HFzfvz{",
    256483: "HFzf~z{",
}
COLUMNS = (
    "order", "index", "graph6", "helly_g", "helly_kg", "k_order",
    "status_g", "htype_g", "betti_g", "reason_g",
    "status_kg", "htype_kg", "betti_kg", "reason_kg", "comparison",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def historical_rows():
    summary = json.loads((HISTORY / "summary.json").read_text())
    assert len(summary["orders"]) == 1
    counts = summary["orders"][0]["counts"]
    if counts.get("comparison_UNRESOLVED") != len(EXPECTED):
        raise RuntimeError("Historical summary no longer describes six unresolved cases")
    with gzip.open(HISTORY / "unresolved_order9.tsv.gz", "rt") as stream:
        unresolved = list(csv.DictReader(stream, delimiter="\t"))
    actual = {int(row["index"]): row["graph6"] for row in unresolved}
    if actual != EXPECTED or len(unresolved) != len(EXPECTED):
        raise RuntimeError("Historical unresolved list does not match six audited graph6 strings")
    if any(row["status_g"] != "EXACT" or row["status_kg"] != "LIMITED"
           or row["comparison"] != "UNRESOLVED" for row in unresolved):
        raise RuntimeError("Historical timeout statuses changed")
    selected = {}
    starts = sorted({index // 10000 * 10000 for index in EXPECTED})
    for start in starts:
        end = min(start + 9999, 261079)
        stem = f"{start:08d}-{end:08d}"
        archive = HISTORY / "order9" / "chunks" / (stem + ".tsv.gz")
        marker = HISTORY / "order9" / "completed" / (stem + ".done.json")
        state = json.loads(marker.read_text())
        if state != {"sha256": sha256(archive), "rows": end - start + 1}:
            raise RuntimeError("Original census batch checksum mismatch: " + stem)
        with gzip.open(archive, "rt", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if tuple(reader.fieldnames or ()) != COLUMNS:
                raise RuntimeError("Historical row schema changed")
            for row in reader:
                idx = int(row["index"])
                if idx in EXPECTED:
                    if row["graph6"] != EXPECTED[idx]:
                        raise RuntimeError(f"Index/graph6 mismatch for {idx}")
                    selected[idx] = row
    if set(selected) != set(EXPECTED):
        raise RuntimeError("Some historical rows were not found")
    for row in selected.values():
        if row["status_kg"] != "LIMITED" or row["htype_kg"] != "UNKNOWN":
            raise RuntimeError("Original historical row is no longer a timeout")
    return summary, selected


def encode(spheres):
    return ";".join(f"{d}:{n}" for d, n in sorted(spheres.items()) if n) or "0"


def latex(encoded):
    if encoded == "0":
        return "Contractible"
    parts = []
    for pair in encoded.split(";"):
        dim, multiplicity = (int(x) for x in pair.split(":"))
        sphere = f"S^{{{dim}}}"
        parts.append(sphere if multiplicity == 1 else
                     r"\bigvee_{" + str(multiplicity) + "}" + sphere)
    return r"\(" + r"\vee ".join(parts) + r"\)"


def verified_morse_revision(old_pin: str) -> str:
    """Identify the separately installed Morse code, not the census pin.

    The standalone runner exports the checkout path. Reject an execution
    using the original census virtualenv or a mismatched upstream checkout.
    """
    source = os.environ.get("PYCLIQUES_MORSE_CHECKOUT")
    if not source:
        raise RuntimeError(
            "Use: bash audits/run_order9_morse_followup.sh "
            "(the original census pin cannot be updated while a stage "
            "is unvalidated)"
        )
    checkout = Path(source).resolve()
    try:
        revision = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Cannot determine isolated Morse checkout revision") from exc

    if len(revision) != 40 or revision == old_pin:
        raise RuntimeError("The isolated Morse checkout has no newer revision")
    import pycliques
    import pycombtop

    expected = {
        "pycliques": checkout / "packages" / "pycliques" / "src",
        "pycombtop": checkout / "packages" / "pycombtop" / "src",
    }
    for name, module in (("pycliques", pycliques), ("pycombtop", pycombtop)):
        location = Path(module.__file__).resolve()
        if not location.is_relative_to(expected[name].resolve()):
            raise RuntimeError(
                f"{name} is imported from {location}, not from the "
                f"isolated checkout {expected[name]}"
            )
    return revision


def run():
    import networkx as nx
    from pycliques import clique_graph
    from pycliques.helly import is_clique_helly
    from pycombtop.morse_certificates import graph_morse_certificate

    summary, old_rows = historical_rows()
    old_pin = summary["manifest"]["monorepo_commit"]
    new_pin = verified_morse_revision(old_pin)
    updated = []
    for idx, g6 in sorted(EXPECTED.items()):
        original = old_rows[idx]
        graph = nx.from_graph6_bytes(g6.encode("ascii"))
        if len(graph) != 9 or not nx.is_connected(graph):
            raise RuntimeError(f"Invalid connected graph at index {idx}")
        k = clique_graph(graph, bound=128, max_edges=5000)
        if k is None or str(len(k)) != original["k_order"]:
            raise RuntimeError(f"Changed clique graph at index {idx}")
        if str(bool(is_clique_helly(k))).upper() != original["helly_kg"]:
            raise RuntimeError(f"Changed clique-Helly verdict at index {idx}")
        cert = graph_morse_certificate(k)
        if cert is None:
            raise RuntimeError(f"No certified Morse type for index {idx}")
        row = dict(original)
        row["status_kg"] = "EXACT"
        row["htype_kg"] = row["betti_kg"] = encode(cert.spheres)
        row["reason_kg"] = (
            "Verified acyclic facet Morse matching; critical counts "
            + repr(sorted(cert.critical.items()))
            + ("; exact top rational boundary rank and Hurewicz"
               if cert.uses_hurewicz else "; single positive critical dimension")
        )
        row["comparison"] = (
            "EQUIVALENT" if row["htype_g"] == row["htype_kg"]
            else "DISTINCT"
        )
        updated.append(row)
        print(f"{idx}: {row['htype_kg']} ({row['comparison']})", flush=True)

    counts = collections.Counter(summary["orders"][0]["counts"])
    for row in updated:
        previous = old_rows[int(row["index"])]
        for field in ("status_kg", "comparison"):
            counts[field + "_" + previous[field]] -= 1
            counts[field + "_" + row[field]] += 1
    if any(number < 0 for number in counts.values()):
        raise RuntimeError("Invalid aggregate after follow-up")
    overlay = io.StringIO()
    writer = csv.DictWriter(overlay, fieldnames=COLUMNS,
                            delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(updated)
    manifest = {
        "description": "Separate, six-row Morse follow-up; order9 historical files untouched",
        "original_order9_manifest_sha256": sha256(HISTORY / "manifest.json"),
        "original_order9_summary_sha256": sha256(HISTORY / "summary.json"),
        "original_monorepo_commit": old_pin,
        "followup_monorepo_commit": new_pin,
        "resolved_rows": len(updated),
        "revised_counts": dict(sorted(counts.items())),
    }
    markdown = [
        "# Order-9 facet Morse follow-up",
        "",
        "The original completed 261,080-row census is unchanged. This six-row "
        "overlay was calculated with a separately pinned code revision.",
        "",
        "| Index | graph6 | Type of G | Type of K(G) | Comparison |",
        "|---:|:---|:---|:---|:---|",
    ]
    for row in updated:
        markdown.append(
            f"| {row['index']} | <code>{row['graph6']}</code> | "
            f"{latex(row['htype_g'])} | {latex(row['htype_kg'])} | "
            f"{row['comparison']} |"
        )
    markdown.extend([
        "",
        "Remaining unresolved cases: "
        + str(counts.get("comparison_UNRESOLVED", 0)) + ".",
        "",
        "Certificates: verified acyclic matchings, with an exact top rational "
        "boundary-rank check and the Hurewicz attaching-map argument where needed.",
        "",
    ])
    atomic_write(DEST / "resolved_rows.tsv", overlay.getvalue())
    atomic_write(DEST / "summary.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    atomic_write(ROOT / "order9_morse_followup.md", "\n".join(markdown))
    print("Wrote the six-row overlay and a revised aggregate, leaving order9 unchanged")


if __name__ == "__main__":
    run()
