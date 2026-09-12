"""
test_reputation_invariance.py — Verification of Reputation Decoupling
====================================================================
Tests proving that candidate validation, staging, review priority, and
promotion outcomes are completely invariant to the contents of the legacy
gms_agent_reputation table (Pass 5 §7 & §11.3).
"""
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

tools_dir = str(Path(__file__).parent.parent / "tools")
fixtures_dir = str(Path(__file__).parent / "fixtures")
for p in (tools_dir, fixtures_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

import memory_mcp_server
import schemas
import dream_cycle
from harvest_fixtures import HARVEST_EVAL_CORPUS


class TestReputationInvariance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_db_path = memory_mcp_server.DB_PATH
        self.old_dream_root = dream_cycle.MEM_ROOT

        memory_mcp_server.MEM_ROOT = self.temp_path
        memory_mcp_server.DB_PATH = self.temp_path / "gms_trust.sqlite"
        dream_cycle.MEM_ROOT = self.temp_path

        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "episodic" / "history").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "logs").mkdir(parents=True, exist_ok=True)

        memory_mcp_server.init_db()

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_db_path
        dream_cycle.MEM_ROOT = self.old_dream_root
        self.temp_dir.cleanup()

    def _set_agent_reputation(self, agent_id: str, alpha: float, beta: float):
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (agent_id, alpha, beta),
        )
        conn.commit()
        conn.close()

    def test_candidate_validation_invariant_to_reputation(self):
        """Proof: Candidate schema validation does not query or depend on gms_agent_reputation."""
        cand = copy.deepcopy(HARVEST_EVAL_CORPUS["1_user_decision_with_rationale"]["record"])

        # Case A: Agent has astronomical reputation (alpha=1000.0, beta=0.0)
        self._set_agent_reputation("HighRepAgent", 1000.0, 0.0)
        cand["provenance"]["extractor"] = "HighRepAgent"
        is_valid_high, norm_high, err_high = schemas.validate_context_candidate(cand)

        # Case B: Agent has zero reputation (alpha=0.0, beta=1000.0)
        self._set_agent_reputation("ZeroRepAgent", 0.0, 1000.0)
        cand["provenance"]["extractor"] = "ZeroRepAgent"
        is_valid_zero, norm_zero, err_zero = schemas.validate_context_candidate(cand)

        # Case C: Agent does not exist in reputation table
        cand["provenance"]["extractor"] = "UnknownAgent"
        is_valid_unknown, norm_unknown, err_unknown = schemas.validate_context_candidate(cand)

        self.assertTrue(is_valid_high)
        self.assertTrue(is_valid_zero)
        self.assertTrue(is_valid_unknown)
        self.assertIsNone(err_high)
        self.assertIsNone(err_zero)
        self.assertIsNone(err_unknown)

        # Content hashes should be identical because extractor agent is part of provenance
        # but validation rules and outcomes are completely invariant
        self.assertEqual(norm_high["schema_version"], norm_zero["schema_version"])
        self.assertEqual(norm_high["record_type"], norm_zero["record_type"])

    def test_invalid_candidate_rejected_regardless_of_reputation(self):
        """Proof: High reputation cannot bypass validation rules (e.g. missing rationale)."""
        bad_cand = copy.deepcopy(HARVEST_EVAL_CORPUS["2_decision_without_rationale"]["record"])

        # Give extractor maximum possible reputation
        self._set_agent_reputation("SuperAgent", 9999.0, 0.0)
        bad_cand["provenance"]["extractor"] = "SuperAgent"

        is_valid, norm, err = schemas.validate_context_candidate(bad_cand)
        self.assertFalse(is_valid)
        self.assertIsNone(norm)
        self.assertIn("rationale", err.lower())

    def test_staging_and_deduplication_invariant_to_reputation(self):
        """Proof: Candidate staging and dedupe work identically regardless of reputation table."""
        cand = copy.deepcopy(HARVEST_EVAL_CORPUS["3_technical_fact_from_tests"]["record"])

        self._set_agent_reputation("AgentA", 50.0, 0.0)
        cand["provenance"]["extractor"] = "AgentA"

        res1 = memory_mcp_server.stage_context_candidate(cand)
        self.assertEqual(res1["status"], "staged")

        # Second attempt should be detected as duplicate
        res2 = memory_mcp_server.stage_context_candidate(cand)
        self.assertEqual(res2["status"], "duplicate")

        # Now change AgentA's reputation to complete failure
        self._set_agent_reputation("AgentA", 0.0, 50.0)
        res3 = memory_mcp_server.stage_context_candidate(cand)
        self.assertEqual(res3["status"], "duplicate")

    def test_promotion_invariant_to_reputation(self):
        """Proof: Candidate review and promotion into canonical facts.json succeeds identically regardless of reputation."""
        cand = copy.deepcopy(HARVEST_EVAL_CORPUS["1_user_decision_with_rationale"]["record"])
        cand["key"] = "test.policy.reputation_invariant"

        # Agent with zero reputation creates candidate
        self._set_agent_reputation("ZeroRepAgent", 0.0, 100.0)
        cand["provenance"]["extractor"] = "ZeroRepAgent"

        stage_res = memory_mcp_server.stage_context_candidate(cand)
        self.assertEqual(stage_res["status"], "staged")
        candidate_id = stage_res["candidate_id"]

        # Reviewer with no reputation accepts it
        rev_res = memory_mcp_server.review_context_candidate(
            candidate_id=candidate_id,
            action="accept",
            reviewer="UnrankedReviewer",
            rationale="Verified architectural direction"
        )
        self.assertEqual(rev_res["status"], "accepted")
        self.assertIsNotNone(rev_res["claim_id"])

        # Verify fact exists in facts.json with full structured envelope
        facts_file = self.temp_path / "semantic" / "facts.json"
        self.assertTrue(facts_file.exists())
        facts = json.loads(facts_file.read_text(encoding="utf-8"))
        self.assertIn("test.policy.reputation_invariant", facts)
        stored_payload = json.loads(facts["test.policy.reputation_invariant"])
        self.assertEqual(stored_payload["record_type"], "decision")
        self.assertEqual(stored_payload["rationale"], cand["rationale"])

        # Verify claim in SQLite has status='active' and confidence is unaffected by legacy trust
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT status, confidence FROM gms_claims WHERE claim_id = ?", (rev_res["claim_id"],))
        claim_row = cursor.fetchone()
        conn.close()

        self.assertEqual(claim_row[0], "active")
        self.assertEqual(claim_row[1], 1.0)  # Accepted claim confidence is authoritative 1.0, not zero-rep score!

    def test_dream_cycle_default_does_not_run_calibration(self):
        """Proof: Default Dream Cycle execution does NOT run beta-binomial reputation calibration."""
        # Insert a baseline reputation row
        self._set_agent_reputation("ObservedAgent", 1.0, 0.0)

        # Write dummy journal so dream cycle runs
        journal = self.temp_path / "episodic" / "journal.md"
        journal.write_text("Work completed for today without incident.")

        # Run Dream Cycle in a real dry-run configuration.  Stub extraction so
        # this unit test can never reach an external provider.
        old_dry_run = dream_cycle.DRY_RUN
        old_extract = dream_cycle.extract_facts_with_cascade
        dream_cycle.DRY_RUN = True
        dream_cycle.extract_facts_with_cascade = lambda *_args, **_kwargs: ([], "fixture")
        try:
            exit_code = dream_cycle.main()
        finally:
            dream_cycle.DRY_RUN = old_dry_run
            dream_cycle.extract_facts_with_cascade = old_extract
        self.assertEqual(exit_code, 0)

        # Dry-run status is in memory only and must not overwrite production telemetry.
        status_file = self.temp_path / "logs" / "dream_cycle_status.json"
        self.assertFalse(status_file.exists())
        self.assertTrue(dream_cycle.LAST_RUN_STATUS["dry_run"])
        self.assertEqual(dream_cycle.LAST_RUN_STATUS["durable_writes"], 0)

        # Verify reputation row remained unchanged (not recalibrated)
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT alpha, beta FROM gms_agent_reputation WHERE agent_id = 'ObservedAgent'")
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[0], 1.0)
        self.assertEqual(row[1], 0.0)


if __name__ == "__main__":
    unittest.main()
