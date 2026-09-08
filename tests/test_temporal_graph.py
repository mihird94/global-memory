import json
import os
import sys
import unittest
import tempfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import memory_mcp_server


class TestTemporalGraph(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_db_path = memory_mcp_server.DB_PATH
        memory_mcp_server.MEM_ROOT = self.temp_path
        memory_mcp_server.DB_PATH = self.temp_path / "gms_trust.sqlite"
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "episodic" / "history").mkdir(parents=True, exist_ok=True)
        memory_mcp_server.init_db()

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_single_valued_predicate_invalidation(self):
        t0 = (datetime.now() - timedelta(hours=2)).isoformat()
        t1 = (datetime.now() - timedelta(hours=1)).isoformat()

        # 1. First record Optimus targets AlphaSignal_v1 at t0
        rel1 = memory_mcp_server.record_graph_relationship(
            "Optimus", "targets", "AlphaSignal_v1", valid_from=t0
        )
        self.assertTrue(rel1 > 0)

        # 2. Second record Optimus targets AlphaSignal_v2 at t1 (predicate 'targets' is single-valued)
        rel2 = memory_mcp_server.record_graph_relationship(
            "Optimus", "targets", "AlphaSignal_v2", valid_from=t1
        )
        self.assertTrue(rel2 > 0)

        # Check DB state directly
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT relationship_id, valid_from, valid_to FROM gms_relationships WHERE relationship_id = ?", (rel1,))
        r1_row = cursor.fetchone()
        cursor.execute("SELECT relationship_id, valid_from, valid_to FROM gms_relationships WHERE relationship_id = ?", (rel2,))
        r2_row = cursor.fetchone()
        conn.close()

        # rel1 must have valid_to set to t1 (invalidated!)
        self.assertEqual(r1_row[2], t1)
        # rel2 must be currently active (valid_to is NULL)
        self.assertIsNone(r2_row[2])

        # 3. Active graph query must only contain AlphaSignal_v2
        active_graph = memory_mcp_server.query_entity_graph("Optimus", hops=1)
        targets = [e["object"] for e in active_graph["edges"] if e["predicate"] == "targets"]
        self.assertEqual(targets, ["AlphaSignal_v2"])

        # 4. History query (include_expired=True) must contain both
        history_graph = memory_mcp_server.query_entity_graph("Optimus", hops=1, include_expired=True)
        all_targets = [e["object"] for e in history_graph["edges"] if e["predicate"] == "targets"]
        self.assertIn("AlphaSignal_v1", all_targets)
        self.assertIn("AlphaSignal_v2", all_targets)

    def test_explicit_invalidation(self):
        memory_mcp_server.record_graph_relationship("Server", "status", "running")
        # Invalidate status
        inv_count = memory_mcp_server.invalidate_graph_relationship("Server", "status")
        self.assertEqual(inv_count, 1)

        # Query active graph: Server should have no active status edge
        active = memory_mcp_server.query_entity_graph("Server", hops=1)
        status_edges = [e for e in active["edges"] if e["predicate"] == "status"]
        self.assertEqual(len(status_edges), 0)

    def test_multi_valued_predicates_coexist(self):
        # Multi-valued predicates like 'uses' or 'depends_on' should coexist
        memory_mcp_server.record_graph_relationship("Antigravity", "uses", "Python")
        memory_mcp_server.record_graph_relationship("Antigravity", "uses", "SQLite")

        active = memory_mcp_server.query_entity_graph("Antigravity", hops=1)
        uses = [e["object"] for e in active["edges"] if e["predicate"] == "uses"]
        self.assertIn("Python", uses)
        self.assertIn("SQLite", uses)


if __name__ == "__main__":
    unittest.main()
