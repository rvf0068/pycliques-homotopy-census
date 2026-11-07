"""Regression tests for lossless order-10 compressed checkpoint migration."""

from __future__ import annotations

import csv
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from census import COLUMNS
from audits.order10_checkpoints import (
    checksum,
    inspect_journal,
    prune_completed,
    restore,
    snapshot,
)


def fake_run(root: Path, count: int = 5, stem: str = "00600000-00699999") -> Path:
    stage = root / "runs" / "order10"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "manifest.json").write_text(
        json.dumps({"orders": [10], "settings": {"max_graph_seconds": 120}})
    )
    partial = stage / "order10" / "partial"
    partial.mkdir(parents=True, exist_ok=True)
    target = partial / (stem + ".partial.tsv")
    start = int(stem.split("-")[0])
    with target.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=COLUMNS, delimiter="\t",
                                lineterminator="\n")
        writer.writeheader()
        for i in range(count):
            row = {k: "" for k in COLUMNS}
            row.update(
                order=10, index=start + i, graph6="I?" + "a" * 8,
                helly_g="FALSE", helly_kg="TRUE",
                status_g="EXACT", status_kg="EXACT",
                htype_g="0", htype_kg="0",
                betti_g="0", betti_kg="0",
                comparison="EQUIVALENT",
            )
            writer.writerow(row)
    return target


