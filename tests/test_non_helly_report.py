"""Tests for root-level non-Helly reports; independent of upstream datasets."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "reports"))

import non_helly


def write_completed_batch(
    root: Path, stage: str, n: int, entries: list[dict],
) -> Path:
    run_dir = root / "runs" / f"order{stage}"
    folder = run_dir / f"order{n}"
    for name in ("chunks", "completed", "partial"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"orders": [n]}), encoding="utf-8"
    )
    stem = f"00000000-{len(entries)-1:08d}"
    archived = folder / "chunks" / f"{stem}.tsv.gz"
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, delimiter="\t", lineterminator="\n",
        fieldnames=non_helly.REQUIRED_COLUMNS,
    )
    writer.writeheader()
    writer.writerows(entries)
    with archived.open("wb") as raw:
        with gzip.GzipFile(
            fileobj=raw, filename="", mode="wb", mtime=0,
        ) as stream:
            stream.write(output.getvalue().encode("utf-8"))
    data = archived.read_bytes()
    (folder / "completed" / f"{stem}.done.json").write_text(
        json.dumps({
            "sha256": hashlib.sha256(data).hexdigest(),
            "rows": len(entries),
        }), encoding="utf-8",
    )
    return archived


def row(
    index: int,
    *,
    g6: str,
    helly_g: str = "FALSE",
    helly_kg: str = "TRUE",
    htype_g: str = "1:1",
    htype_kg: str = "0",
    status_g: str = "EXACT",
    status_kg: str = "EXACT",
) -> dict:
    return {
        "order": "3",
        "index": str(index),
        "graph6": g6,
        "helly_g": helly_g,
        "helly_kg": helly_kg,
        "status_g": status_g,
        "htype_g": htype_g,
        "status_kg": status_kg,
        "htype_kg": htype_kg,
    }


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.stage = "test"
        self.stages_patch = patch.dict(non_helly.STAGES, {"test": (3,)})
        self.counts_patch = patch.dict(non_helly.COUNTS, {3: 2})
        self.stages_patch.start()
        self.counts_patch.start()
        self.addCleanup(self.stages_patch.stop)
        self.addCleanup(self.counts_patch.stop)

    def test_report_filters_g_not_kg_and_formats_exact_types(self) -> None:
        write_completed_batch(
            self.root, self.stage, 3, [
                row(
                    0, g6="C|" + chr(96), htype_g="1:1",
                    htype_kg="1:3;2:1",
                ),
                row(
                    1, g6="C?", helly_g="TRUE", helly_kg="FALSE",
                ),
            ],
        )
        destination, count = non_helly.write_report(
            self.stage, self.root
        )
        self.assertEqual(count, 1)
        markdown = destination.read_text(encoding="utf-8")
        self.assertIn("<code>C&#124;" + chr(96) + "</code>", markdown)
        self.assertIn(r"\(S^{1}\)", markdown)
        self.assertIn(r"\bigvee_{3} S^{1} \vee S^{2}", markdown)
        self.assertIn("| Yes |", markdown)
        self.assertNotIn("<code>C?</code>", markdown)
        self.assertIn("among 2 connected graphs", markdown)

    def test_contractible_and_nonexact_types_are_not_misreported(self) -> None:
        write_completed_batch(
            self.root, self.stage, 3, [
                row(
                    0, g6="C?", htype_g="0", status_kg="BETTI_ONLY",
                    htype_kg="UNKNOWN",
                ),
                row(
                    1, g6="C@", htype_g="1:2",
                    status_kg="LIMITED", htype_kg="UNKNOWN",
                ),
            ],
        )
        report, count = non_helly.write_report(self.stage, self.root)
        self.assertEqual(count, 2)
        text = report.read_text()
        self.assertIn("Contractible", text)
        self.assertIn("Undetermined (Betti numbers only)", text)
        self.assertIn("Undetermined (resource limit)", text)
        self.assertIn(r"\bigvee_{2} S^{1}", text)

    def test_bad_hash_refuses_to_create_report(self) -> None:
        archived = write_completed_batch(
            self.root, self.stage, 3, [
                row(0, g6="C?"), row(1, g6="C@"),
            ],
        )
        archived.write_bytes(b"corrupted gzip")
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            non_helly.write_report(self.stage, self.root)
        self.assertFalse(non_helly.output_path(self.stage, self.root).exists())
        self.assertFalse(
            non_helly.output_path(self.stage, self.root)
            .with_suffix(".md.partial").exists()
        )

    def test_missing_batch_refuses_report(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Missing census manifest"):
            non_helly.write_report(self.stage, self.root)

    def test_wrong_row_index_refuses_report(self) -> None:
        write_completed_batch(
            self.root, self.stage, 3, [
                row(0, g6="C?"), row(3, g6="C@"),
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "Wrong graph index"):
            non_helly.write_report(self.stage, self.root)

    def test_invalid_exact_vector_is_rejected(self) -> None:
        self.assertEqual(
            non_helly.wedge_latex("0"), "Contractible"
        )
        self.assertEqual(
            non_helly.wedge_latex("1:1"), r"\(S^{1}\)"
        )
        with self.assertRaises(ValueError):
            non_helly.wedge_latex("1:1;1:3")
        with self.assertRaises(ValueError):
            non_helly.wedge_latex("1:0")
        with self.assertRaises(ValueError):
            non_helly.readable_type("BETTI_ONLY", "0")


if __name__ == "__main__":
    unittest.main()
