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

        # General namespace should match general_note
        res_gen = self.api.get_memories(namespace="general")
        self.assertGreaterEqual(res_gen["total"], 1)
        self.assertTrue(any(m["key"] == "general_note" for m in res_gen["memories"]))

        # Check timestamps and agent fields are present
        for m in res_all["memories"]:
            self.assertIn("created_at", m)
            self.assertIn("updated_at", m)
            self.assertIn("activity_at", m)
            self.assertIn("agent", m)

        # Filter by query
        res_q = self.api.get_memories(query="node1")
        self.assertEqual(res_q["total"], 1)

        # Test alphabetical sorting
        res_alpha = self.api.get_memories(sort="alpha")
        alpha_keys = [m["key"].lower() for m in res_alpha["memories"]]
        self.assertEqual(alpha_keys, sorted(alpha_keys))

        # Test time-based sorting contracts
        res_recent = self.api.get_memories(sort="recent")
        recent_times = [m["activity_at"] for m in res_recent["memories"]]
        self.assertEqual(recent_times, sorted(recent_times, reverse=True))

        res_newest = self.api.get_memories(sort="newest")
        created_times = [m["created_at"] for m in res_newest["memories"]]
        self.assertEqual(created_times, sorted(created_times, reverse=True))

        res_oldest = self.api.get_memories(sort="oldest")
        oldest_times = [m["created_at"] for m in res_oldest["memories"]]
        self.assertEqual(oldest_times, sorted(oldest_times))

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

        # Consolidate the note into memory
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

        extraction = self.api.extract_from_text("Server Alpha uses StoragePool")
        self.assertIn("entity_candidates", extraction)
        existing = [item for item in extraction["entity_candidates"] if item["status"] == "existing"]
        self.assertGreaterEqual(len(existing), 1)
        self.assertTrue(extraction["review_required"])

    def test_apple_reminders_structure(self):
        # Test structure returns graceful dictionary regardless of platform
        res = self.api.get_reminders()
        self.assertIn("supported", res)
        self.assertIn("reminders", res)
        self.assertIsInstance(res["reminders"], list)

    def test_quarantine_items_with_diff_and_conflict_detection(self):
        # Insert a quarantined fact that conflicts with existing infra.node1
        proposed_val = {"host": "node1", "ip": "10.99.99.99", "port": 2222, "status": "maintenance"}
        memory_mcp_server.quarantine_fact("infra.node1", json.dumps(proposed_val), "rogue_agent", "feature-branch")

        items = self.api.get_quarantine_items()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["fact_key"], "infra.node1")
        self.assertEqual(item["agent_id"], "rogue_agent")
        self.assertEqual(item["conflict_type"], "overwrite_conflict")
        self.assertIn("Overwrites active memory", item["conflict_reason"])
        self.assertIsNotNone(item["current_value"])
        self.assertEqual(item["current_value"]["ip"], "192.168.1.10")
        self.assertEqual(item["value"]["ip"], "10.99.99.99")
        self.assertIn("agent_stats", item)

    def test_resolve_quarantine_promote_and_discard(self):
        # Quarantine an item
        prop_val = {"host": "node2", "ip": "192.168.1.20", "port": 22, "status": "online"}
        memory_mcp_server.quarantine_fact("infra.node2", json.dumps(prop_val), "worker_alpha", "main")

        # Promote it
        res_accept = self.api.resolve_quarantine("infra.node2", "worker_alpha", "accept", reviewer="human-ui")
        self.assertEqual(res_accept["status"], "success")

        # Verify it is active in memory
        memories = self.api.get_memories(namespace="infra.")
        keys = [m["key"] for m in memories["memories"]]
        self.assertIn("infra.node2", keys)

        # Quarantine another item and discard it
        prop_discard = {"host": "bad_node", "ip": "0.0.0.0", "port": 0, "status": "offline"}
        memory_mcp_server.quarantine_fact("infra.bad", json.dumps(prop_discard), "bad_agent", "main")
        res_reject = self.api.resolve_quarantine("infra.bad", "bad_agent", "reject", reviewer="human-ui")
        self.assertEqual(res_reject["status"], "success")

        # Verify quarantine is clean
        items_after = self.api.get_quarantine_items()
        self.assertEqual(len(items_after), 0)

    def test_resolve_quarantine_with_edited_value(self):
        # Quarantine a trading signal with invalid action
        invalid_val = {"ticker": "AAPL", "action": "yolo", "price": 200.0}
        memory_mcp_server.quarantine_fact("trading.aapl", json.dumps(invalid_val), "novice_agent", "main")

        # Attempt to accept with invalid edited value -> fails schema check
        res_fail = self.api.resolve_quarantine(
            "trading.aapl", "novice_agent", "accept",
            edited_value={"ticker": "AAPL", "action": "still_wrong", "price": 200.0}
        )
        self.assertEqual(res_fail["status"], "error")
        self.assertIn("Schema validation failed", res_fail["message"])

        # Accept with valid edited value
        valid_val = {
            "ticker": "AAPL",
            "action": "buy",
            "price": 200.0,
            "stop_loss": 190.0,
            "target_price": 230.0,
            "timeframe": "swing",
            "thesis": "Earnings breakout",
            "status": "open"
        }
        res_ok = self.api.resolve_quarantine("trading.aapl", "novice_agent", "accept", edited_value=valid_val)
        self.assertEqual(res_ok["status"], "success")

        # Verify trading.aapl is in memory with the edited value
        memories = self.api.get_memories(namespace="trading.")
        matching = [m for m in memories["memories"] if m["key"] == "trading.aapl"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["value"]["action"], "buy")

    def test_triage_history(self):
        history = self.api.get_triage_history(10)
        self.assertIsInstance(history, list)

    def test_search_hybrid(self):
        # Insert test entity and relationship
        conn = sqlite3.connect(str(self.api.db_path))
        c = conn.cursor()
        c.execute("INSERT INTO gms_entities (name, entity_type, summary) VALUES (?, ?, ?)", ("AlphaOS Core", "INFRA", "Trading engine"))
        eid = c.lastrowid
        conn.commit()
        conn.close()

        res = self.api.search_hybrid("AlphaOS")
        self.assertIn("query", res)
        self.assertEqual(res["query"], "AlphaOS")
        self.assertIn("memories", res)
        self.assertIn("entities", res)
        self.assertIn("triples", res)
        self.assertTrue(any(e["name"] == "AlphaOS Core" for e in res["entities"]))

    def test_merge_entities(self):
        conn = sqlite3.connect(str(self.api.db_path))
        c = conn.cursor()
        c.execute("INSERT INTO gms_entities (name, entity_type, summary) VALUES (?, ?, ?)", ("Ent A", "CONCEPT", "Entity A"))
        id_a = c.lastrowid
        c.execute("INSERT INTO gms_entities (name, entity_type, summary) VALUES (?, ?, ?)", ("Ent B", "CONCEPT", "Entity B"))
        id_b = c.lastrowid
        c.execute("INSERT INTO gms_relationships (subject_entity_id, predicate, object_literal) VALUES (?, ?, ?)", (id_a, "depends_on", "Postgres"))
        conn.commit()
        conn.close()

        res = self.api.merge_entities(id_a, id_b)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["source_id"], id_a)
        self.assertEqual(res["target_id"], id_b)

        # Check DB: id_a deleted, relationship points to id_b
        conn = sqlite3.connect(str(self.api.db_path))
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM gms_entities WHERE entity_id = ?", (id_a,))
        self.assertEqual(c.fetchone()[0], 0)
        c.execute("SELECT subject_entity_id FROM gms_relationships WHERE subject_entity_id = ?", (id_b,))
        self.assertEqual(c.fetchone()[0], id_b)
        conn.close()

    def test_dream_cycle_status(self):
        status = self.api.get_dream_cycle_status()
        self.assertIn("status", status)

    def test_broadened_secret_redaction(self):
        text = "My sk-123456789012345678901234 key and AKIA1234567890123456 and gho_12345678901234567890 token"
        redacted = self.api._redact_secrets(text)
        self.assertNotIn("sk-123456789012345678901234", redacted)
        self.assertNotIn("AKIA1234567890123456", redacted)
        self.assertNotIn("gho_12345678901234567890", redacted)
        self.assertIn("[REDACTED_API_KEY]", redacted)
        self.assertIn("[REDACTED_AWS_KEY]", redacted)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", redacted)

    def test_task_lifecycle_api(self):
        # 1. Create task
        res_create = self.api.create_task({
            "task_id": "test_desk_task_1",
            "project": "global-memory",
            "title": "API Parity Task",
            "objective": "Verify desktop API task lifecycle",
            "agent": "agent_alpha",
        })
        self.assertEqual(res_create.get("status"), "created")
        self.assertEqual(res_create["task"]["task_id"], "test_desk_task_1")

        # 2. Claim task
        res_claim = self.api.claim_task({
            "task_id": "test_desk_task_1",
            "agent": "agent_alpha",
            "expected_revision": 1,
            "lease_seconds": 600,
        })
        self.assertEqual(res_claim.get("status"), "claimed")
        self.assertEqual(res_claim["task"]["owner_agent"], "agent_alpha")

        # 3. Checkpoint task
        res_cp = self.api.checkpoint_task({
            "task_id": "test_desk_task_1",
            "agent": "agent_alpha",
            "expected_revision": 2,
            "label": "Milestone 1",
            "state": {"progress": 50},
        })
        self.assertEqual(res_cp.get("status"), "checkpointed")

        # 4. Handoff task
        res_ho = self.api.handoff_task({
            "task_id": "test_desk_task_1",
            "source_agent": "agent_alpha",
            "target_agent": "agent_beta",
            "expected_revision": 3,
            "objective": "Complete milestone 2",
            "next_action": "Run validation tests",
        })
        self.assertEqual(res_ho.get("status"), "handed_off")

        # 5. Resume bundle
        resume = self.api.get_task_resume("test_desk_task_1")
        self.assertEqual(resume["task"]["status"], "handed_off")
        self.assertEqual(resume["checkpoint"]["label"], "Milestone 1")
        self.assertEqual(resume["handoff"]["target_agent"], "agent_beta")

        # 6. Claim by agent_beta and complete
        res_claim2 = self.api.claim_task({
            "task_id": "test_desk_task_1",
            "agent": "agent_beta",
            "expected_revision": 4,
        })
        self.assertEqual(res_claim2.get("status"), "claimed")

        res_complete = self.api.complete_task({
            "task_id": "test_desk_task_1",
            "agent": "agent_beta",
            "expected_revision": 5,
        })
        self.assertIn("completed", str(res_complete).lower())

    def test_record_quarantine_review_api(self):
        # 1. First seed a quarantined fact
        memory_mcp_server.quarantine_fact("test_fact", "val", "agent_candidate", "main")

        # 2. Record review
        res = self.api.record_quarantine_review({
            "key": "test_fact",
            "agent_id": "agent_candidate",
            "reviewer_id": "reviewer_desk",
            "rating": "endorse",
            "rationale": "Corroborated via desktop API",
        })
        self.assertEqual(res["status"], "success")

    def test_get_retrieval_benchmarks_api(self):
        report = self.api.get_retrieval_benchmarks(mode="synthetic")
        self.assertIn("methods", report)
        self.assertIn("corpus_size", report)
        self.assertIn("Hybrid RRF", report["methods"])


if __name__ == "__main__":
    unittest.main()
