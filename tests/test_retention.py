import argparse
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

temp_dir = os.environ.get("MEMORY_ROOT")
if not temp_dir:
    temp_dir = tempfile.mkdtemp()
    os.environ["MEMORY_ROOT"] = temp_dir

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import dream_cycle
import memory_mcp_server
import memoryctl


class TestRetentionPruning(unittest.TestCase):
    def setUp(self):
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "episodic" / "history").mkdir(parents=True, exist_ok=True)

        self.old_mem_root_server = memory_mcp_server.MEM_ROOT
        self.old_db_path_server = memory_mcp_server.DB_PATH
        self.old_mem_root_dream = dream_cycle.MEM_ROOT
        self.old_mem_root_ctl = memoryctl.MEM_ROOT

        memory_mcp_server.MEM_ROOT = self.temp_path
        memory_mcp_server.DB_PATH = self.temp_path / "gms_trust.sqlite"
        dream_cycle.MEM_ROOT = self.temp_path
        memoryctl.MEM_ROOT = self.temp_path

        memory_mcp_server.init_db()

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mem_root_server
        memory_mcp_server.DB_PATH = self.old_db_path_server
        dream_cycle.MEM_ROOT = self.old_mem_root_dream
        memoryctl.MEM_ROOT = self.old_mem_root_ctl

    def get_db_connection(self):
        return sqlite3.connect(str(self.temp_path / "gms_trust.sqlite"))

    def test_low_confidence_active_claim_is_archived_and_removed_from_facts(self):
        facts_path = self.temp_path / "semantic" / "facts.json"
        facts_path.write_text(json.dumps({"stale_fact": "old_value"}, indent=2))

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO gms_claims (
                memory_kind, memory_key, value, agent_id, branch, status,
                supersedes_claim_id, confidence, contradiction_type, created_at
            ) VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, NULL, ?)
            """,
            ("semantic", "stale_fact", "old_value", "agent_old", "main", 0.2, "2026-04-01 00:00:00"),
        )
        cursor.execute(
            """
            INSERT INTO gms_fact_provenance (fact_key, agent_id, branch, quarantined, timestamp)
            VALUES (?, ?, ?, 0, ?)
            """,
            ("stale_fact", "agent_old", "main", "2026-04-01 00:00:00"),
        )
        conn.commit()
        conn.close()

        now = datetime(2026, 6, 4, 12, 0, 0)
        report = dream_cycle.generate_retention_report(
            self.temp_path / "gms_trust.sqlite",
            now=now,
            low_confidence_threshold=0.3,
            stale_active_days=30,
            stale_quarantine_days=14,
        )
        self.assertEqual(report["summary"]["active_claim_candidates"], 1)

        applied = dream_cycle.run_retention_pruning(
            now=now,
            low_confidence_threshold=0.3,
            stale_active_days=30,
            stale_quarantine_days=14,
        )
        self.assertEqual(applied["applied"]["archived_active_claims"], 1)

        facts = json.loads(facts_path.read_text())
        self.assertNotIn("stale_fact", facts)

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, confidence FROM gms_claims WHERE memory_key = 'stale_fact'")
        status, confidence = cursor.fetchone()
        self.assertEqual(status, "archived")
        self.assertEqual(confidence, 0.0)
        cursor.execute("SELECT 1 FROM gms_fact_provenance WHERE fact_key = 'stale_fact'")
        self.assertIsNone(cursor.fetchone())
        conn.close()

    def test_stale_quarantine_is_discarded_and_reviews_are_flushed(self):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO gms_quarantined_facts (fact_key, value, agent_id, branch, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("operational:queued_change", "candidate", "agent_untrusted", "main", "2026-05-01 00:00:00"),
        )
        cursor.execute(
            """
            INSERT INTO gms_claims (
                memory_kind, memory_key, value, agent_id, branch, status,
                supersedes_claim_id, confidence, contradiction_type, created_at
            ) VALUES (?, ?, ?, ?, ?, 'quarantined', NULL, ?, 'exact_conflict', ?)
            """,
            ("operational", "queued_change", "candidate", "agent_untrusted", "main", 0.2, "2026-05-01 00:00:00"),
        )
        cursor.execute(
            """
            INSERT INTO gms_quarantine_reviews (fact_key, agent_id, reviewer_id, rating, rationale, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("operational:queued_change", "agent_untrusted", "reviewer_one", "endorse", "Maybe okay", "2026-05-02 00:00:00"),
        )
        conn.commit()
        conn.close()

        now = datetime(2026, 6, 4, 12, 0, 0)
        applied = dream_cycle.run_retention_pruning(
            now=now,
            low_confidence_threshold=0.3,
            stale_active_days=30,
            stale_quarantine_days=14,
        )
        self.assertEqual(applied["applied"]["discarded_quarantines"], 1)

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM gms_quarantined_facts")
        self.assertIsNone(cursor.fetchone())
        cursor.execute("SELECT 1 FROM gms_quarantine_reviews")
        self.assertIsNone(cursor.fetchone())
        cursor.execute("SELECT status, confidence FROM gms_claims WHERE memory_key = 'queued_change'")
        status, confidence = cursor.fetchone()
        self.assertEqual(status, "discarded")
        self.assertEqual(confidence, 0.0)
        conn.close()

    def test_cli_retention_report_outputs_json(self):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO gms_claims (
                memory_kind, memory_key, value, agent_id, branch, status,
                supersedes_claim_id, confidence, contradiction_type, created_at
            ) VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, NULL, ?)
            """,
            ("semantic", "stale_fact", "old_value", "agent_old", "main", 0.2, "2026-04-01 00:00:00"),
        )
        conn.commit()
        conn.close()

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = memoryctl.cmd_retention_report(
                argparse.Namespace(
                    low_confidence=0.3,
                    stale_active_days=30,
                    stale_quarantine_days=14,
                    json=True,
                )
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["summary"]["active_claim_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