class CheckpointTests(unittest.TestCase):
    def test_round_trip_preserves_every_byte_and_avoids_recalculation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 11)
            original = raw.read_bytes()
            meta = snapshot(root, stage_git=False)
            self.assertEqual(meta["rows"], 11)
            self.assertEqual(meta["original_sha256"], checksum(raw))
            self.assertTrue(raw.exists(), "Saving must never delete local data")
            archive = (
                root / "checkpoints" / "order10" /
                "00600000-00699999.partial.tsv.gz"
            )
            with gzip.open(archive, "rb") as stream:
                self.assertEqual(stream.read(), original)
            raw.unlink()
            self.assertEqual(restore(root), 1)
            self.assertEqual(raw.read_bytes(), original)
            self.assertEqual(inspect_journal(raw, "00600000-00699999"), 11)
            self.assertEqual(restore(root), 0)

    def test_corrupt_snapshot_is_rejected_without_touching_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root)
            snapshot(root, stage_git=False)
            archive = (
                root / "checkpoints" / "order10" /
                "00600000-00699999.partial.tsv.gz"
            )
            archive.write_bytes(b"corruption")
            raw.unlink()
            with self.assertRaisesRegex(RuntimeError, "corrupted"):
                restore(root)
            self.assertFalse(raw.exists())

    def test_manifest_change_blocks_cross_run_restoration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root)
            snapshot(root, stage_git=False)
            raw.unlink()
            (root / "runs" / "order10" / "manifest.json").write_text(
                json.dumps({"orders": [10], "settings": {"max_graph_seconds": 999}})
            )
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                restore(root)
            self.assertFalse(raw.exists())

    def test_torn_row_refused_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root)
            with raw.open("ab") as stream:
                stream.write(b"10\t600005\tBROKEN")
            original = raw.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "torn last line"):
                snapshot(root, stage_git=False)
            self.assertEqual(raw.read_bytes(), original)

    def test_restore_preserves_newer_local_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 3)
            snapshot(root, stage_git=False)
            newer = fake_run(root, 8)
            original = newer.read_bytes()
            self.assertEqual(restore(root), 0)
            self.assertEqual(newer.read_bytes(), original)

    def test_restore_leaves_torn_tail_for_original_census_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 3)
            snapshot(root, stage_git=False)
            with raw.open("ab") as stream:
                stream.write(b"10\\t600003\\tBROKEN")
            original = raw.read_bytes()
            # This must not fail before the census runner gets the journal.
            self.assertEqual(restore(root), 0)
            self.assertEqual(raw.read_bytes(), original)
            from census import read_partial
            self.assertEqual(len(read_partial(raw, 600000)), 3)
            self.assertTrue(raw.read_bytes().endswith(b"\\n"))

    def test_out_of_range_snapshot_indices_are_rejected(self):
        from audits.order10_checkpoints import bounds
        with self.assertRaisesRegex(RuntimeError, "Unexpected"):
            bounds("11800000-11716570")
        with self.assertRaisesRegex(RuntimeError, "Unexpected"):
            bounds("11700000-11799999")

    def test_stale_local_journal_is_rejected_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 9)
            snapshot(root, stage_git=False)
            older = fake_run(root, 2)
            contents = older.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "older than"):
                restore(root)
            self.assertEqual(raw.read_bytes(), contents)

    def test_divergent_local_journal_is_rejected_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 5)
            snapshot(root, stage_git=False)
            modified = raw.read_bytes().replace(b"I?aaaaaaaa", b"I?bbbbbbbb")
            raw.write_bytes(modified)
            with self.assertRaisesRegex(RuntimeError, "differs from"):
                restore(root)
            self.assertEqual(raw.read_bytes(), modified)

    def test_finished_chunk_supersedes_and_prunes_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 2)
            snapshot(root, stage_git=False)
            raw.unlink()
            order = root / "runs" / "order10" / "order10"
            chunk = order / "chunks" / "00600000-00699999.tsv.gz"
            done = order / "completed" / "00600000-00699999.done.json"
            chunk.parent.mkdir(parents=True)
            done.parent.mkdir(parents=True)
            with gzip.open(chunk, "wb") as out:
                out.write(b"authoritative completed batch")
            done.write_text(json.dumps({
                "sha256": checksum(chunk), "rows": 100000,
            }))
            self.assertEqual(restore(root), 0)
            self.assertFalse(raw.exists())
            self.assertEqual(prune_completed(root, stage_git=False), 1)
            self.assertEqual(list((root / "checkpoints" / "order10").iterdir()), [])

    def test_invalid_finished_marker_cannot_mask_unfinished_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 2)
            snapshot(root, stage_git=False)
            raw.unlink()
            done = (
                root / "runs" / "order10" / "order10" / "completed" /
                "00600000-00699999.done.json"
            )
            done.parent.mkdir(parents=True)
            done.write_text(json.dumps({"sha256": "bad", "rows": 100000}))
            with self.assertRaisesRegex(RuntimeError, "without archive"):
                restore(root)
            self.assertFalse(raw.exists())

    def test_corrupt_obsolete_snapshot_does_not_block_valid_completed_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 2)
            snapshot(root, stage_git=False)
            raw.unlink()
            order = root / "runs" / "order10" / "order10"
            chunk = order / "chunks" / "00600000-00699999.tsv.gz"
            done = order / "completed" / "00600000-00699999.done.json"
            chunk.parent.mkdir(parents=True)
            done.parent.mkdir(parents=True)
            with gzip.open(chunk, "wb") as out:
                out.write(b"authoritative completed batch")
            done.write_text(json.dumps({
                "sha256": checksum(chunk), "rows": 100000,
            }))
            old = root / "checkpoints" / "order10" / "00600000-00699999.partial.tsv.gz"
            old.write_bytes(b"corrupt obsolete backup")
            self.assertEqual(prune_completed(root, stage_git=False), 1)
            self.assertFalse(old.exists())

    def test_git_snapshot_untracks_but_does_not_delete_old_raw_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = fake_run(root, 3)
            shutil.copy2(ROOT / ".gitignore", root / ".gitignore")
            def git(*args: str):
                return subprocess.run(
                    ["git", "-C", str(root), *args],
                    check=True, text=True, capture_output=True,
                ).stdout.strip()
            git("init", "-q")
            git("config", "user.email", "test@example.org")
            git("config", "user.name", "Checkpoint Test")
            git("add", "-f", "--", raw.relative_to(root).as_posix())
            git("add", "--", ".gitignore", "runs/order10/manifest.json")
            git("commit", "-qm", "legacy raw journal")
            self.assertIn("partial.tsv", git("ls-files"))
            snapshot(root, stage_git=True)
            staged = git("diff", "--cached", "--name-status")
            self.assertIn("D\truns/order10/order10/partial/00600000-00699999.partial.tsv",
                          staged)
            self.assertIn("A\tcheckpoints/order10/00600000-00699999.partial.tsv.gz",
                          staged)
            self.assertIn("A\tcheckpoints/order10/00600000-00699999.snapshot.json",
                          staged)
            self.assertTrue(raw.is_file())
            self.assertNotIn(
                "partial.tsv\n", git("ls-files") + "\n"
            )


if __name__ == "__main__":
    unittest.main()
