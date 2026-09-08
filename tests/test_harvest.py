import json
import os
import sys
import unittest
import tempfile
import sqlite3
from pathlib import Path

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import memory_mcp_server
import harvest


class TestHarvest(unittest.TestCase):
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

    def test_harvest_session_extracts_facts_and_triples(self):
        sample_text = (
            "Session work complete:\n"
            "- [FACT:infra.mac] {\"host\": \"mac-m4\", \"port\": 22, \"role\": \"workstation\"}\n"
            "- Optimus depends on AlphaSignal for swing triggers\n"
            "- AlphaOS targets production trading\n"
        )
        report = harvest.harvest_session(
            agent="Antigravity",
            summary="Deployed upgraded infrastructure node and connected swing triggers",
            text=sample_text,
            incremental_index=False,
            mem_root=self.temp_path
        )

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["agent"], "Antigravity")

        # 1. Fact must be saved
        facts_file = self.temp_path / "semantic" / "facts.json"
        self.assertTrue(facts_file.exists())
        facts = json.loads(facts_file.read_text())
        self.assertIn("infra.mac", facts)

        # 2. Triples must be recorded in Knowledge Graph
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM gms_relationships")
        rel_count = cursor.fetchone()[0]
        self.assertTrue(rel_count > 0)
        conn.close()

        # 3. Proposing agent alpha should be boosted
        trust = memory_mcp_server.get_agent_trust("Antigravity")
        self.assertTrue(trust > 0.5)

    def test_session_end_micro_consolidation(self):
        sample_summary = "Refactored memory server with bi-temporal edges"
        res = memory_mcp_server.tool_mem_session_end({
            "agent": "Codex",
            "summary": sample_summary
        })
        self.assertIn("Session end logged", res)
        self.assertIn("Agentic Sleep Harvest", res)


if __name__ == "__main__":
    unittest.main()
