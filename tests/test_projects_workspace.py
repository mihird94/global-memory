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


class TestProjectsWorkspace(unittest.TestCase):
    def setUp(self):
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_mcp_db = memory_mcp_server.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.projects_dir = self.mem_root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        (self.mem_root / "semantic").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "operational").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "procedural").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "episodic" / "history").mkdir(parents=True, exist_ok=True)

        # 1. Complete project bank (alpha-core)
        p_complete = self.projects_dir / "alpha-core"
        p_complete.mkdir(parents=True, exist_ok=True)
        (p_complete / "projectBrief.md").write_text(
            "# Project Brief: Alpha Core\n\n## Overview\nAlpha Core is a high-throughput algorithmic engine.\n\n## Requirements\n- Latency < 5ms\n- 99.99% uptime\n"
        )
        (p_complete / "activeContext.md").write_text(
            "# Active Context\n\n## Current Focus\nOptimizing memory ordering in Rust engine.\n\n## Constraints\nDo not touch legacy C++ bindings.\n\n## Known Gaps\nNeeds load testing.\n\n## Verification\nAll 42 unit tests passing.\n\n### Update (2026-09-08 08:00)\nCodex completed memory fence audit.\n"
        )
        (p_complete / "systemPatterns.md").write_text(
            "# System Patterns\n\n## Architecture\nEvent-driven actor system.\n\n## Key Decisions\nUse lock-free ring buffers.\n"
        )
        (p_complete / "techContext.md").write_text(
            "# Tech Context\n\n## Technology Stack\nRust, Tokio, SQLite.\n"
        )
        (p_complete / "progress.md").write_text(
            "# Progress\n\n## Working Features\n- Ring buffer\n\n## Open Items\n- Benchmarking\n"
        )

        # 2. Placeholder project bank (beta-scaffold)
        p_placeholder = self.projects_dir / "beta-scaffold"
        p_placeholder.mkdir(parents=True, exist_ok=True)
        (p_placeholder / "projectBrief.md").write_text(
            "# Project Brief\n\n## Overview\n[Core goals and project scope]\n\n## Requirements\n- [Key requirement 1]\n"
        )
        (p_placeholder / "activeContext.md").write_text(
            "# Active Context\n\n## Current Focus\n[Active task or current milestone]\n\n## Recent Changes\n- [Recent update]\n"
        )

        # 3. Seed semantic facts with structured decisions
        (self.mem_root / "semantic" / "facts.json").write_text(json.dumps({
            "alpha-core.decision.engine": {
                "decision": "Use lock-free queues for market data feed",
                "status": "accepted",
                "rationale": "Lock contention on mutexes caused 14ms latency spikes at 50k msgs/sec.",
                "implications": ["Requires crossbeam channels", "Single producer, multi-consumer"],
                "scope": "alpha-core ingestion pipeline",
                "provenance": {"agent": "Antigravity", "date": "2026-09-08"}
            },
            "mbrain.agent_trust_ui": {
                "decision": "Do not use a global agent trust or reliability score in Mbrain",
                "status": "retired",
                "rationale": "A single score collapses task domain, evidence quality, and recency.",
                "implications": ["Show provenance, recency, contribution counts separate"],
                "scope": "Mbrain UI",
                "provenance": {"agent": "Codex", "date": "2026-09-08"}
            },
            "infra.secret_key": "Bearer sensitive_secret_token_12345678901234567890",
            "unstructured_note": "A general plain text memory fact"
        }))

        # 4. Initialize SQLite DB with tasks & handoffs
        memory_mcp_server.MEM_ROOT = self.mem_root
        memory_mcp_server.DB_PATH = self.mem_root / "gms_trust.sqlite"
        memory_mcp_server.init_db()

        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        cursor = conn.cursor()

        # Seed task for alpha-core
        cursor.execute("""
            INSERT INTO gms_tasks (task_id, project, title, objective, status, owner_agent, revision, created_by)
            VALUES ('task-101', 'alpha-core', 'Implement lock-free queue', 'Reduce latency to under 5ms', 'in_progress', 'agent_rust', 2, 'Codex')
        """)
        cursor.execute("""
            INSERT INTO gms_task_checkpoints (task_id, revision, agent_id, label, state_json, artifact_refs_json, claim_refs_json, episode_refs_json)
            VALUES ('task-101', 2, 'agent_rust', 'Benchmark checkpoint', '{\"throughput\": \"95k/s\"}', '[\"/src/queue.rs\"]', '[]', '[]')
        """)
        cursor.execute("""
            INSERT INTO gms_handoffs (task_id, revision, source_agent, target_agent, objective, completed_work, next_action, acknowledged_at)
            VALUES ('task-101', 2, 'Codex', 'agent_rust', 'Reduce latency', 'Drafted ring buffer', 'Run bench suite', '2026-09-08 07:30:00')
        """)

        # Seed task for a task-only project (gamma-tasks) with no directory bank
        cursor.execute("""
            INSERT INTO gms_tasks (task_id, project, title, objective, status, owner_agent, revision, created_by)
            VALUES ('task-201', 'gamma-tasks', 'Task-only project item', 'Validate task discovery', 'open', NULL, 1, 'Antigravity')
        """)

        conn.commit()
        conn.close()

        self.api = gms_desktop_api.GMSDesktopAPI(mem_root=self.mem_root)

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_mcp_db
        self.temp_dir.cleanup()

    def test_project_id_sanitization(self):
        # Valid IDs
        self.assertEqual(self.api._sanitize_project_id("alpha-core"), "alpha-core")
        self.assertEqual(self.api._sanitize_project_id("global_memory-2.0"), "global_memory-2.0")

        # Traversal and invalid characters
        with self.assertRaises(ValueError):
            self.api._sanitize_project_id("../etc/passwd")
        with self.assertRaises(ValueError):
            self.api._sanitize_project_id("foo/bar")
        with self.assertRaises(ValueError):
            self.api._sanitize_project_id("foo\\bar")
        with self.assertRaises(ValueError):
            self.api._sanitize_project_id("")
        with self.assertRaises(ValueError):
            self.api._sanitize_project_id("foo\0bar")

    def test_project_discovery_merges_banks_and_tasks(self):
        projects = self.api._discover_projects()
        # Should discover alpha-core (bank + task), beta-scaffold (bank only), and gamma-tasks (task only)
        self.assertIn("alpha-core", projects)
        self.assertIn("beta-scaffold", projects)
        self.assertIn("gamma-tasks", projects)
        self.assertEqual(len(projects), 3)

    def test_get_projects_summaries_and_attention(self):
        res = self.api.get_projects()
        self.assertEqual(res["total"], 3)
        proj_map = {p["project_id"]: p for p in res["projects"]}

        # alpha-core
        alpha = proj_map["alpha-core"]
        self.assertEqual(alpha["purpose_status"], "present")
        self.assertIn("high-throughput algorithmic engine", alpha["purpose"])
        self.assertEqual(alpha["counts"]["open_tasks"], 1)
        self.assertEqual(alpha["bank_completeness"]["completion_ratio"], 1.0)
        self.assertEqual(alpha["attention_count"], len(alpha["attention"]))
        self.assertEqual(alpha["last_activity"], alpha["last_activity_at"])

        # beta-scaffold
        beta = proj_map["beta-scaffold"]
        self.assertEqual(beta["purpose_status"], "placeholder")
        self.assertTrue(any("brief" in a.lower() for a in beta["attention"]))
        self.assertEqual(beta["bank_completeness"]["completion_ratio"], 0.4)
        self.assertIn("systemPatterns.md", beta["bank_completeness"]["missing_files"])

        # gamma-tasks (task-only project)
        gamma = proj_map["gamma-tasks"]
        self.assertEqual(gamma["purpose_status"], "missing")
        self.assertEqual(gamma["counts"]["open_tasks"], 1)

    def test_get_project_detail_and_empty_tasks(self):
        # 1. Project with tasks & full bank (alpha-core)
        detail = self.api.get_project_detail("alpha-core")
        self.assertEqual(detail["project_id"], "alpha-core")
        self.assertEqual(detail["bank_completeness"]["completion_ratio"], 1.0)
        self.assertIsNotNone(detail["last_activity"])
        self.assertEqual(detail["brief"]["purpose_status"], "present")
        self.assertEqual(detail["active_context"]["current_focus"], "Optimizing memory ordering in Rust engine.")
        self.assertTrue(any("legacy C++" in c for c in detail["active_context"]["constraints"]))
        self.assertEqual(len(detail["tasks"]["in_progress"]), 1)
        self.assertEqual(detail["tasks"]["in_progress"][0]["task_id"], "task-101")
        self.assertIsNotNone(detail["tasks"]["in_progress"][0]["latest_checkpoint"])
        self.assertIsNotNone(detail["tasks"]["in_progress"][0]["latest_handoff"])

        # Structured decisions
        self.assertTrue(any(d["decision"] == "Use lock-free queues for market data feed" for d in detail["decisions"]))
        decision = next(d for d in detail["decisions"] if d["decision"] == "Use lock-free queues for market data feed")
        self.assertIn("Lock contention", decision["rationale"])
        self.assertEqual(decision["provenance_tag"], "explicit")

        # 2. Project with 0 tasks (beta-scaffold)
        beta_detail = self.api.get_project_detail("beta-scaffold")
        self.assertEqual(beta_detail["project_id"], "beta-scaffold")
        self.assertEqual(len(beta_detail["tasks"]["in_progress"]), 0)
        self.assertEqual(len(beta_detail["tasks"]["open"]), 0)
        self.assertEqual(beta_detail["total_tasks"], 0)

    def test_project_activity_timeline(self):
        activity = self.api.get_project_activity("alpha-core")
        self.assertGreaterEqual(len(activity), 1)
        # Check that events have timestamp and source_type
        for item in activity:
            self.assertIn("timestamp", item)
            self.assertIn("summary", item)
            self.assertIn("source_type", item)

    def test_task_resume_endpoint(self):
        resume = self.api.get_task_resume("task-101")
        self.assertEqual(resume["task"]["task_id"], "task-101")
        self.assertEqual(resume["checkpoint"]["state"]["throughput"], "95k/s")
        self.assertEqual(resume["handoff"]["next_action"], "Run bench suite")

    def test_deterministic_context_packet_assembly(self):
        # 1. Preview Standard profile
        payload = {
            "project_id": "alpha-core",
            "profile": "standard",
            "target": {"agent": "Antigravity", "harness": "Antigravity IDE", "host": "local"}
        }
        res1 = self.api.preview_context_packet(payload)
        res2 = self.api.preview_context_packet(payload)

        # Verify deterministic hash
        self.assertEqual(res1["content_hash"], res2["content_hash"])
        self.assertTrue(res1["content_hash"].startswith("sha256:"))

        # Check packet fields
        packet = res1["packet"]
        self.assertEqual(packet["packet_version"], "gms-context-v1")
        self.assertEqual(packet["project"], "alpha-core")
        self.assertIn("Optimizing memory ordering", packet["current_state"])
        self.assertTrue(any("lock-free queues" in d["decision"] for d in packet["decisions"]))
        self.assertIn("Do not touch legacy C++ bindings.", packet["constraints"])

        # Check Markdown format
        md = res1["markdown"]
        self.assertIn("# Context Packet: alpha-core", md)
        self.assertIn("## 1. Objective", md)
        self.assertIn("## 3. Active Decisions & Rationale", md)

        # 2. Profile differences: Small vs Deep
        small_res = self.api.preview_context_packet({**payload, "profile": "small"})
        deep_res = self.api.preview_context_packet({**payload, "profile": "deep"})
        self.assertLess(small_res["packet"]["budget"]["char_count"], deep_res["packet"]["budget"]["char_count"])

        # 3. Secret redaction in context packet
        (self.mem_root / "projects" / "alpha-core" / "activeContext.md").write_text(
            "# Active Context\nUsing key Bearer secret_live_token_99999888887777766666 for trading API.\n"
        )
        redacted_res = self.api.preview_context_packet(payload)
        self.assertNotIn("secret_live_token", redacted_res["markdown"])
        self.assertIn("[REDACTED_TOKEN]", redacted_res["markdown"])

        # 4. Export packet to file
        export_res = self.api.export_context_packet(payload)
        self.assertEqual(export_res["status"], "success")
        self.assertTrue(Path(export_res["json_path"]).exists())
        self.assertTrue(Path(export_res["md_path"]).exists())


if __name__ == "__main__":
    unittest.main()
