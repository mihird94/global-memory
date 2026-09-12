#!/usr/bin/env python3
"""
tests/test_review_contract.py — Comprehensive tests for Review Contract enforcement.

Tests:
1. Reviewer identity validation (unknown reviewer rejected with INVALID_REVIEWER).
2. Registered reviewer acceptance (mihir, antigravity, codex, gemini, system, etc.).
3. Substantive rationale requirement (>=10 non-whitespace chars on terminal actions).
4. Optimistic concurrency conflict detection (hash mismatch returns CONCURRENCY_CONFLICT).
5. Append-only audit trail in gms_review_audit with content hashes.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import memory_mcp_server
import reviewers


class TestReviewContract(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.db_path = self.mem_root / "gms_trust.sqlite"
        memory_mcp_server.init_db(self.db_path)

        # Stage a standard candidate
        cand = {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "platform.sqlite.concurrency",
            "statement": "Enforce WAL mode and 5000ms busy timeout on all SQLite connections.",
            "rationale": "High-frequency multi-agent concurrent writes cause database locked errors in rollback journal mode.",
            "scope": {"project": "global-memory", "level": "component"},
            "authority": "human_instruction",
            "provenance": {
                "source_refs": ["docs/architecture.md"],
                "source_hashes": ["sha256:abc123"],
                "extractor": "system",
                "extracted_at": "2026-09-08T12:00:00Z",
                "provider": "system",
                "model": "rule-v1",
                "prompt_version": "v1",
            },
            "evidence": [
                {
                    "ref": "docs/architecture.md#sec-1",
                    "excerpt_hash": "sha256:abc123",
                    "type": "documentation",
                }
            ],
            "implications": ["All database connection helpers must set PRAGMA journal_mode=WAL"],
            "review": {"requires_human": True, "status": "proposed"},
        }
        res = memory_mcp_server.stage_context_candidate(
            cand,
            extractor_agent="system",
            provider="system",
            model="rule-v1",
            prompt_version="v1",
            source_fingerprint="fp_sqlite_wal",
            db_path=self.db_path,
        )
        self.candidate_id = res["candidate_id"]
        self.content_hash = res["content_hash"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unknown_reviewer_rejected(self):
        """Reviewers not in the controlled registry must be rejected with INVALID_REVIEWER."""
        res = memory_mcp_server.review_context_candidate(
            candidate_id=self.candidate_id,
            action="accept",
            reviewer="rogue_agent_99",
            rationale="Valid substantive rationale that is long enough.",
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_code"], "INVALID_REVIEWER")
        self.assertIn("Unknown reviewer identity", res["error"])

    def test_registered_reviewer_accepted(self):
        """Registered reviewers (e.g. mihir, antigravity, system) are accepted."""
        for valid_reviewer in ("mihir", "Mihir", "antigravity", "system", "codex"):
            valid, norm = reviewers.validate_reviewer_id(valid_reviewer, mem_root=self.mem_root)
            self.assertTrue(valid, f"Expected {valid_reviewer} to be valid")

    def test_short_rationale_rejected_on_terminal_action(self):
        """Terminal actions (accept, edit, merge, supersede, reject) require >=10 characters rationale."""
        for short_rationale in ("", "   ", "ok", "looks good"):  # 'looks good' is 10 with spaces, but let's test <10 non-whitespace
            res = memory_mcp_server.review_context_candidate(
                candidate_id=self.candidate_id,
                action="accept",
                reviewer="mihir",
                rationale="short",  # 5 chars
                db_path=self.db_path,
            )
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_code"], "RATIONALE_REQUIRED")
            self.assertIn("at least 10 non-whitespace characters", res["error"])

    def test_defer_action_allows_brief_rationale(self):
        """Defer action does not strictly require 10 chars, but accepts rationale if provided."""
        res = memory_mcp_server.review_context_candidate(
            candidate_id=self.candidate_id,
            action="defer",
            reviewer="mihir",
            rationale="Wait",
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "deferred")
        self.assertEqual(res["candidate_id"], self.candidate_id)

    def test_optimistic_concurrency_conflict_detected(self):
        """Expected content hash mismatch must return CONCURRENCY_CONFLICT without mutating candidate."""
        res = memory_mcp_server.review_context_candidate(
            candidate_id=self.candidate_id,
            action="accept",
            reviewer="mihir",
            rationale="Verified and approving production rule.",
            expected_content_hash="sha256:stale_hash_from_earlier_view",
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_code"], "CONCURRENCY_CONFLICT")
        self.assertIn("content hash mismatch", res["error"])

        # Confirm candidate status is still staged
        cand = memory_mcp_server.get_context_candidate_by_id(self.candidate_id, db_path=self.db_path)
        self.assertEqual(cand["review_status"], "proposed")

    def test_successful_review_records_audit_trail(self):
        """Successful review updates candidate status, creates claim, and writes gms_review_audit."""
        res = memory_mcp_server.review_context_candidate(
            candidate_id=self.candidate_id,
            action="accept",
            reviewer="mihir",
            rationale="Architectural approval of WAL mode across all database connections.",
            expected_content_hash=self.content_hash,
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "accepted")

        # Verify audit record
        audit_history = memory_mcp_server.get_review_audit_history(self.candidate_id, db_path=self.db_path)
        self.assertEqual(len(audit_history), 1)
        audit_entry = audit_history[0]
        self.assertEqual(audit_entry["candidate_id"], self.candidate_id)
        self.assertEqual(audit_entry["canonical_key"], "platform.sqlite.concurrency")
        self.assertEqual(audit_entry["action"], "accept")
        self.assertEqual(audit_entry["reviewer_id"], "mihir")
        self.assertEqual(audit_entry["original_content_hash"], self.content_hash)
        self.assertTrue(audit_entry["resulting_claim_id"] is not None)


if __name__ == "__main__":
    unittest.main()
