import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

temp_dir = os.environ.get("MEMORY_ROOT")
if not temp_dir:
    temp_dir = tempfile.mkdtemp()
    os.environ["MEMORY_ROOT"] = temp_dir

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import memory_mcp_server


class TestQuarantineReviews(unittest.TestCase):
    def setUp(self):
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        (self.temp_path / "operational").mkdir(parents=True, exist_ok=True)
        memory_mcp_server.MEM_ROOT = self.temp_path
        memory_mcp_server.DB_PATH = self.temp_path / "gms_trust.sqlite"
        memory_mcp_server.init_db()

    def get_db_connection(self):
        return sqlite3.connect(str(self.temp_path / "gms_trust.sqlite"))

    def _set_reputation(self, agent_id: str, alpha: float, beta: float):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            (agent_id, alpha, beta),
        )
        conn.commit()
        conn.close()

    def _create_quarantined_operational_claim(self):
        self._set_reputation("agent_trusted", 10.0, 0.0)
        self._set_reputation("agent_untrusted", 1.0, 5.0)
        self._set_reputation("reviewer_support", 12.0, 0.0)
        self._set_reputation("reviewer_reject", 1.0, 8.0)
        self._set_reputation("reviewer_abstain", 3.0, 1.0)

        res1 = memory_mcp_server.tool_mem_save_typed({
            "key": "shared_config",
            "value": "trusted_value",
            "kind": "operational",
            "agent": "agent_trusted",
        })
        self.assertIn("saved", res1.lower())

        res2 = memory_mcp_server.tool_mem_save_typed({
            "key": "shared_config",
            "value": "candidate_value",
            "kind": "operational",
            "agent": "agent_untrusted",
        })
        self.assertIn("CONFLICT/QUARANTINE", res2)

    def test_weighted_recommendation_and_cleanup(self):
        self._create_quarantined_operational_claim()

        res_support = memory_mcp_server.tool_mem_record_review({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
            "reviewer_id": "reviewer_support",
            "rating": "endorse",
            "rationale": "High-confidence corroboration.",
        })
        self.assertIn("SUCCESS", res_support)

        res_reject = memory_mcp_server.tool_mem_record_review({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
            "reviewer_id": "reviewer_reject",
            "rating": "reject",
            "rationale": "Conflicts with prior rollout.",
        })
        self.assertIn("SUCCESS", res_reject)

        res_abstain = memory_mcp_server.tool_mem_record_review({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
            "reviewer_id": "reviewer_abstain",
            "rating": "abstain",
            "rationale": "Insufficient evidence.",
        })
        self.assertIn("SUCCESS", res_abstain)

        summary = json.loads(memory_mcp_server.tool_mem_get_recommendation_summary({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
        }))
        self.assertEqual(summary["reviewer_count"], 3)
        self.assertEqual(summary["recommendation"], "promote")
        self.assertGreater(summary["endorse_weight"], summary["reject_weight"])
        self.assertGreater(summary["abstain_weight"], 0.0)

        resolve = memory_mcp_server.tool_mem_resolve_quarantine({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
            "action": "promote",
            "agent": "admin",
        })
        self.assertIn("SUCCESS", resolve)
        self.assertIn("Recommendation: promote", resolve)
        self.assertIn("Reviewers: 3", resolve)

        reviews = json.loads(memory_mcp_server.tool_mem_get_reviews({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
        }))
        self.assertEqual(reviews, [])

        reps = json.loads(memory_mcp_server.tool_mem_get_reputations({}))
        rep_by_agent = {row["agent_id"]: row for row in reps}
        self.assertGreater(rep_by_agent["reviewer_support"]["alpha"], 12.0)
        self.assertGreater(rep_by_agent["reviewer_reject"]["beta"], 8.0)
        self.assertEqual(rep_by_agent["reviewer_abstain"]["alpha"], 3.0)
        self.assertEqual(rep_by_agent["reviewer_abstain"]["beta"], 1.0)

    def test_duplicate_reviewer_updates_existing_review(self):
        self._create_quarantined_operational_claim()

        first = memory_mcp_server.tool_mem_record_review({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
            "reviewer_id": "reviewer_support",
            "rating": "endorse",
            "rationale": "Initial review.",
        })
        self.assertIn("SUCCESS", first)

        second = memory_mcp_server.tool_mem_record_review({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
            "reviewer_id": "reviewer_support",
            "rating": "reject",
            "rationale": "Changed after new evidence.",
        })
        self.assertIn("SUCCESS", second)

        reviews = json.loads(memory_mcp_server.tool_mem_get_reviews({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
        }))
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["reviewer_id"], "reviewer_support")
        self.assertEqual(reviews[0]["rating"], "reject")
        self.assertEqual(reviews[0]["rationale"], "Changed after new evidence.")

    def test_review_requires_existing_quarantine(self):
        res = memory_mcp_server.tool_mem_record_review({
            "key": "operational:missing",
            "agent_id": "ghost_agent",
            "reviewer_id": "reviewer_support",
            "rating": "endorse",
        })
        self.assertIn("ERROR", res)


if __name__ == "__main__":
    unittest.main()
