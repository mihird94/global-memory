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

    def test_filter_items_substring(self):
        items = [
            {"agent_id": "agent_alpha", "branch": "main", "value": "val1", "fact_key": "semantic:k1"},
            {"agent_id": "agent_beta", "branch": "dev", "value": "val2", "fact_key": "operational:k2"},
        ]
        # Plain substring search
        res1 = gms_tui.filter_items(items, "alpha")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["agent_id"], "agent_alpha")

        res2 = gms_tui.filter_items(items, "dev")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["branch"], "dev")

        # Prefix search
        res3 = gms_tui.filter_items(items, "agent:beta")
        self.assertEqual(len(res3), 1)
        self.assertEqual(res3[0]["agent_id"], "agent_beta")

        res4 = gms_tui.filter_items(items, "branch:main")
        self.assertEqual(len(res4), 1)
        self.assertEqual(res4[0]["branch"], "main")

        res5 = gms_tui.filter_items(items, "key:k1")
        self.assertEqual(len(res5), 1)
        self.assertEqual(res5[0]["fact_key"], "semantic:k1")

    def test_tab_region_hit_testing(self):
        regions = gms_tui.compute_tab_regions(("Summary", "Quarantine", "Trust", "Claims"))
        self.assertEqual(gms_tui.find_tab_index_at_x(regions[0]["x_start"], regions), 0)
        self.assertEqual(gms_tui.find_tab_index_at_x(regions[1]["x_start"], regions), 1)
        self.assertEqual(gms_tui.find_tab_index_at_x(regions[3]["x_end"], regions), 3)
        self.assertIsNone(gms_tui.find_tab_index_at_x(0, regions))

    def test_list_row_hit_testing(self):
        self.assertEqual(gms_tui.find_list_index_at_y(6, 5, 3, 0), 1)
        self.assertEqual(gms_tui.find_list_index_at_y(8, 5, 4, 10), 13)
        self.assertIsNone(gms_tui.find_list_index_at_y(4, 5, 3, 0))
        self.assertIsNone(gms_tui.find_list_index_at_y(9, 5, 3, 0))

    def test_get_quarantine_detail_and_formatting(self):
        self._seed_quarantine()
        items = gms_tui.load_dashboard_data()["quarantines"]
        self.assertEqual(len(items), 1)
        
        detail = gms_tui.get_quarantine_detail(items[0])
        self.assertEqual(detail["item"]["fact_key"], "semantic:secret_key")
        self.assertIsNotNone(detail["proposing_agent_trust"])
        
        lines = gms_tui.format_quarantine_detail_lines(detail, 80)
        self.assertTrue(any("semantic:secret_key" in l for l in lines))
        self.assertTrue(any("agent_bad" in l for l in lines))

    def test_get_quarantine_detail_with_conflict(self):
        self._seed_quarantine()
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO gms_claims (
                memory_kind, memory_key, value, agent_id, branch, status,
                supersedes_claim_id, confidence, contradiction_type, created_at
            ) VALUES (?, ?, ?, ?, ?, 'active', NULL, 0.9, 'none', '2026-06-04 11:00:00')
            """,
            ("semantic", "secret_key", "good_value", "agent_good", "main"),
        )
        conn.commit()
        conn.close()

        items = gms_tui.load_dashboard_data()["quarantines"]
        detail = gms_tui.get_quarantine_detail(items[0])
        self.assertIsNotNone(detail["conflicting_claim"])
        self.assertEqual(detail["conflicting_claim"]["value"], "good_value")
        
        lines = gms_tui.format_quarantine_detail_lines(detail, 80)
        self.assertTrue(any("Conflicting Active Fact" in l for l in lines))
        self.assertTrue(any("good_value" in l for l in lines))

    def test_get_claim_detail_and_formatting(self):
        self._seed_quarantine()
        claims = gms_tui.load_dashboard_data()["claims"]
        self.assertEqual(len(claims), 1)
        
        detail = gms_tui.get_claim_detail(claims[0])
        self.assertEqual(detail["claim"]["memory_key"], "secret_key")
        
        lines = gms_tui.format_claim_detail_lines(detail, 80)
        self.assertTrue(any("#1" in l or "secret_key" in l for l in lines))

    def test_format_selected_claim_detail(self):
        # Test empty/None claim case
        none_lines = gms_tui.format_selected_claim_detail(None, 80)
        self.assertEqual(none_lines, ["No claim selected."])

        # Test valid claim formatting
        claim = {
            "claim_id": 42,
            "memory_kind": "semantic",
            "memory_key": "test_key",
            "value": "test_value",
            "agent_id": "test_agent",
            "branch": "test_branch",
            "status": "active",
            "confidence": 0.856,
            "contradiction_type": "exact_conflict",
            "created_at": "2026-06-04 20:00:00"
        }
        lines = gms_tui.format_selected_claim_detail(claim, 80)
        self.assertTrue(any("ID:          #42" in l for l in lines))
        self.assertTrue(any("Key:         semantic:test_key" in l for l in lines))
        f_val = [l for l in lines if "Value:" in l][0]
        self.assertIn("test_value", f_val)
        self.assertTrue(any("Agent:       test_agent (Branch: test_branch)" in l for l in lines))
        self.assertTrue(any("Status:      ACTIVE" in l for l in lines))
        self.assertTrue(any("Confidence:  0.86" in l for l in lines))
        self.assertTrue(any("Conflict:    exact_conflict" in l for l in lines))
        self.assertTrue(any("Created:     2026-06-04 20:00:00" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
