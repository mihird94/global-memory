import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = str(Path(__file__).parent.parent / "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import memory_mcp_server


class TestTaskHandoff(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_root = memory_mcp_server.MEM_ROOT
        self.old_db_path = memory_mcp_server.DB_PATH
        memory_mcp_server.MEM_ROOT = self.root
        memory_mcp_server.DB_PATH = self.root / "gms_trust.sqlite"
        memory_mcp_server.init_db()

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_root
        memory_mcp_server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def call(self, name, payload):
        result = memory_mcp_server.TOOLS[name]["fn"](payload)
        self.assertFalse(result.startswith("ERROR:"), result)
        return json.loads(result)

    def test_handoff_lifecycle_preserves_checkpoint_and_requires_fresh_revision(self):
        created = self.call("mem_task_create", {
            "task_id": "gms-handoff-1", "title": "Add handoff", "project": "global-memory",
            "objective": "Persist safe state transfer", "agent": "agent_a",
        })
        self.assertEqual(created["task"]["revision"], 1)

        claimed = self.call("mem_task_claim", {
            "task_id": "gms-handoff-1", "agent": "agent_a", "expected_revision": 1,
        })
        self.assertEqual(claimed["task"]["revision"], 2)
        self.assertEqual(claimed["task"]["owner_agent"], "agent_a")

        checkpointed = self.call("mem_task_checkpoint", {
            "task_id": "gms-handoff-1", "agent": "agent_a", "expected_revision": 2,
            "label": "implementation", "state": {"files_changed": ["tools/memory_mcp_server.py"]},
            "artifact_refs": ["/tmp/diff.patch"], "claim_refs": [42], "episode_refs": ["2026-07-13.md"],
        })
        self.assertEqual(checkpointed["task"]["revision"], 3)

        stale = json.loads(memory_mcp_server.tool_mem_handoff_create({
            "task_id": "gms-handoff-1", "source_agent": "agent_a", "expected_revision": 2,
        }))
        self.assertEqual(stale["status"], "conflict")

        handed_off = self.call("mem_handoff_create", {
            "task_id": "gms-handoff-1", "source_agent": "agent_a", "target_agent": "agent_b",
            "expected_revision": 3, "completed_work": "Implemented task tables.",
            "next_action": "Run the test suite.", "context": {"branch": "master"},
            "artifact_refs": ["/tmp/diff.patch"],
        })
        self.assertEqual(handed_off["task"]["status"], "handed_off")
        self.assertEqual(handed_off["task"]["revision"], 4)

        claimed_by_b = self.call("mem_task_claim", {
            "task_id": "gms-handoff-1", "agent": "agent_b", "expected_revision": 4,
        })
        self.assertEqual(claimed_by_b["task"]["revision"], 5)

        resumed = self.call("mem_task_resume", {"task_id": "gms-handoff-1"})
        self.assertEqual(resumed["checkpoint"]["state"]["files_changed"], ["tools/memory_mcp_server.py"])
        self.assertEqual(resumed["handoff"]["target_agent"], "agent_b")
        self.assertIsNotNone(resumed["handoff"]["acknowledged_at"])

    def test_project_state_returns_latest_work_without_completed_tasks_by_default(self):
        self.call("mem_task_create", {
            "task_id": "active", "title": "Active task", "project": "global-memory", "agent": "agent_a",
        })
        self.call("mem_task_create", {
            "task_id": "done", "title": "Done task", "project": "global-memory", "agent": "agent_a",
        })
        self.call("mem_task_claim", {"task_id": "done", "agent": "agent_a", "expected_revision": 1})
        self.call("mem_task_complete", {"task_id": "done", "agent": "agent_a", "expected_revision": 2})

        state = self.call("mem_project_state", {"project": "global-memory"})
        self.assertEqual([task["task_id"] for task in state["tasks"]], ["active"])

        all_state = self.call("mem_project_state", {"project": "global-memory", "include_completed": True})
        self.assertEqual({task["task_id"] for task in all_state["tasks"]}, {"active", "done"})

        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM gms_tasks").fetchone()[0], 2)
        conn.close()


if __name__ == "__main__":
    unittest.main()
