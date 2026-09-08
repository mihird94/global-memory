import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Add tools directory to sys.path
tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import gms_desktop_api
import memory_mcp_server


class TestGMSDesktopAPI(unittest.TestCase):
    def setUp(self):
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_mcp_db = memory_mcp_server.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        (self.mem_root / "semantic").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "operational").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "procedural").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "episodic" / "history").mkdir(parents=True, exist_ok=True)

        # Seed semantic facts
        (self.mem_root / "semantic" / "facts.json").write_text(json.dumps({
            "infra.node1": {"host": "node1", "ip": "192.168.1.10", "port": 22, "status": "online"},
            "general_note": "A general unstructured fact"
        }))

        # Seed journal
        (self.mem_root / "episodic" / "journal.md").write_text("# Session 1\nDiscussed architecture.\n")

        # Initialize DB
        memory_mcp_server.MEM_ROOT = self.mem_root
        memory_mcp_server.DB_PATH = self.mem_root / "gms_trust.sqlite"
        memory_mcp_server.init_db()

        self.api = gms_desktop_api.GMSDesktopAPI(mem_root=self.mem_root)

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_mcp_db
        self.temp_dir.cleanup()

    def test_get_snapshot(self):
        snap = self.api.get_snapshot()
        self.assertEqual(snap["memory_root"], str(self.mem_root))
        self.assertEqual(snap["facts"]["semantic"], 2)
        self.assertIn("db", snap)
        self.assertIn("platform", snap)
        self.assertIn("agent_reputations", snap)

    def test_get_memories(self):
        # All
        res_all = self.api.get_memories()
        self.assertGreaterEqual(res_all["total"], 3)

        # Filter by namespace
        res_ns = self.api.get_memories(namespace="infra.")
        self.assertEqual(res_ns["total"], 1)
        self.assertEqual(res_ns["memories"][0]["key"], "infra.node1")

        # Filter by query
        res_q = self.api.get_memories(query="node1")
        self.assertEqual(res_q["total"], 1)

    def test_validate_and_save_fact_schema_enforcement(self):
        # Invalid trading action
        invalid_payload = {"ticker": "NVDA", "action": "yolo", "price": 120.0}
        val_report = self.api.validate_memory_payload("trading.nvda", invalid_payload)
        self.assertFalse(val_report["valid"])
        self.assertIn("action", val_report["error"])

        save_res = self.api.save_fact("trading.nvda", invalid_payload)
        self.assertEqual(save_res["status"], "error")
        self.assertIn("Schema contract validation failed", save_res["message"])

        # Valid trading action (lowercase buy)
        valid_payload = {
            "ticker": "NVDA",
            "action": "buy",
            "price": 120.0,
            "stop_loss": 110.0,
            "target_price": 140.0,
            "timeframe": "swing",
            "thesis": "Breakout",
            "status": "open"
        }
        val_report2 = self.api.validate_memory_payload("trading.nvda", valid_payload)
        self.assertTrue(val_report2["valid"])

        save_res2 = self.api.save_fact("trading.nvda", valid_payload)
        self.assertIn(save_res2["status"], ("success", "warning"))
        self.assertEqual(save_res2["key"], "trading.nvda")

    def test_delete_fact(self):
        res = self.api.delete_fact("infra.node1")
        self.assertEqual(res["status"], "success")

        # Verify it is gone from semantic facts
        memories = self.api.get_memories(namespace="infra.")
        self.assertEqual(memories["total"], 0)

    def test_daily_note_lifecycle_and_harvest(self):
        date_str = "2026-09-08"
        content = "# Daily Note\n\n- [FACT:infra.compute_server] {\"host\": \"compute1\", \"ip\": \"10.0.0.5\", \"port\": 22, \"status\": \"online\"}\n"

        # Save note
        save_res = self.api.save_daily_note(date_str, content)
        self.assertEqual(save_res["status"], "success")

        # Retrieve note
        note = self.api.get_daily_note(date_str)
        self.assertTrue(note["exists"])
        self.assertIn("compute_server", note["content"])

        # Harvest ("Suck into GMS")
        harvest_res = self.api.harvest_daily_note(date_str)
        self.assertIn("status", harvest_res)
        self.assertGreaterEqual(harvest_res["total_extracted"], 1)
        self.assertGreaterEqual(len(harvest_res["saved_facts"]), 1)

    def test_graph_data_and_concepts(self):
        # Insert entity and relationship
        memory_mcp_server.tool_mem_upsert_entity({"name": "Server Alpha", "entity_type": "INFRA", "summary": "Primary cluster node"})
        memory_mcp_server.tool_mem_upsert_entity({"name": "Storage Pool", "entity_type": "INFRA", "summary": "Fast NVMe pool"})
        memory_mcp_server.record_graph_relationship("Server Alpha", "attached_to", "Storage Pool")

        graph = self.api.get_graph_data()
        self.assertGreaterEqual(len(graph["nodes"]), 2)
        self.assertGreaterEqual(len(graph["edges"]), 1)

        concepts = self.api.get_concepts()
        self.assertIn("INFRA", concepts["groups"])
        self.assertGreaterEqual(concepts["total_entities"], 2)

    def test_apple_reminders_structure(self):
        # Test structure returns graceful dictionary regardless of platform
        res = self.api.get_reminders()
        self.assertIn("supported", res)
        self.assertIn("reminders", res)
        self.assertIsInstance(res["reminders"], list)


if __name__ == "__main__":
    unittest.main()
