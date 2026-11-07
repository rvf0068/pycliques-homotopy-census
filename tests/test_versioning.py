"""Regression tests for safe dependency updates and historical run recovery."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from historical_validate import link_directory
from versioning import (
    check_all_stage_completions,
    committed_runner_sha,
    historical_runner_revision,
    verify_stage_complete,
)


class VersioningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for folder in ("scripts", "config", "runs"):
            (self.root / folder).mkdir()
        (self.root / "scripts" / "census.py").write_text("print('original')\n")
        (self.root / "scripts" / "run.sh").write_text("#!/bin/sh\nexit 0\n")
        self.pin = "a" * 40
        (self.root / "config" / "pycliques_commit.txt").write_text(
            self.pin + "\n"
        )
        self.git("init", "-q", "-b", "main")
        self.git("add", "scripts", "config")
        self.commit("original")
        self.original = self.git("rev-parse", "HEAD")
        digest, pin = committed_runner_sha(self.root, self.original)
        self.assertEqual(pin, self.pin)
        self.manifest = {
            "orders": [7],
            "runner_sha256": digest,
            "monorepo_commit": pin,
        }

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True,
        ).strip()

    def commit(self, message):
        subprocess.run([
            "git", "-C", str(self.root),
            "-c", "user.name=Test",
            "-c", "user.email=test@example.org",
            "commit", "-qm", message,
        ], check=True)

    def completed_stage(self):
        directory = self.root / "runs" / "order7"
        output = directory / "order7"
        for part in ("chunks", "completed", "partial"):
            (output / part).mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps(self.manifest))
        (directory / "summary.json").write_text(json.dumps({
            "manifest": self.manifest,
            "orders": [{"order": 7, "counts": {"graphs": 853}}],
        }))
        payload = b"example data; checksum validated by guard"
        (output / "chunks" / "00000000-00000852.tsv.gz").write_bytes(payload)
        (output / "completed" / "00000000-00000852.done.json").write_text(
            json.dumps({
                "sha256": hashlib.sha256(payload).hexdigest(),
                "rows": 853,
            })
        )
        return directory

    def test_lookup_old_committed_runner_after_source_change(self):
        (self.root / "scripts" / "census.py").write_text(
            "print('updated')\n"
        )
        self.git("add", "scripts")
        self.commit("updated")
        self.assertEqual(
            historical_runner_revision(self.root, self.manifest),
            self.original,
        )

    def test_completed_validated_stage_is_safe(self):
        self.completed_stage()
        result = check_all_stage_completions(self.root)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["runner"], self.original)

    def test_partial_journal_blocks_update(self):
        directory = self.completed_stage()
        (directory / "order7" / "partial" / "00000000-00000852.partial.tsv").write_text(
            "unfinished"
        )
        with self.assertRaisesRegex(RuntimeError, "Unfinished"):
            check_all_stage_completions(self.root)

    def test_unvalidated_stage_blocks_update(self):
        directory = self.completed_stage()
        (directory / "summary.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "not yet validated"):
            check_all_stage_completions(self.root)

    def test_corrupted_batch_blocks_update(self):
        directory = self.completed_stage()
        (directory / "order7" / "chunks" / "00000000-00000852.tsv.gz").write_bytes(
            b"damaged"
        )
        with self.assertRaisesRegex(RuntimeError, "Corrupt batch"):
            verify_stage_complete(self.root, "7")

    def test_counterexample_stops_update(self):
        directory = self.completed_stage()
        (directory / "STOP_COUNTEREXAMPLE.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "counterexample"):
            check_all_stage_completions(self.root)

    def test_followup_overlay_does_not_block_future_dependency_updates(self):
        self.completed_stage()
        overlay = self.root / "runs" / "order9_morse_followup"
        overlay.mkdir()
        (overlay / "summary.json").write_text('{"resolved_rows": 6}')
        result = check_all_stage_completions(self.root)
        self.assertEqual([entry["stage"] for entry in result], ["7"])

    def test_unvalidated_stage_still_blocks_even_with_morse_overlay(self):
        directory = self.completed_stage()
        (self.root / "runs" / "order9_morse_followup").mkdir()
        (directory / "summary.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "not yet validated"):
            check_all_stage_completions(self.root)

    def test_unexpected_run_data_blocks_update(self):
        (self.root / "runs" / "unknown_stage").mkdir()
        with self.assertRaisesRegex(RuntimeError, "Unexpected"):
            check_all_stage_completions(self.root)

    def test_historical_symlink_is_not_overwritten(self):
        source = self.root / "runs" / "order7"
        source.mkdir()
        target = self.root / "history" / "order7"
        link_directory(source, target)
        link_directory(source, target)
        self.assertEqual(target.resolve(), source.resolve())
        other = self.root / "runs" / "order8"
        other.mkdir()
        with self.assertRaisesRegex(RuntimeError, "wrong directory"):
            link_directory(other, target)


if __name__ == "__main__":
    unittest.main()
