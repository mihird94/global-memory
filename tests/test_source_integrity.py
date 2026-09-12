#!/usr/bin/env python3
"""
tests/test_source_integrity.py — Tests for source reference and excerpt hash verification.
"""

import tempfile
import unittest
from pathlib import Path

import schemas


class TestSourceIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)

        # Create test notes directory and markdown document
        self.history_dir = self.mem_root / "episodic" / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.test_doc = self.history_dir / "2026-09-08.md"

        self.doc_content = """# 2026-09-08 Daily Notes

## 1. Architectural Decisions

Mbrain should not use synthetic trust scores.
A single scalar collapses distinct dimensions of reliability.
Each agent claim must be evaluated on evidence and verification.

## 2. Implementation Workstream

We configured SQLite busy_timeout to 5000ms.
WAL mode has been verified under concurrent testing.
Line 10 test content.
"""
        self.test_doc.write_text(self.doc_content, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_section_reference_and_hash(self):
        """A valid relative path with section anchor and matching hash succeeds."""
        # Calculate expected excerpt hash for Section 1
        ok, excerpt, _ = schemas.extract_source_excerpt(self.doc_content, anchor="sec-1")
        self.assertTrue(ok)
        expected_hash = f"sha256:{schemas.compute_excerpt_hash(excerpt)}"

        valid, status, details = schemas.validate_source_reference(
            source_ref="episodic/history/2026-09-08.md#sec-1",
            excerpt_hash=expected_hash,
            mem_root=self.mem_root,
        )
        self.assertTrue(valid)
        self.assertEqual(status, "valid")
        self.assertEqual(details["computed_hash"], expected_hash)

    def test_missing_file_detection(self):
        """Reference to a nonexistent file reports missing_file."""
        valid, status, details = schemas.validate_source_reference(
            source_ref="episodic/history/2025-01-01.md#sec-1",
            excerpt_hash="sha256:dummyhash",
            mem_root=self.mem_root,
        )
        self.assertFalse(valid)
        self.assertEqual(status, "missing_file")
        self.assertIn("Source file does not exist", details["error"])

    def test_missing_anchor_detection(self):
        """Reference to an existing file with a nonexistent anchor reports missing_anchor."""
        valid, status, details = schemas.validate_source_reference(
            source_ref="episodic/history/2026-09-08.md#nonexistent-heading-xyz",
            excerpt_hash="sha256:dummyhash",
            mem_root=self.mem_root,
        )
        self.assertFalse(valid)
        self.assertEqual(status, "missing_anchor")
        self.assertIn("not found", details["error"])

    def test_hash_mismatch_on_modified_source(self):
        """If source file content was modified, hash mismatch is detected."""
        stale_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        valid, status, details = schemas.validate_source_reference(
            source_ref="episodic/history/2026-09-08.md#sec-1",
            excerpt_hash=stale_hash,
            mem_root=self.mem_root,
        )
        self.assertFalse(valid)
        self.assertEqual(status, "hash_mismatch")
        self.assertIn("Excerpt hash mismatch", details["error"])

    def test_whole_file_reference(self):
        """Whole-file reference without anchor validates using whole file hash."""
        whole_hash = f"sha256:{schemas.compute_excerpt_hash(self.doc_content)}"
        valid, status, details = schemas.validate_source_reference(
            source_ref="episodic/history/2026-09-08.md",
            excerpt_hash=whole_hash,
            mem_root=self.mem_root,
        )
        self.assertTrue(valid)
        self.assertEqual(status, "valid")

    def test_line_number_locator(self):
        """Line range anchor (e.g. #L3-L5) extracts exact lines and computes hash."""
        ok, excerpt, _ = schemas.extract_source_excerpt(self.doc_content, anchor="L3-L5")
        self.assertTrue(ok)
        self.assertIn("synthetic trust scores", excerpt)

        line_hash = f"sha256:{schemas.compute_excerpt_hash(excerpt)}"
        valid, status, details = schemas.validate_source_reference(
            source_ref="episodic/history/2026-09-08.md#L3-L5",
            excerpt_hash=line_hash,
            mem_root=self.mem_root,
        )
        self.assertTrue(valid)
        self.assertEqual(status, "valid")


if __name__ == "__main__":
    unittest.main()
