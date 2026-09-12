#!/usr/bin/env python3
"""
tests/test_pollution_audit.py — Unit tests for pollution audit and surgical cleanup.
"""

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pollution_audit
import memory_mcp_server


class TestPollutionAudit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.db_path = self.mem_root / "gms_trust.sqlite"
        self.facts_path = self.mem_root / "semantic" / "facts.json"
        self.facts_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize test DB schema
        memory_mcp_server.init_db(self.db_path)

        # Setup test data: 1 genuine candidate, 1 pollution candidate
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Genuine candidate
        cursor.execute(
            """
            INSERT INTO gms_context_candidates (
                candidate_id, schema_version, record_type, canonical_key,
                payload_json, source_fingerprint, content_hash,
                extractor_agent, prompt_version, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand_genuine_001",
                "gms-context-record-v1",
                "decision",
                "core.architecture.principles",
                json.dumps({"key": "core.architecture.principles", "statement": "Genuine architectural principle"}),
                "fp1",
                "hash1",
                "system",
                "v1",
                "staged",
            ),
        )

        # Polluted candidate
        cursor.execute(
            """
            INSERT INTO gms_context_candidates (
                candidate_id, schema_version, record_type, canonical_key,
                payload_json, source_fingerprint, content_hash,
                extractor_agent, prompt_version, review_status, reviewed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand_mbrain.agent_trust_architecture_2bd8e5c4816f",
                "gms-context-record-v1",
                "decision",
                "mbrain.agent_trust_architecture",
                json.dumps({"key": "mbrain.agent_trust_architecture", "statement": "Smoke test decision"}),
                "fp2",
                "hash2",
                "test",
                "v1",
                "accepted",
                "Mihir",
            ),
        )

        # Genuine claim
        cursor.execute(
            """
            INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, status)
            VALUES ('fact', 'production.deployment_target', 'macOS Sonoma', 'antigravity', 'active')
            """
        )

        # Polluted claims
        cursor.execute(
            """
            INSERT INTO gms_claims (claim_id, memory_kind, memory_key, value, agent_id, status)
            VALUES (119, 'decision', 'mbrain.agent_trust_architecture', 'Retired trust scores', 'Mihir', 'active')
            """
        )
        cursor.execute(
            """
            INSERT INTO gms_claims (claim_id, memory_kind, memory_key, value, agent_id, status)
            VALUES (120, 'fact', 'test_key_dummy', '12345', 'tester', 'active')
            """
        )

        conn.commit()
        conn.close()

        # Setup facts.json with 1 genuine key and 2 test keys
        facts_content = {
            "production.deployment_target": "macOS Sonoma",
            "test_reinforce": "foo",
            "latest_key": "bar",
        }
        self.facts_path.write_text(json.dumps(facts_content, indent=2), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dry_run_isolation_and_detection(self):
        """Dry-run audit accurately detects pollution and guarantees zero disk mutations."""
        # Calculate pre-audit SHA-256 hashes
        db_hash_pre = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        facts_hash_pre = hashlib.sha256(self.facts_path.read_bytes()).hexdigest()

        # Run dry-run audit
        findings = pollution_audit.run_pollution_audit(db_path=self.db_path, mem_root=self.mem_root)
        self.assertEqual(findings["total_pollutants"], 5)
        self.assertEqual(len(findings["test_candidates"]), 1)
        self.assertEqual(findings["test_candidates"][0]["candidate_id"], "cand_mbrain.agent_trust_architecture_2bd8e5c4816f")
        self.assertEqual(len(findings["test_claims"]), 2)
        self.assertEqual(len(findings["test_facts"]), 2)

        # Run dry-run cleanup (apply=False)
        cleanup_res = pollution_audit.run_pollution_cleanup(apply=False, db_path=self.db_path, mem_root=self.mem_root)
        self.assertEqual(cleanup_res["status"], "dry_run")

        # Verify disk hashes did not change
        db_hash_post = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        facts_hash_post = hashlib.sha256(self.facts_path.read_bytes()).hexdigest()
        self.assertEqual(db_hash_pre, db_hash_post)
        self.assertEqual(facts_hash_pre, facts_hash_post)

    def test_cleanup_apply_and_audit_trail(self):
        """Applying cleanup surgically removes pollutants, records audit trail, and preserves genuine data."""
        cleanup_res = pollution_audit.run_pollution_cleanup(apply=True, db_path=self.db_path, mem_root=self.mem_root)
        self.assertEqual(cleanup_res["status"], "applied")
        self.assertEqual(len(cleanup_res["deleted"]["deleted_candidates"]), 1)
        self.assertEqual(len(cleanup_res["deleted"]["deleted_claims"]), 2)
        self.assertEqual(len(cleanup_res["deleted"]["deleted_facts"]), 2)

        # Verify facts.json has only genuine keys
        facts_data = json.loads(self.facts_path.read_text(encoding="utf-8"))
        self.assertEqual(set(facts_data.keys()), {"production.deployment_target"})

        # Verify SQLite DB
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Genuine candidate still exists
        cursor.execute("SELECT candidate_id FROM gms_context_candidates")
        cands = [r["candidate_id"] for r in cursor.fetchall()]
        self.assertEqual(cands, ["cand_genuine_001"])

        # Genuine claim still exists
        cursor.execute("SELECT memory_key FROM gms_claims")
        claims = [r["memory_key"] for r in cursor.fetchall()]
        self.assertEqual(claims, ["production.deployment_target"])

        # Audit trail recorded in gms_review_audit
        cursor.execute("SELECT action, canonical_key, reviewer_id FROM gms_review_audit")
        audit_rows = cursor.fetchall()
        self.assertEqual(len(audit_rows), 3)  # 1 candidate + 2 claims
        for row in audit_rows:
            self.assertEqual(row["action"], "pollution_cleanup")
            self.assertEqual(row["reviewer_id"], "mihir")

        conn.close()

        # Verify second audit run is clean (idempotency)
        second_audit = pollution_audit.run_pollution_audit(db_path=self.db_path, mem_root=self.mem_root)
        self.assertEqual(second_audit["total_pollutants"], 0)


if __name__ == "__main__":
    unittest.main()
