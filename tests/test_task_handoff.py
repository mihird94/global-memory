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
        # Complete the task at revision 5
        completed = self.call("mem_task_complete", {
            "task_id": "gms-handoff-1", "agent": "agent_b", "expected_revision": 5,
        })
        self.assertEqual(completed["task"]["status"], "completed")
        self.assertEqual(completed["task"]["revision"], 6)

    def test_full_continuity_lifecycle_with_blockers_and_criteria_survival(self):
        """Proves task create -> claim -> checkpoint -> handoff -> targeted claim -> resume -> complete."""
        import task_readiness

        # Initial readiness check on empty project
        readiness_empty = task_readiness.check_task_readiness(self.root, project="global-memory")
        self.assertFalse(readiness_empty["ready"])
        self.assertFalse(readiness_empty["quality_gate_eligible"])

        # 1. Create
        created = self.call("mem_task_create", {
            "task_id": "task-life-1", "title": "Implement Pass 10", "project": "global-memory",
            "objective": "Live context integrity", "agent": "codex",
        })
        self.assertEqual(created["task"]["revision"], 1)

        # 2. Claim
        claimed = self.call("mem_task_claim", {
            "task_id": "task-life-1", "agent": "codex", "expected_revision": 1,
        })
        self.assertEqual(claimed["task"]["revision"], 2)
        self.assertEqual(claimed["task"]["owner_agent"], "codex")

        # Concurrency enforcement: stale revision claim fails
        stale_claim = json.loads(memory_mcp_server.tool_mem_task_claim({
            "task_id": "task-life-1", "agent": "antigravity", "expected_revision": 1,
        }))
        self.assertEqual(stale_claim["status"], "conflict")

        # 3. Checkpoint
        checkpointed = self.call("mem_task_checkpoint", {
            "task_id": "task-life-1", "agent": "codex", "expected_revision": 2,
            "label": "core_planner",
            "state": {"progress": "implemented 3-stage planner", "tests": 338},
            "artifact_refs": ["tools/context_retrieval_planner.py", "eval/cli.py"],
            "claim_refs": [101],
            "episode_refs": ["2026-10-05.md"],
        })
        self.assertEqual(checkpointed["task"]["revision"], 3)

        # 4. Handoff
        handed_off = self.call("mem_handoff_create", {
            "task_id": "task-life-1",
            "source_agent": "codex",
            "target_agent": "antigravity",
            "expected_revision": 3,
            "objective": "Verify and close Pass 10",
            "completed_work": "Core retrieval and reporting hardened.",
            "next_action": "Run full regression verification checklist.",
            "blockers": "Launchd Dream Cycle telemetry must remain clean.",
            "acceptance_criteria": "338 pytest tests pass; resumption eval 9/9 evaluable.",
            "context": {"branch": "master", "hash": "abc1234"},
            "artifact_refs": ["docs/GMS_PASS_10_LIVE_CONTEXT_INTEGRITY_SPEC.md"],
        })
        self.assertEqual(handed_off["task"]["status"], "handed_off")
        self.assertEqual(handed_off["task"]["revision"], 4)

        # Readiness check while handed off
        readiness_handed_off = task_readiness.check_task_readiness(self.root, project="global-memory")
        self.assertTrue(readiness_handed_off["ready"])
        self.assertTrue(readiness_handed_off["quality_gate_eligible"])
        self.assertEqual(readiness_handed_off["active_task"]["task_id"], "task-life-1")

        # 5. Targeted Claim by handoff target agent
        claimed_target = self.call("mem_task_claim", {
            "task_id": "task-life-1", "agent": "antigravity", "expected_revision": 4,
        })
        self.assertEqual(claimed_target["task"]["revision"], 5)
        self.assertEqual(claimed_target["task"]["owner_agent"], "antigravity")

        # 6. Resume
        resumed = self.call("mem_task_resume", {"task_id": "task-life-1"})
        # Verify artifact refs, explicit blockers, acceptance criteria, and next action survived
        self.assertEqual(resumed["checkpoint"]["artifact_refs"], ["tools/context_retrieval_planner.py", "eval/cli.py"])
        self.assertEqual(resumed["handoff"]["artifact_refs"], ["docs/GMS_PASS_10_LIVE_CONTEXT_INTEGRITY_SPEC.md"])
        self.assertEqual(resumed["handoff"]["blockers"], "Launchd Dream Cycle telemetry must remain clean.")
        self.assertEqual(resumed["handoff"]["acceptance_criteria"], "338 pytest tests pass; resumption eval 9/9 evaluable.")
        self.assertEqual(resumed["handoff"]["next_action"], "Run full regression verification checklist.")

        # 7. Complete
        completed = self.call("mem_task_complete", {
            "task_id": "task-life-1", "agent": "antigravity", "expected_revision": 5,
        })
        self.assertEqual(completed["task"]["status"], "completed")
        self.assertEqual(completed["task"]["revision"], 6)

        # Readiness check after completion: completed task means no active task
        readiness_completed = task_readiness.check_task_readiness(self.root, project="global-memory")
        self.assertFalse(readiness_completed["ready"])
        self.assertFalse(readiness_completed["quality_gate_eligible"])

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
