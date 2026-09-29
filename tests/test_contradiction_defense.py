"""Unit tests for contradiction defense, exact conflict quarantine, and trust beta updates."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import memory_mcp_server


class TestContradictionDefense(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_db_path = memory_mcp_server.DB_PATH

        memory_mcp_server.MEM_ROOT = self.temp_path
        memory_mcp_server.DB_PATH = self.temp_path / "gms_trust.sqlite"
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "operational").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "procedural").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "logs").mkdir(parents=True, exist_ok=True)
        memory_mcp_server.init_db()

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_exact_conflict_is_quarantined_and_preserves_incumbent(self):
        # 1. Incumbent agent with established trust writes fact
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        conn.execute("INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES ('deploy_bot_alpha', 12.0, 0.0)")
        conn.execute("INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES ('rogue_bot', 1.0, 3.0)")
        conn.commit()
        conn.close()

        res1 = memory_mcp_server.tool_mem_save_typed({
            "key": "deploy_target",
            "value": "aws-east",
            "kind": "semantic",
            "agent": "deploy_bot_alpha"
        })
        self.assertIn("Fact saved", res1)

        # 2. Rogue agent with lower trust attempts to overwrite with contradictory value
        res2 = memory_mcp_server.tool_mem_save_typed({
            "key": "deploy_target",
            "value": "compromised-server",
            "kind": "semantic",
            "agent": "rogue_bot"
        })
        self.assertIn("CONFLICT/QUARANTINE", res2)

        # 3. Verify facts.json still holds incumbent value
        facts = json.loads((self.temp_path / "semantic" / "facts.json").read_text())
        self.assertEqual(facts["deploy_target"], "aws-east")

        # 4. Verify rogue claim was recorded as quarantined
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        claims = conn.execute("SELECT claim_id, agent_id, status FROM gms_claims WHERE memory_key='deploy_target' ORDER BY claim_id ASC").fetchall()
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0][1], "deploy_bot_alpha")
        self.assertEqual(claims[0][2], "active")
        self.assertEqual(claims[1][1], "rogue_bot")
        self.assertEqual(claims[1][2], "quarantined")

        # 5. Verify rogue agent beta reputation was incremented
        rep = conn.execute("SELECT alpha, beta FROM gms_agent_reputation WHERE agent_id='rogue_bot'").fetchone()
        conn.close()
        self.assertGreater(rep[1], 3.0)

    def test_same_owner_can_update_with_temporal_invalidation(self):
        # 1. Agent writes fact
        memory_mcp_server.tool_mem_save_typed({
            "key": "feature_flag",
            "value": "disabled",
            "kind": "operational",
            "agent": "feature_manager"
        })

        # 2. Same agent updates the feature flag
        res = memory_mcp_server.tool_mem_save_typed({
            "key": "feature_flag",
            "value": "enabled",
            "kind": "operational",
            "agent": "feature_manager"
        })
        self.assertIn("Fact saved", res)

        # 3. Operational facts.json reflects update
        facts = json.loads((self.temp_path / "operational" / "facts.json").read_text())
        self.assertEqual(facts["feature_flag"], "enabled")

        # 4. Old claim is superseded, new claim is active
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        claims = conn.execute("SELECT value, status, contradiction_type FROM gms_claims WHERE memory_key='feature_flag' ORDER BY claim_id ASC").fetchall()
        conn.close()
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0][1], "superseded")
        self.assertEqual(claims[1][1], "active")
        self.assertEqual(claims[1][2], "temporal_invalidation")

    def test_protected_policy_namespace_blocks_unauthorized_overwrite(self):
        policy_payload = {
            "rule_name": "max_position_size",
            "action": "allow",
            "description": "Max position size is 5000"
        }

        # 1. Operator writes policy
        res1 = memory_mcp_server.tool_mem_save_typed({
            "key": "policy:max_position_size",
            "value": policy_payload,
            "kind": "operational",
            "agent": "mihir"
        })
        self.assertIn("Fact saved", res1)

        # 2. Non-operator agent attempts to overwrite policy with another valid payload
        exploit_payload = {
            "rule_name": "max_position_size",
            "action": "allow",
            "description": "Bypassing risk limit to 500000"
        }
        res2 = memory_mcp_server.tool_mem_save_typed({
            "key": "policy:max_position_size",
            "value": exploit_payload,
            "kind": "operational",
            "agent": "automated_trader"
        })
        self.assertIn("CONFLICT/QUARANTINE", res2)
        self.assertIn("Protected namespace", res2)

        # 3. Policy is preserved
        facts = json.loads((self.temp_path / "operational" / "facts.json").read_text())
        self.assertEqual(facts["policy:max_position_size"]["description"], "Max position size is 5000")


if __name__ == "__main__":
    unittest.main()
