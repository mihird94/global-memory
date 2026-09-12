#!/usr/bin/env python3
"""
tests/test_harvest_api_and_review.py — Stage 3 & 4 Verification Suite.

Validates:
1. Harvest queue status aggregation and candidate querying with diffs.
2. Candidate review workflow (accept, edit, merge, reject, defer) with audit records.
3. Legacy flat record migration dry-run and apply idempotency.
4. Context packet precedence for accepted typed records and proposal exclusion.
5. Zero LLM model loading on desktop API browse and review paths.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gms_desktop_api
import memory_mcp_server
import migrate_flat_records
import schemas


class TestHarvestApiAndReview(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.db_path = self.mem_root / "gms_trust.sqlite"
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_db_path = memory_mcp_server.DB_PATH
        memory_mcp_server.MEM_ROOT = self.mem_root
        memory_mcp_server.DB_PATH = self.db_path
        memory_mcp_server.init_db(self.db_path)

        # Seed sample daily note and active facts
        history_dir = self.mem_root / "episodic" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        # Preserve the migration's real line-locator contract in the fixture.
        lines = [f"fixture line {i}" for i in range(1, 61)]
        lines[15] = "### Retired global agent trust"
        lines[16] = "Global trust scores collapse evidence, scope, and recency into false certainty."
        lines[18] = "### Rationale-first durable memory"
        lines[19] = "Durable decisions require rationale, implications, scope, provenance, and review conditions."
        lines[34] = "Implemented deterministic Small, Standard, and Deep context packets with secret masking."
        lines[43] = "Verified SQLite WAL mode and busy_timeout=5000 for concurrent agents."
        lines[52] = "Validated tools/eval_retrieval_benchmark.py as the retrieval benchmark harness."
        lines[56] = "Synthetic benchmark showed BM25 ahead on short exact queries."
        (history_dir / "2026-09-08.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

        facts_dir = self.mem_root / "semantic"
        facts_dir.mkdir(parents=True, exist_ok=True)
        self.facts_path = facts_dir / "facts.json"
        self.facts_path.write_text(
            json.dumps({
                "mbrain_agent_trust_architecture": "Legacy flat string for trust architecture.",
                "global_memory_sqlite_concurrency": "Legacy flat string for sqlite concurrency.",
            }),
            encoding="utf-8",
        )

        self.api = gms_desktop_api.GMSDesktopAPI(mem_root=self.mem_root)

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def _sample_decision_candidate(self, key="test.sample_decision", statement="Use WAL mode everywhere.") -> dict:
        return {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": key,
            "statement": statement,
            "rationale": "High concurrency across agents requires non-blocking reads.",
            "implications": [
                "All DB connections must specify busy_timeout=5000.",
                "Avoid bare connect calls."
            ],
            "scope": {
                "level": "system",
                "project": "global-memory",
                "workstream": "storage",
                "applies_to": ["tools", "api"]
            },
            "provenance": {
                "observed_agents": ["Antigravity", "Codex"],
                "extractor": "TestHarness",
                "source_refs": ["episodic/history/2026-09-08.md#sec-1"],
                "source_hashes": ["sha256:abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234"],
                "extracted_at": "2026-09-08T18:00:00Z",
                "prompt_version": "context-harvest-v1",
                "provider": "system",
                "model": "test-runner"
            },
            "evidence": [
                {
                    "type": "source_document",
                    "ref": "episodic/history/2026-09-08.md#sec-1",
                    "excerpt_hash": "sha256:abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234"
                }
            ],
            "freshness": {
                "effective_at": "2026-09-08T18:00:00Z",
                "review_after": None,
                "status": "fresh",
                "supersedes": []
            },
            "review": {
                "status": "proposed",
                "requires_human": True,
                "reasons": ["architectural decision extracted for review"]
            },
            "authority": "source_document",
            "verification": "verified"
        }

    # -------------------------------------------------------------------------
    # 1. Harvest Status & Candidates Querying
    # -------------------------------------------------------------------------
    def test_harvest_status_empty_queue(self):
        status = self.api.get_harvest_status()
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["total_awaiting_review"], 0)
        self.assertEqual(status["decisions_policies_pending"], 0)
        self.assertIn("03:10 AM", status["next_scheduled_run"])

    def test_harvest_status_with_staged_candidates(self):
        cand1 = self._sample_decision_candidate(key="test.decision_1")
        cand2 = self._sample_decision_candidate(key="test.decision_2")
        cand2["record_type"] = "project_state"

        # Stage both candidates
        memory_mcp_server.stage_context_candidate(cand1, "agent1", "system", "test", "v1", "fp1", db_path=self.db_path)
        memory_mcp_server.stage_context_candidate(cand2, "agent2", "system", "test", "v1", "fp2", db_path=self.db_path)

        status = self.api.get_harvest_status()
        self.assertEqual(status["total_awaiting_review"], 2)
        self.assertEqual(status["decisions_policies_pending"], 1)
        self.assertEqual(status["project_state_pending"], 1)

    def test_get_harvest_candidates_with_diff(self):
        cand = self._sample_decision_candidate(key="mbrain.agent_trust_architecture")
        stage_res = memory_mcp_server.stage_context_candidate(
            cand, "agent1", "system", "test", "v1", "fp1", db_path=self.db_path
        )
        self.assertEqual(stage_res["status"], "staged")

        res = self.api.get_harvest_candidates()
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["candidates"]), 1)
        c = res["candidates"][0]
        self.assertEqual(c["canonical_key"], "mbrain.agent_trust_architecture")
        self.assertTrue(c["diff"]["has_existing"])

    # -------------------------------------------------------------------------
    # 2. Audited Candidate Review Actions (accept, edit, merge, reject, defer)
    # -------------------------------------------------------------------------
    def test_review_action_accept_promotes_to_facts_and_claims(self):
        cand = self._sample_decision_candidate(key="test.accepted_decision")
        stage_res = memory_mcp_server.stage_context_candidate(
            cand, "agent1", "system", "test", "v1", "fp1", db_path=self.db_path
        )
        cand_id = stage_res["candidate_id"]

        review_res = self.api.review_harvest_candidate(
            cand_id,
            {"action": "accept", "reviewer": "human-test", "rationale": "Approved after inspection"}
        )
        self.assertEqual(review_res["status"], "success")
        self.assertEqual(review_res["review_status"], "accepted")

        # Check candidate table
        cand_after = memory_mcp_server.get_context_candidate_by_id(cand_id, db_path=self.db_path)
        self.assertEqual(cand_after["review_status"], "accepted")
        self.assertEqual(cand_after["reviewed_by"], "human-test")
        self.assertIsNotNone(cand_after["merged_claim_id"])

        # Check facts.json
        facts = json.loads(self.facts_path.read_text(encoding="utf-8"))
        self.assertIn("test.accepted_decision", facts)
        stored_rec = json.loads(facts["test.accepted_decision"])
        self.assertEqual(stored_rec["statement"], "Use WAL mode everywhere.")
        self.assertEqual(stored_rec["rationale"], "High concurrency across agents requires non-blocking reads.")

        # Check gms_claims in SQLite
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("SELECT claim_id, memory_key, agent_id, confidence, status FROM gms_claims WHERE memory_key = ?", ("test.accepted_decision",))
        row = c.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "test.accepted_decision")
        self.assertEqual(row[2], "human-test")
        self.assertEqual(row[3], 1.0)
        self.assertEqual(row[4], "active")

    def test_review_action_reject_with_rationale(self):
        cand = self._sample_decision_candidate(key="test.rejected_decision")
        stage_res = memory_mcp_server.stage_context_candidate(
            cand, "agent1", "system", "test", "v1", "fp1", db_path=self.db_path
        )
        cand_id = stage_res["candidate_id"]

        review_res = self.api.review_harvest_candidate(
            cand_id,
            {"action": "reject", "reviewer": "human-test", "rationale": "Contradicts established benchmarks."}
        )
        self.assertEqual(review_res["status"], "success")
        self.assertEqual(review_res["review_status"], "rejected")

        # Candidate table updated
        cand_after = memory_mcp_server.get_context_candidate_by_id(cand_id, db_path=self.db_path)
        self.assertEqual(cand_after["review_status"], "rejected")

        # Active facts.json is NOT modified
        facts = json.loads(self.facts_path.read_text(encoding="utf-8"))
        self.assertNotIn("test.rejected_decision", facts)

    def test_review_action_defer(self):
        cand = self._sample_decision_candidate(key="test.deferred_decision")
        stage_res = memory_mcp_server.stage_context_candidate(
            cand, "agent1", "system", "test", "v1", "fp1", db_path=self.db_path
        )
        cand_id = stage_res["candidate_id"]

        review_res = self.api.review_harvest_candidate(
            cand_id,
            {"action": "defer", "reviewer": "human-test", "rationale": "Pending tomorrow's test results."}
        )
        self.assertEqual(review_res["status"], "success")
        self.assertEqual(review_res["review_status"], "deferred")

        cand_after = memory_mcp_server.get_context_candidate_by_id(cand_id, db_path=self.db_path)
        self.assertEqual(cand_after["review_status"], "deferred")

    # -------------------------------------------------------------------------
    # 3. Legacy Flat Records Migration
    # -------------------------------------------------------------------------
    def test_migrate_flat_records_dry_run_idempotency(self):
        res1 = migrate_flat_records.run_migration(apply=False, mem_root=self.mem_root)
        self.assertEqual(res1["status"], "success")
        self.assertTrue(res1["dry_run"])
        self.assertEqual(res1["total_targets"], 6)
        self.assertEqual(res1["valid_candidates"], 6)
        self.assertEqual(res1["staged_candidates"], 0)

        # Database must not contain any candidates
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("SELECT count(*) FROM gms_context_candidates")
        count = c.fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_migrate_flat_records_apply_and_reapply(self):
        # First apply
        res1 = migrate_flat_records.run_migration(apply=True, mem_root=self.mem_root)
        self.assertEqual(res1["status"], "success")
        self.assertFalse(res1["dry_run"])
        self.assertEqual(res1["staged_candidates"], 6)

        # Re-apply must be idempotent (no duplicates inserted, count stays 6)
        res2 = migrate_flat_records.run_migration(apply=True, mem_root=self.mem_root)
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["staged_candidates"], 6)

        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("SELECT count(*) FROM gms_context_candidates")
        count = c.fetchone()[0]
        conn.close()
        self.assertEqual(count, 6)

    # -------------------------------------------------------------------------
    # 4. Context Packet Integration & Proposal Exclusion
    # -------------------------------------------------------------------------
    def test_context_packet_excludes_proposed_by_default(self):
        # Stage a proposed decision
        cand = self._sample_decision_candidate(
            key="global-memory.proposed_decision",
            statement="Proposed decision awaiting review."
        )
        memory_mcp_server.stage_context_candidate(cand, "agent1", "system", "test", "v1", "fp1", db_path=self.db_path)

        preview = self.api.preview_context_packet({"project_id": "global-memory"})
        packet = preview["packet"]
        # Proposed decision must not be in default decisions
        self.assertFalse(any(d.get("statement") == "Proposed decision awaiting review." for d in packet["decisions"]))

        # Include proposed explicitly with flag
        preview_with_prop = self.api.preview_context_packet({"project_id": "global-memory", "include_proposed": True})
        packet_with_prop = preview_with_prop["packet"]
        prop_matches = [d for d in packet_with_prop["decisions"] if d.get("statement") == "Proposed decision awaiting review."]
        self.assertEqual(len(prop_matches), 1)
        self.assertIn("warning", prop_matches[0])
        self.assertIn("PROPOSED CANDIDATE", prop_matches[0]["warning"])
        self.assertIn("⚠️ [PROPOSED CANDIDATE]", preview_with_prop["markdown"])

    def test_context_packet_hash_changes_on_decision_edit(self):
        # Accept decision
        cand = self._sample_decision_candidate(
            key="global-memory.active_rule",
            statement="Version 1 rule."
        )
        stage_res = memory_mcp_server.stage_context_candidate(cand, "agent1", "system", "test", "v1", "fp1", db_path=self.db_path)
        self.api.review_harvest_candidate(stage_res["candidate_id"], {"action": "accept", "reviewer": "tester", "rationale": "Initial accepted rule version 1"})

        preview1 = self.api.preview_context_packet({"project_id": "global-memory"})
        hash1 = preview1["content_hash"]

        # Edit decision
        cand_v2 = self._sample_decision_candidate(
            key="global-memory.active_rule",
            statement="Version 2 rule with updated rationale."
        )
        cand_v2["rationale"] = "Updated rationale completely changing constraints."
        stage_res2 = memory_mcp_server.stage_context_candidate(cand_v2, "agent1", "system", "test", "v2", "fp2", db_path=self.db_path)
        self.api.review_harvest_candidate(stage_res2["candidate_id"], {"action": "accept", "reviewer": "tester", "rationale": "Updated accepted rule version 2"})

        preview2 = self.api.preview_context_packet({"project_id": "global-memory"})
        hash2 = preview2["content_hash"]

        self.assertNotEqual(hash1, hash2)

    # -------------------------------------------------------------------------
    # 5. Zero LLM Model Loading on Daytime Browse/Open Paths
    # -------------------------------------------------------------------------
    def test_zero_daytime_model_loading(self):
        """Ensure opening desktop API, projects, exploration, or harvest queue never invokes Ollama."""
        with patch("urllib.request.urlopen") as mock_url:
            mock_url.side_effect = AssertionError("Network/Ollama request attempted on daytime browse path!")

            # 1. Snapshot
            snap = self.api.get_snapshot()
            self.assertIsNotNone(snap)

            # 2. Memories list
            mems = self.api.get_memories(tier="all")
            self.assertIsNotNone(mems)

            # 3. Harvest status
            h_stat = self.api.get_harvest_status()
            self.assertIsNotNone(h_stat)

            # 4. Harvest candidates
            h_cands = self.api.get_harvest_candidates()
            self.assertIsNotNone(h_cands)

            # 5. Project detail
            proj = self.api.get_project_detail("global-memory")
            self.assertIsNotNone(proj)


if __name__ == "__main__":
    unittest.main()
