import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import gms_tui
import memory_mcp_server
import memoryctl


class TestGMSTui(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "gms_trust.sqlite"

        self.old_tui_root = gms_tui.MEM_ROOT
        self.old_tui_db = gms_tui.DB_PATH
        self.old_server_root = memory_mcp_server.MEM_ROOT
        self.old_server_db = memory_mcp_server.DB_PATH
        self.old_ctl_root = memoryctl.MEM_ROOT

        gms_tui.MEM_ROOT = self.root
        gms_tui.DB_PATH = self.db_path
        memory_mcp_server.MEM_ROOT = self.root
        memory_mcp_server.DB_PATH = self.db_path
        memoryctl.MEM_ROOT = self.root

        (self.root / "semantic").mkdir(parents=True, exist_ok=True)
        (self.root / "operational").mkdir(parents=True, exist_ok=True)
        (self.root / "procedural").mkdir(parents=True, exist_ok=True)
        (self.root / "episodic" / "history").mkdir(parents=True, exist_ok=True)
        (self.root / "semantic" / "facts.json").write_text(json.dumps({"a": "1"}))
        (self.root / "operational" / "facts.json").write_text(json.dumps({"cfg": "x"}))
        memory_mcp_server.init_db()

    def tearDown(self):
        gms_tui.MEM_ROOT = self.old_tui_root
        gms_tui.DB_PATH = self.old_tui_db
        memory_mcp_server.MEM_ROOT = self.old_server_root
        memory_mcp_server.DB_PATH = self.old_server_db
        memoryctl.MEM_ROOT = self.old_ctl_root
        self.temp_dir.cleanup()

    def _seed_quarantine(self):
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO gms_quarantined_facts (fact_key, value, agent_id, branch, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("semantic:secret_key", "bad", "agent_bad", "main", "2026-06-04 12:00:00"),
        )
        cursor.execute(
            """
            INSERT INTO gms_claims (
                memory_kind, memory_key, value, agent_id, branch, status,
                supersedes_claim_id, confidence, contradiction_type, created_at
            ) VALUES (?, ?, ?, ?, ?, 'quarantined', NULL, ?, 'exact_conflict', ?)
            """,
            ("semantic", "secret_key", "bad", "agent_bad", "main", 0.2, "2026-06-04 12:00:00"),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("reviewer_one", 10.0, 0.0),
        )
        conn.commit()
        conn.close()

    def test_load_dashboard_data_returns_expected_sections(self):
        self._seed_quarantine()
        data = gms_tui.load_dashboard_data()
        self.assertIn("snapshot", data)
        self.assertIn("quarantines", data)
        self.assertIn("reputations", data)
        self.assertIn("claims", data)
        self.assertEqual(data["snapshot"]["facts"]["semantic"], 1)
        self.assertEqual(len(data["quarantines"]), 1)

    def test_review_and_resolve_helpers_delegate_to_mcp_server(self):
        item = {"fact_key": "semantic:secret_key", "agent_id": "agent_bad"}
        with patch.object(memory_mcp_server, "tool_mem_record_review", return_value="SUCCESS: review") as mock_review:
            res = gms_tui.review_quarantine_item(item, "endorse", reviewer="tester", rationale="ok")
        self.assertIn("SUCCESS", res)
        mock_review.assert_called_once()

        with patch.object(memory_mcp_server, "tool_mem_resolve_quarantine", return_value="SUCCESS: resolve") as mock_resolve:
            res = gms_tui.resolve_quarantine_item(item, "promote", resolver="tester")
        self.assertIn("SUCCESS", res)
        mock_resolve.assert_called_once()

    def test_memoryctl_tui_command_invokes_tui_main(self):
        with patch("gms_tui.main", return_value=0) as mock_main:
            code = memoryctl.cmd_tui(None)
        self.assertEqual(code, 0)
        mock_main.assert_called_once()


if __name__ == "__main__":
    unittest.main()
