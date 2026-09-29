"""Unit tests for split-brain bidirectional store synchronization."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dream_cycle import sync_json_and_sqlite_claims
import memory_mcp_server


class TestStoreSynchronization(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "semantic").mkdir(parents=True, exist_ok=True)
        memory_mcp_server.init_db(self.root / "gms_trust.sqlite")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bidirectional_sync_reconciles_divergences(self):
        # 1. Populate SQLite with an active claim missing from facts.json
        conn = sqlite3.connect(str(self.root / "gms_trust.sqlite"))
        conn.execute("""
            INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, confidence, contradiction_type)
            VALUES ('semantic', 'cluster.leader_node', 'node-01', 'system', 'main', 'active', 0.95, 'initial')
        """)
        # Populate SQLite with a divergent value for existing key
        conn.execute("""
            INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, confidence, contradiction_type)
            VALUES ('semantic', 'api.version', 'v2.5', 'system', 'main', 'active', 0.95, 'initial')
        """)
        conn.commit()
        conn.close()

        # 2. Populate facts.json with a divergent value and an un-claimed fact
        facts_path = self.root / "semantic" / "facts.json"
        facts_path.write_text(json.dumps({
            "api.version": "v1.0",
            "offline.flag": "true"
        }, indent=2))

        # 3. Run sync
        report = sync_json_and_sqlite_claims(self.root)
        self.assertEqual(report["status"], "synchronized")
        self.assertGreater(report["divergences_resolved"], 0)

        # 4. Verify facts.json updated with SQLite active claims
        synced_facts = json.loads(facts_path.read_text())
        self.assertEqual(synced_facts["cluster.leader_node"], "node-01")
        self.assertEqual(synced_facts["api.version"], "v2.5")
        self.assertEqual(synced_facts["offline.flag"], "true")

        # 5. Verify SQLite claims table received un-claimed fact
        conn = sqlite3.connect(str(self.root / "gms_trust.sqlite"))
        row = conn.execute("SELECT value, status FROM gms_claims WHERE memory_key='offline.flag' AND status='active'").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "true")

        # 6. Verify subsequent run is a no-op (idempotent)
        repeat = sync_json_and_sqlite_claims(self.root)
        self.assertEqual(repeat["divergences_resolved"], 0)


if __name__ == "__main__":
    unittest.main()
