"""Regression tests for issues raised in PR #6 code review."""

from __future__ import annotations

import csv
import gzip
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import census
from audits.benchmark_order10 import (
    COLUMNS as PILOT_COLUMNS,
    pilot_source_digest,
    recover_pilot_rows,
)
from reports.order10_split import render_batch


class CopilotReviewRegressions(unittest.TestCase):
    def test_old_manifest_runs_report_only_without_recomputation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(ROOT / "run_with_report.sh", root / "run_with_report.sh")
            (root / "runs" / "order7").mkdir(parents=True)
            (root / "runs" / "order7" / "manifest.json").write_text("{}")
            (root / ".venv" / "bin").mkdir(parents=True)
            stub = root / ".venv" / "bin" / "python"
            stub.write_text('#!/bin/sh\necho "$*" >> invoked.txt\n')
            stub.chmod(0o755)
            (root / "scripts").mkdir()
            (root / "scripts" / "run.sh").write_text(
                "#!/bin/sh\necho forbidden-run >> invoked.txt\nexit 3\n"
            )
            proc = subprocess.run(
                ["bash", str(root / "run_with_report.sh"), "7"],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            commands = (root / "invoked.txt").read_text()
            self.assertIn("reports/non_helly.py --stage 7", commands)
            self.assertNotIn("forbidden-run", commands)
            (root / "invoked.txt").write_text("")
            refused = subprocess.run(
                ["bash", str(root / "run_with_report.sh"), "7",
                 "--max-graph-seconds", "120"],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(refused.returncode, 2)
            self.assertFalse((root / "invoked.txt").read_text())

    def test_source_digest_detects_local_edits_to_runner_and_pilot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("scripts", "audits", "config"):
                (root / name).mkdir()
            script = root / "scripts" / "census.py"
            pilot = root / "audits" / "benchmark_order10.py"
            script.write_text("first")
            pilot.write_text("pilot")
            (root / "config" / "pycliques_commit.txt").write_text("a" * 40)
            first = pilot_source_digest(root)
            script.write_text("second")
            second = pilot_source_digest(root)
            self.assertNotEqual(first, second)
            pilot.write_text("updated")
            self.assertNotEqual(second, pilot_source_digest(root))

    def test_pilot_recovers_unterminated_final_row_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot.tsv"
            header = "\t".join(PILOT_COLUMNS) + "\n"
            row = {
                "index": "0", "graph6": "Dhc", "seconds": "0.100000",
                "status_g": "EXACT", "status_kg": "EXACT",
                "comparison": "EQUIVALENT",
                "helly_g": "TRUE", "helly_kg": "TRUE", "k_order": "5",
            }
            complete = "\t".join(row[name] for name in PILOT_COLUMNS) + "\n"
            output.write_bytes((header + complete + "1\tBROKEN").encode())
            self.assertEqual(recover_pilot_rows(output, [0, 1]), {0: "Dhc"})
            self.assertEqual(output.read_text(), header + complete)
            with output.open("a") as stream:
                stream.write("1\tBROKEN\n")
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                recover_pilot_rows(output, [0, 1])

    def test_report_parts_are_hashed_and_checked_before_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "batch.tsv.gz"
            with gzip.open(archive, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=census.COLUMNS,
                    delimiter="\t", lineterminator="\n",
                )
                writer.writeheader()
                for i in range(4):
                    row = census.graph_timeout_row("Dhc", 10, i, 120)
                    row.update(
                        helly_g="FALSE", helly_kg="TRUE",
                        status_g="EXACT", status_kg="EXACT",
                        htype_g="1:1", htype_kg="1:1",
                        betti_g="1:1", betti_kg="1:1",
                        comparison="EQUIVALENT",
                    )
                    writer.writerow(row)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            meta = render_batch(root, 0, 3, archive, digest, max_bytes=700)
            self.assertTrue(meta["parts_sha256"])
            part = root / "reports" / "order10_parts" / meta["parts"][0]
            part.write_text(part.read_text() + "\ntampered\n")
            with self.assertRaisesRegex(RuntimeError, "Corrupt or missing"):
                render_batch(root, 0, 3, archive, digest, max_bytes=700)


if __name__ == "__main__":
    unittest.main()
