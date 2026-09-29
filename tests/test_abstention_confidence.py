"""Unit tests for calibrated abstention and retrieval confidence scoring."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from context_retrieval_planner import retrieve, make_plan, RetrievalConfig
import memory_mcp_server


class TestAbstentionConfidence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "semantic").mkdir(parents=True, exist_ok=True)
        memory_mcp_server.init_db(self.root / "gms_trust.sqlite")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unsupported_query_triggers_abstention(self):
        # Memory is empty, query for unknown concept
        res = retrieve(self.root, "quantum teleportation crystal protocol")
        self.assertEqual(res["evidence_status"], "insufficient")
        self.assertLess(res["retrieval_confidence"], 0.40)
        self.assertTrue(res["abstention_recommended"])
        self.assertIn("insufficient", res["abstention_reason"].lower())
        self.assertFalse(res["actionable"])

    def test_supported_corroborated_query_yields_high_confidence(self):
        # Save a fact into facts.json and as an active claim
        (self.root / "semantic" / "facts.json").write_text(json.dumps({
            "database.engine": "PostgreSQL 16 distributed cluster"
        }))
        conn = sqlite3.connect(str(self.root / "gms_trust.sqlite"))
        conn.execute("""
            INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, confidence, contradiction_type)
            VALUES ('semantic', 'database.engine', 'PostgreSQL 16 distributed cluster', 'system', 'main', 'active', 0.95, 'initial')
        """)
        conn.commit()
        conn.close()

        res = retrieve(self.root, "database engine cluster")
        self.assertEqual(res["evidence_status"], "supported")
        self.assertGreater(res["retrieval_confidence"], 0.40)
        self.assertFalse(res["abstention_recommended"])
        self.assertTrue(res["actionable"])


if __name__ == "__main__":
    unittest.main()
