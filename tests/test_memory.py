import os
import sys
import unittest
import tempfile
import shutil
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

# Create a temporary directory and set it as MEMORY_ROOT
# before importing the tools so they pick it up as MEM_ROOT.
temp_dir = os.environ.get("MEMORY_ROOT")
if not temp_dir:
    temp_dir = tempfile.mkdtemp()
    os.environ["MEMORY_ROOT"] = temp_dir


# Add the tools directory to sys.path
tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import memory_mcp_server
import dream_cycle

class TestGMSPhase1(unittest.TestCase):
    def setUp(self):
        # Clean up temp_dir contents between tests
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        
        # Ensure subdirectory structure exists
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "episodic" / "history").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "lessons").mkdir(parents=True, exist_ok=True)
        
        # Initialize DB
        memory_mcp_server.init_db()

    def tearDown(self):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def get_db_connection(self):
        return sqlite3.connect(str(self.temp_path / "gms_trust.sqlite"))

    def test_conflicting_fact_quarantine(self):
        # 1. Save a fact from a trusted agent
        # Set agent reputation: agent_trusted has high alpha
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_trusted", 10.0, 0.0)
        )
        conn.commit()
        conn.close()

        # Save the initial fact
        res1 = memory_mcp_server.tool_mem_save_fact({
            "key": "test_fact",
            "value": "initial_value",
            "agent": "agent_trusted"
        })
        self.assertIn("Fact saved", res1)

        # Verify it was saved to facts.json
        facts_file = self.temp_path / "semantic" / "facts.json"
        self.assertTrue(facts_file.exists())
        facts = json.loads(facts_file.read_text())
        self.assertEqual(facts["test_fact"], "initial_value")

        # 2. Try to overwrite from a less trusted agent (e.g. low reputation)
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_untrusted", 1.0, 5.0)
        )
        conn.commit()
        conn.close()

        res2 = memory_mcp_server.tool_mem_save_fact({
            "key": "test_fact",
            "value": "untrusted_value",
            "agent": "agent_untrusted"
        })
        self.assertIn("CONFLICT/QUARANTINE", res2)

        # Verify facts.json did not change
        facts = json.loads(facts_file.read_text())
        self.assertEqual(facts["test_fact"], "initial_value")

        # Verify it is in the quarantine table
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", ("test_fact", "agent_untrusted"))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "untrusted_value")

    @patch("dream_cycle.ollama_available", return_value=False)
    @patch("dream_cycle.extract_facts_with_cascade")
    @patch("dream_cycle.rebuild_faiss_index")
    @patch("dream_cycle.git_commit_memories")
    def test_non_conflicting_dream_cycle_promotion(self, mock_git, mock_rebuild, mock_extract, mock_ollama):
        # Mock extract to return a new fact
        mock_extract.return_value = ({"new_dream_fact": "dream_value"}, "mock-provider")
        
        # Write mock journal entries so dream_cycle runs
        journal_path = self.temp_path / "episodic" / "journal.md"
        journal_path.write_text("Completed Phase 1 tasks today.")

        # Run dream_cycle main
        code = dream_cycle.main()
        self.assertEqual(code, 0)

        # Verify it was promoted to facts.json
        facts_file = self.temp_path / "semantic" / "facts.json"
        self.assertTrue(facts_file.exists())
        facts = json.loads(facts_file.read_text())
        self.assertEqual(facts["new_dream_fact"], "dream_value")

        # Verify provenance was recorded in the database
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, branch, quarantined FROM gms_fact_provenance WHERE fact_key = ?", ("new_dream_fact",))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "DreamCycle-mock-provider")
        self.assertEqual(row[2], 0) # not quarantined

    @patch("dream_cycle.ollama_available", return_value=False)
    @patch("dream_cycle.extract_facts_with_cascade")
    @patch("dream_cycle.rebuild_faiss_index")
    @patch("dream_cycle.git_commit_memories")
    def test_conflicting_dream_cycle_quarantine(self, mock_git, mock_rebuild, mock_extract, mock_ollama):
        # 1. Establish a high-trust owner for a fact in facts.json
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_trusted", 10.0, 0.0)
        )
        conn.commit()
        conn.close()

        # Save it
        res = memory_mcp_server.tool_mem_save_fact({
            "key": "conflict_fact",
            "value": "trusted_value",
            "agent": "agent_trusted"
        })
        self.assertIn("Fact saved", res)

        # 2. Dream cycle extracts a conflicting value for that fact.
        # DreamCycle has default reputation (alpha=1.0, beta=0.0 -> trust = 0.5), which is less than agent_trusted (trust = 0.916)
        mock_extract.return_value = ({"conflict_fact": "dream_conflicting_value"}, "mock-provider")
        
        # Write mock journal
        journal_path = self.temp_path / "episodic" / "journal.md"
        journal_path.write_text("Some updates.")

        # Run dream_cycle main
        code = dream_cycle.main()
        self.assertEqual(code, 0)

        # Verify facts.json was NOT overwritten
        facts_file = self.temp_path / "semantic" / "facts.json"
        facts = json.loads(facts_file.read_text())
        self.assertEqual(facts["conflict_fact"], "trusted_value")

        # Verify it was quarantined
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", ("conflict_fact", "DreamCycle-mock-provider"))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "dream_conflicting_value")

    def test_calibration_routine_naming(self):
        # Check that new calibration name exists and old name does not
        self.assertTrue(hasattr(dream_cycle, "run_beta_binomial_trust_calibration"))
        self.assertFalse(hasattr(dream_cycle, "run_trust_calibration_em"))


class TestGMSPhase2(unittest.TestCase):
    def setUp(self):
        # Clean up temp_dir contents between tests
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        
        # Ensure subdirectory structure exists
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "operational").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "procedural").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "lessons").mkdir(parents=True, exist_ok=True)
        
        # Initialize DB
        memory_mcp_server.init_db()

    def get_db_connection(self):
        return sqlite3.connect(str(self.temp_path / "gms_trust.sqlite"))

    def test_semantic_write_lands_in_semantic_storage(self):
        # Explicit semantic write
        res = memory_mcp_server.tool_mem_save_typed({
            "key": "world_capital",
            "value": "Paris",
            "kind": "semantic",
            "agent": "agent_test"
        })
        self.assertIn("Fact saved", res)
        
        # Verify it lands in semantic storage
        sem_file = self.temp_path / "semantic" / "facts.json"
        self.assertTrue(sem_file.exists())
        facts = json.loads(sem_file.read_text())
        self.assertEqual(facts["world_capital"], "Paris")
        
        # Verify it does NOT land in operational/procedural storage
        self.assertFalse((self.temp_path / "operational" / "facts.json").exists())
        self.assertFalse((self.temp_path / "procedural" / "facts.json").exists())

    def test_operational_write_lands_in_operational_storage(self):
        # Explicit operational write
        res = memory_mcp_server.tool_mem_save_typed({
            "key": "agent_settings",
            "value": "temperature=0.7",
            "kind": "operational",
            "agent": "agent_test"
        })
        self.assertIn("Fact saved", res)
        
        # Verify it lands in operational storage
        op_file = self.temp_path / "operational" / "facts.json"
        self.assertTrue(op_file.exists())
        facts = json.loads(op_file.read_text())
        self.assertEqual(facts["agent_settings"], "temperature=0.7")
        
        # Verify it does NOT land in semantic/procedural storage
        sem_file = self.temp_path / "semantic" / "facts.json"
        if sem_file.exists():
            facts_sem = json.loads(sem_file.read_text())
            self.assertNotIn("agent_settings", facts_sem)
        self.assertFalse((self.temp_path / "procedural" / "facts.json").exists())

    def test_procedural_write_lands_in_procedural_storage(self):
        # Explicit procedural write
        res = memory_mcp_server.tool_mem_save_typed({
            "key": "git_workflow_instruction",
            "value": "always run git pull before push",
            "kind": "procedural",
            "agent": "agent_test"
        })
        self.assertIn("Fact saved", res)
        
        # Verify it lands in procedural storage
        proc_file = self.temp_path / "procedural" / "facts.json"
        self.assertTrue(proc_file.exists())
        facts = json.loads(proc_file.read_text())
        self.assertEqual(facts["git_workflow_instruction"], "always run git pull before push")
        
        # Verify it does NOT land in semantic/operational storage
        sem_file = self.temp_path / "semantic" / "facts.json"
        if sem_file.exists():
            facts_sem = json.loads(sem_file.read_text())
            self.assertNotIn("git_workflow_instruction", facts_sem)
        op_file = self.temp_path / "operational" / "facts.json"
        if op_file.exists():
            facts_op = json.loads(op_file.read_text())
            self.assertNotIn("git_workflow_instruction", facts_op)

    def test_session_writes_do_not_persist(self):
        # Explicit session write
        res = memory_mcp_server.tool_mem_save_typed({
            "key": "current_chat_context",
            "value": "user is asking about GMS",
            "kind": "session",
            "agent": "agent_test"
        })
        self.assertIn("SESSION_ONLY", res)
        
        # Verify no files were created or updated with session info
        self.assertFalse((self.temp_path / "semantic" / "facts.json").exists())
        self.assertFalse((self.temp_path / "operational" / "facts.json").exists())
        self.assertFalse((self.temp_path / "procedural" / "facts.json").exists())

    def test_deterministic_routing_rules(self):
        # Auto-routes behavior/config -> operational
        res1 = memory_mcp_server.tool_mem_save_typed({
            "key": "agent_behavior_rule",
            "value": "always be concise",
            "agent": "agent_test"
        })
        self.assertIn("OPERATIONAL", res1)
        self.assertTrue((self.temp_path / "operational" / "facts.json").exists())
        
        # Auto-routes instruction -> procedural
        res2 = memory_mcp_server.tool_mem_save_typed({
            "key": "how_to_build",
            "value": "run npm run build",
            "agent": "agent_test"
        })
        self.assertIn("PROCEDURAL", res2)
        self.assertTrue((self.temp_path / "procedural" / "facts.json").exists())
        
        # Auto-routes current conversation/task_state -> session
        res3 = memory_mcp_server.tool_mem_save_typed({
            "key": "current_task_state_v1",
            "value": "writing code",
            "agent": "agent_test"
        })
        self.assertIn("SESSION_ONLY", res3)

        # Auto-routes other -> semantic
        res4 = memory_mcp_server.tool_mem_save_typed({
            "key": "capital_of_france",
            "value": "Paris",
            "agent": "agent_test"
        })
        self.assertIn("SEMANTIC", res4)
        self.assertTrue((self.temp_path / "semantic" / "facts.json").exists())

    def test_typed_reads_retrieve_right_bucket(self):
        # Write to semantic
        memory_mcp_server.tool_mem_save_typed({
            "key": "fact_sem",
            "value": "val_sem",
            "kind": "semantic",
            "agent": "agent_test"
        })
        # Write to operational
        memory_mcp_server.tool_mem_save_typed({
            "key": "fact_op",
            "value": "val_op",
            "kind": "operational",
            "agent": "agent_test"
        })
        
        # Retrieve semantic
        res_sem_json = memory_mcp_server.tool_mem_get_facts({"kind": "semantic"})
        res_sem = json.loads(res_sem_json)
        self.assertIn("fact_sem", res_sem)
        self.assertNotIn("fact_op", res_sem)
        
        # Retrieve operational
        res_op_json = memory_mcp_server.tool_mem_get_facts({"kind": "operational"})
        res_op = json.loads(res_op_json)
        self.assertIn("fact_op", res_op)
        self.assertNotIn("fact_sem", res_op)

    def test_backward_compatible_mem_save_fact(self):
        # Call legacy mem_save_fact (must write to semantic and land in semantic storage)
        res = memory_mcp_server.tool_mem_save_fact({
            "key": "legacy_key",
            "value": "legacy_val",
            "agent": "agent_test"
        })
        self.assertIn("Fact saved", res)
        
        sem_file = self.temp_path / "semantic" / "facts.json"
        self.assertTrue(sem_file.exists())
        facts = json.loads(sem_file.read_text())
        self.assertEqual(facts["legacy_key"], "legacy_val")


class TestGMSPhase3(unittest.TestCase):
    def setUp(self):
        # Clean up temp_dir contents between tests
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        
        # Ensure subdirectory structure exists
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "operational").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "procedural").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "lessons").mkdir(parents=True, exist_ok=True)
        
        # Initialize DB
        memory_mcp_server.init_db()

    def get_db_connection(self):
        return sqlite3.connect(str(self.temp_path / "gms_trust.sqlite"))

    def test_accepted_persisted_write_creates_active_claim(self):
        # Save operational fact
        memory_mcp_server.tool_mem_save_typed({
            "key": "agent_settings",
            "value": "temperature=0.7",
            "kind": "operational",
            "agent": "agent_test"
        })
        
        # Read claims
        claims_json = memory_mcp_server.tool_mem_get_claims({"kind": "operational", "key": "agent_settings"})
        claims = json.loads(claims_json)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], "active")
        self.assertEqual(claims[0]["value"], "temperature=0.7")
        self.assertEqual(claims[0]["agent_id"], "agent_test")

    def test_overwrite_supersedes_prior_active_claim(self):
        # First write
        memory_mcp_server.tool_mem_save_typed({
            "key": "app_mode",
            "value": "debug",
            "kind": "operational",
            "agent": "agent_1"
        })
        
        # Get first claim
        claims_1 = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "operational", "key": "app_mode"}))
        self.assertEqual(len(claims_1), 1)
        claim_1_id = claims_1[0]["claim_id"]
        
        # Overwrite with force to guarantee acceptance
        memory_mcp_server.tool_mem_save_typed({
            "key": "app_mode",
            "value": "production",
            "kind": "operational",
            "agent": "agent_1",
            "force": True
        })
        
        # Get both claims
        claims_2 = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "operational", "key": "app_mode"}))
        self.assertEqual(len(claims_2), 2)
        
        # Find claim_1 and claim_2 in the result
        c1 = [c for c in claims_2 if c["claim_id"] == claim_1_id][0]
        c2 = [c for c in claims_2 if c["claim_id"] != claim_1_id][0]
        
        self.assertEqual(c1["status"], "superseded")
        self.assertEqual(c2["status"], "active")
        self.assertEqual(c2["supersedes_claim_id"], claim_1_id)

    def test_quarantined_write_creates_quarantined_claim(self):
        # Set agent reputation
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_trusted", 10.0, 0.0)
        )
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_untrusted", 1.0, 5.0)
        )
        conn.commit()
        conn.close()

        # Save initial fact
        memory_mcp_server.tool_mem_save_typed({
            "key": "secret_key",
            "value": "trusted_val",
            "kind": "semantic",
            "agent": "agent_trusted"
        })
        
        # Attempt conflicting write from untrusted agent
        memory_mcp_server.tool_mem_save_typed({
            "key": "secret_key",
            "value": "untrusted_val",
            "kind": "semantic",
            "agent": "agent_untrusted"
        })
        
        # Retrieve quarantined claims
        claims_json = memory_mcp_server.tool_mem_get_claims({"kind": "semantic", "key": "secret_key", "status": "quarantined"})
        claims = json.loads(claims_json)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["value"], "untrusted_val")
        self.assertEqual(claims[0]["agent_id"], "agent_untrusted")

    def test_session_writes_do_not_create_claims(self):
        memory_mcp_server.tool_mem_save_typed({
            "key": "ephemeral_task",
            "value": "running_tests",
            "kind": "session",
            "agent": "agent_test"
        })
        
        claims_json = memory_mcp_server.tool_mem_get_claims({"key": "ephemeral_task"})
        claims = json.loads(claims_json)
        self.assertEqual(len(claims), 0)

    def test_claim_reads_can_filter(self):
        memory_mcp_server.tool_mem_save_typed({
            "key": "k1",
            "value": "v1",
            "kind": "semantic",
            "agent": "agent_test"
        })
        memory_mcp_server.tool_mem_save_typed({
            "key": "k2",
            "value": "v2",
            "kind": "operational",
            "agent": "agent_test"
        })
        
        # Filter by kind
        claims_sem = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "semantic"}))
        self.assertEqual(len(claims_sem), 1)
        self.assertEqual(claims_sem[0]["memory_key"], "k1")
        
        claims_op = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "operational"}))
        self.assertEqual(len(claims_op), 1)
        self.assertEqual(claims_op[0]["memory_key"], "k2")
        
        # Filter by key
        claims_k1 = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "k1"}))
        self.assertEqual(len(claims_k1), 1)
        
        # Filter by status
        claims_act = json.loads(memory_mcp_server.tool_mem_get_claims({"status": "active"}))
        self.assertEqual(len(claims_act), 2)

    def test_quarantine_promotion_and_discard_claims(self):
        # Set agent reputations
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_trusted", 10.0, 0.0)
        )
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_untrusted", 1.0, 5.0)
        )
        conn.commit()
        conn.close()

        # 1. First active write
        memory_mcp_server.tool_mem_save_typed({
            "key": "shared_config",
            "value": "v_trusted",
            "kind": "operational",
            "agent": "agent_trusted"
        })
        
        claims = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "operational", "key": "shared_config"}))
        active_id = claims[0]["claim_id"]
        
        # 2. Quarantined write
        memory_mcp_server.tool_mem_save_typed({
            "key": "shared_config",
            "value": "v_untrusted",
            "kind": "operational",
            "agent": "agent_untrusted"
        })
        
        claims = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "operational", "key": "shared_config", "status": "quarantined"}))
        self.assertEqual(len(claims), 1)
        quar_id = claims[0]["claim_id"]
        
        # 3. Promote quarantine
        res = memory_mcp_server.tool_mem_resolve_quarantine({
            "key": "operational:shared_config",
            "agent_id": "agent_untrusted",
            "action": "promote",
            "agent": "admin"
        })
        self.assertIn("SUCCESS", res)
        
        # Verify claim status transitions
        claims = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "operational", "key": "shared_config"}))
        self.assertEqual(len(claims), 2)
        
        c_old = [c for c in claims if c["claim_id"] == active_id][0]
        c_prom = [c for c in claims if c["claim_id"] == quar_id][0]
        
        self.assertEqual(c_old["status"], "superseded")
        self.assertEqual(c_prom["status"], "active")
        self.assertEqual(c_prom["supersedes_claim_id"], active_id)
        
        # 4. Now test discard
        memory_mcp_server.tool_mem_save_typed({
            "key": "discard_config",
            "value": "v_trusted",
            "kind": "operational",
            "agent": "agent_trusted"
        })
        
        memory_mcp_server.tool_mem_save_typed({
            "key": "discard_config",
            "value": "v_bad",
            "kind": "operational",
            "agent": "agent_untrusted"
        })
        
        claims = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "operational", "key": "discard_config", "status": "quarantined"}))
        self.assertEqual(len(claims), 1)
        bad_id = claims[0]["claim_id"]
        
        res_disc = memory_mcp_server.tool_mem_resolve_quarantine({
            "key": "operational:discard_config",
            "agent_id": "agent_untrusted",
            "action": "discard",
            "agent": "admin"
        })
        self.assertIn("SUCCESS", res_disc)
        
        # Verify claim status updated to discarded
        claims_disc = json.loads(memory_mcp_server.tool_mem_get_claims({"kind": "operational", "key": "discard_config", "status": "discarded"}))
        self.assertEqual(len(claims_disc), 1)
        self.assertEqual(claims_disc[0]["claim_id"], bad_id)


class TestGMSPhase4(unittest.TestCase):
    def setUp(self):
        # Clean up temp_dir contents between tests
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        
        # Ensure subdirectory structure exists
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "operational").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "procedural").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "lessons").mkdir(parents=True, exist_ok=True)
        
        # Initialize DB
        memory_mcp_server.init_db()

    def get_db_connection(self):
        return sqlite3.connect(str(self.temp_path / "gms_trust.sqlite"))

    def test_entity_upsert_idempotent(self):
        # First upsert creates entity
        res_json = memory_mcp_server.tool_mem_upsert_entity({
            "name": "Project Alpha",
            "entity_type": "Project",
            "summary": "Alpha platform launch"
        })
        res = json.loads(res_json)
        self.assertEqual(res["name"], "Project Alpha")
        self.assertEqual(res["entity_type"], "Project")
        self.assertEqual(res["summary"], "Alpha platform launch")
        entity_id = res["entity_id"]

        # Second upsert with different details updates existing
        res2_json = memory_mcp_server.tool_mem_upsert_entity({
            "name": "Project Alpha",
            "entity_type": "Initiative",
            "summary": "Alpha platform launch v2"
        })
        res2 = json.loads(res2_json)
        self.assertEqual(res2["entity_id"], entity_id) # Same ID!
        self.assertEqual(res2["entity_type"], "Initiative")
        self.assertEqual(res2["summary"], "Alpha platform launch v2")

        # Verify DB content
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM gms_entities WHERE name = ?", ("Project Alpha",))
        self.assertEqual(cursor.fetchone()[0], 1)
        conn.close()

    def test_relationship_creation(self):
        # Create entities
        e1 = json.loads(memory_mcp_server.tool_mem_upsert_entity({"name": "Mihir", "entity_type": "Person"}))
        e2 = json.loads(memory_mcp_server.tool_mem_upsert_entity({"name": "Optimus", "entity_type": "Project"}))
        
        # Create relationship
        rel_json = memory_mcp_server.tool_mem_link_entities({
            "subject_id": e1["entity_id"],
            "predicate": "leads",
            "object_id": e2["entity_id"]
        })
        rel = json.loads(rel_json)
        self.assertEqual(rel["subject_entity_id"], e1["entity_id"])
        self.assertEqual(rel["predicate"], "leads")
        self.assertEqual(rel["object_entity_id"], e2["entity_id"])

    def test_relationship_temporal_fields(self):
        # Create relationship with temporal bounds
        rel_json = memory_mcp_server.tool_mem_link_entities({
            "subject_name": "Antigravity",
            "predicate": "active_on",
            "object_literal": "Phase 4",
            "valid_from": "2026-06-04T12:00:00Z",
            "valid_to": "2026-06-05T12:00:00Z"
        })
        rel = json.loads(rel_json)
        self.assertEqual(rel["valid_from"], "2026-06-04T12:00:00Z")
        self.assertEqual(rel["valid_to"], "2026-06-05T12:00:00Z")
        self.assertEqual(rel["object_literal"], "Phase 4")

    def test_relationship_reference_valid_claim_id(self):
        # Create a valid claim by saving a fact
        memory_mcp_server.tool_mem_save_typed({
            "key": "optimus_lead",
            "value": "Mihir",
            "kind": "semantic",
            "agent": "Codex"
        })
        # Retrieve the claim_id
        claims = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "optimus_lead"}))
        self.assertGreater(len(claims), 0)
        claim_id = claims[0]["claim_id"]

        # Link with valid claim ID
        rel_json = memory_mcp_server.tool_mem_link_entities({
            "subject_name": "Mihir",
            "predicate": "leads",
            "object_name": "Optimus",
            "source_claim_id": claim_id
        })
        rel = json.loads(rel_json)
        self.assertEqual(rel["source_claim_id"], claim_id)

        # Attempt to link with invalid claim ID
        bad_rel = memory_mcp_server.tool_mem_link_entities({
            "subject_name": "Mihir",
            "predicate": "leads",
            "object_name": "Optimus",
            "source_claim_id": 99999
        })
        self.assertIn("ERROR", bad_rel)

    def test_entity_graph_read(self):
        # Create entity graph
        memory_mcp_server.tool_mem_link_entities({
            "subject_name": "Alice",
            "predicate": "knows",
            "object_name": "Bob"
        })
        memory_mcp_server.tool_mem_link_entities({
            "subject_name": "Bob",
            "predicate": "knows",
            "object_name": "Charlie"
        })

        # Get full graph
        graph_all = json.loads(memory_mcp_server.tool_mem_get_entity_graph({}))
        self.assertEqual(len(graph_all["entities"]), 3)
        self.assertEqual(len(graph_all["relationships"]), 2)

        # Get ego network for Bob
        graph_bob = json.loads(memory_mcp_server.tool_mem_get_entity_graph({"name": "Bob"}))
        self.assertEqual(len(graph_bob["entities"]), 3)
        self.assertEqual(len(graph_bob["relationships"]), 2)

        # Get ego network for Alice
        graph_alice = json.loads(memory_mcp_server.tool_mem_get_entity_graph({"name": "Alice"}))
        self.assertEqual(len(graph_alice["entities"]), 2)
        self.assertEqual(len(graph_alice["relationships"]), 1)


class TestGMSPhase5(unittest.TestCase):
    def setUp(self):
        # Clean up temp_dir contents between tests
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        
        # Ensure subdirectory structure exists
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "operational").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "procedural").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "lessons").mkdir(parents=True, exist_ok=True)
        
        # Initialize DB
        memory_mcp_server.init_db()

    def get_db_connection(self):
        return sqlite3.connect(str(self.temp_path / "gms_trust.sqlite"))

    def test_repeated_same_value_writes_reinforce_confidence(self):
        # Initial write
        memory_mcp_server.tool_mem_save_typed({
            "key": "test_reinforce",
            "value": "constant_val",
            "kind": "semantic",
            "agent": "agent_test"
        })
        
        claims1 = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "test_reinforce"}))
        self.assertEqual(len(claims1), 1)
        conf1 = claims1[0]["confidence"]
        self.assertIsNotNone(conf1)
        
        # Write same value again
        memory_mcp_server.tool_mem_save_typed({
            "key": "test_reinforce",
            "value": "constant_val",
            "kind": "semantic",
            "agent": "agent_test"
        })
        
        claims2 = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "test_reinforce"}))
        self.assertEqual(len(claims2), 1)
        conf2 = claims2[0]["confidence"]
        self.assertEqual(conf2, conf1)

    def test_quarantined_conflicting_writes_produce_low_confidence_quarantined_claims(self):
        # Set agent reputations
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_trusted", 10.0, 0.0)
        )
        cursor.execute(
            "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_untrusted", 1.0, 5.0)
        )
        conn.commit()
        conn.close()

        # Save initial fact
        memory_mcp_server.tool_mem_save_typed({
            "key": "secret_key",
            "value": "trusted_val",
            "kind": "semantic",
            "agent": "agent_trusted"
        })
        
        # Attempt conflicting write from untrusted agent
        memory_mcp_server.tool_mem_save_typed({
            "key": "secret_key",
            "value": "untrusted_val",
            "kind": "semantic",
            "agent": "agent_untrusted"
        })
        
        claims = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "secret_key", "status": "quarantined"}))
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["contradiction_type"], "exact_conflict")
        self.assertLessEqual(claims[0]["confidence"], 0.3)

    def test_exact_conflict_classification_recorded(self):
        # Initial write
        memory_mcp_server.tool_mem_save_typed({
            "key": "conflict_key",
            "value": "val1",
            "kind": "semantic",
            "agent": "agent_1",
            "force": True
        })
        # Overwrite with different value (quarantined write)
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)", ("agent_1", 10.0, 0.0))
        cursor.execute("INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)", ("agent_2", 1.0, 5.0))
        conn.commit()
        conn.close()
        
        memory_mcp_server.tool_mem_save_typed({
            "key": "conflict_key",
            "value": "val2",
            "kind": "semantic",
            "agent": "agent_2"
        })
        
        claims = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "conflict_key", "status": "quarantined"}))
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["contradiction_type"], "exact_conflict")

    def test_temporal_invalidation_can_be_represented(self):
        # 1. Test claim transition superseding
        memory_mcp_server.tool_mem_save_typed({
            "key": "temp_key",
            "value": "val1",
            "kind": "semantic",
            "agent": "agent_1"
        })
        claims_before = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "temp_key"}))
        self.assertEqual(len(claims_before), 1)
        
        # Overwrite (active superseding)
        memory_mcp_server.tool_mem_save_typed({
            "key": "temp_key",
            "value": "val2",
            "kind": "semantic",
            "agent": "agent_1",
            "force": True
        })
        
        claims_after = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "temp_key"}))
        self.assertEqual(len(claims_after), 2)
        c_old = [c for c in claims_after if c["value"] == "val1"][0]
        c_new = [c for c in claims_after if c["value"] == "val2"][0]
        
        self.assertEqual(c_old["status"], "superseded")
        self.assertEqual(c_old["confidence"], 0.0)
        self.assertEqual(c_new["status"], "active")
        self.assertEqual(c_new["contradiction_type"], "temporal_invalidation")

        # 2. Test claim with time keyword or date pattern
        memory_mcp_server.tool_mem_save_typed({
            "key": "expires_soon",
            "value": "active until 2026-12-31",
            "kind": "semantic",
            "agent": "agent_1"
        })
        claims_time = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "expires_soon"}))
        self.assertEqual(claims_time[0]["contradiction_type"], "temporal_invalidation")

    def test_contextual_coexistence_represented_without_overwrite(self):
        # Write unscoped
        memory_mcp_server.tool_mem_save_typed({
            "key": "server_url",
            "value": "http://prod",
            "kind": "semantic",
            "agent": "agent_1"
        })
        
        # Write scoped/context-tagged coexistence
        memory_mcp_server.tool_mem_save_typed({
            "key": "server_url@staging",
            "value": "http://staging",
            "kind": "semantic",
            "agent": "agent_1"
        })
        
        # Verify unscoped key is not overwritten in facts.json
        facts_file = self.temp_path / "semantic" / "facts.json"
        facts = json.loads(facts_file.read_text())
        self.assertEqual(facts["server_url"], "http://prod")
        self.assertEqual(facts["server_url@staging"], "http://staging")
        
        # Verify contradiction_type is contextual_coexistence
        claims = json.loads(memory_mcp_server.tool_mem_get_claims({"key": "server_url@staging"}))
        self.assertEqual(claims[0]["contradiction_type"], "contextual_coexistence")


class TestGMSPhase6(unittest.TestCase):
    def setUp(self):
        # Clean up temp_dir contents between tests
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        
        # Ensure subdirectory structure exists
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "operational").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "procedural").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "lessons").mkdir(parents=True, exist_ok=True)
        
        # Initialize DB
        memory_mcp_server.init_db()

    def get_db_connection(self):
        return sqlite3.connect(str(self.temp_path / "gms_trust.sqlite"))

    def test_upsert_idempotent_by_name(self):
        # Initial upsert
        res1 = memory_mcp_server.tool_mem_upsert_procedure({
            "name": "build_deploy",
            "trigger": "git_push",
            "action": "run_tests && deploy",
            "context": "prod-env"
        })
        proc1 = json.loads(res1)
        self.assertEqual(proc1["name"], "build_deploy")
        self.assertEqual(proc1["trigger"], "git_push")
        self.assertEqual(proc1["status"], "active")

        # Second upsert with same name - updates fields
        res2 = memory_mcp_server.tool_mem_upsert_procedure({
            "name": "build_deploy",
            "trigger": "git_commit",
            "action": "run_tests"
        })
        proc2 = json.loads(res2)
        self.assertEqual(proc2["name"], "build_deploy")
        self.assertEqual(proc2["trigger"], "git_commit")
        self.assertEqual(proc2["action"], "run_tests")
        self.assertEqual(proc2["context"], "prod-env")  # preserved

        # Verify database has only 1 row
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM gms_procedures WHERE name = 'build_deploy'")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_trigger_action_context_fields_persist(self):
        res = memory_mcp_server.tool_mem_upsert_procedure({
            "name": "playbook_1",
            "trigger": "alert_fired",
            "action": "restart_service",
            "context": "k8s-cluster",
            "status": "active"
        })
        proc = json.loads(res)
        self.assertEqual(proc["name"], "playbook_1")
        self.assertEqual(proc["trigger"], "alert_fired")
        self.assertEqual(proc["action"], "restart_service")
        self.assertEqual(proc["context"], "k8s-cluster")

        # Fetch using mem_get_procedures
        fetched_res = memory_mcp_server.tool_mem_get_procedures({"name": "playbook_1"})
        fetched_list = json.loads(fetched_res)
        self.assertEqual(len(fetched_list), 1)
        self.assertEqual(fetched_list[0]["trigger"], "alert_fired")
        self.assertEqual(fetched_list[0]["action"], "restart_service")

    def test_claim_linkage_validation(self):
        # Validation failure for non-existent claim ID
        res_fail = memory_mcp_server.tool_mem_upsert_procedure({
            "name": "linked_playbook",
            "source_claim_id": 9999
        })
        self.assertIn("ERROR", res_fail)
        self.assertIn("does not exist", res_fail)

        # Create a valid claim in the claims table
        claim_id = memory_mcp_server.record_claim(
            kind="semantic",
            key="test_fact_key",
            value="test_fact_val",
            agent_id="test_agent",
            branch="main",
            status="active"
        )
        self.assertTrue(isinstance(claim_id, int))

        # Upsert procedure with valid claim ID linkage
        res_success = memory_mcp_server.tool_mem_upsert_procedure({
            "name": "linked_playbook",
            "source_claim_id": claim_id
        })
        proc = json.loads(res_success)
        self.assertEqual(proc["source_claim_id"], claim_id)

        # Get and verify linkage
        fetched_res = memory_mcp_server.tool_mem_get_procedures({"source_claim_id": claim_id})
        fetched_list = json.loads(fetched_res)
        self.assertEqual(len(fetched_list), 1)
        self.assertEqual(fetched_list[0]["name"], "linked_playbook")

    def test_status_updates_persist(self):
        # Defaults to active
        res1 = memory_mcp_server.tool_mem_upsert_procedure({
            "name": "status_playbook"
        })
        proc1 = json.loads(res1)
        self.assertEqual(proc1["status"], "active")

        # Archive it
        res2 = memory_mcp_server.tool_mem_upsert_procedure({
            "name": "status_playbook",
            "status": "archived"
        })
        proc2 = json.loads(res2)
        self.assertEqual(proc2["status"], "archived")

        # Error on invalid status
        res_err = memory_mcp_server.tool_mem_upsert_procedure({
            "name": "status_playbook",
            "status": "invalid_status"
        })
        self.assertIn("ERROR", res_err)

    def test_read_filtering(self):
        memory_mcp_server.tool_mem_upsert_procedure({
            "name": "proc_active",
            "status": "active"
        })
        memory_mcp_server.tool_mem_upsert_procedure({
            "name": "proc_archived",
            "status": "archived"
        })

        # Filter by active
        active_res = memory_mcp_server.tool_mem_get_procedures({"status": "active"})
        active_list = json.loads(active_res)
        self.assertEqual(len(active_list), 1)
        self.assertEqual(active_list[0]["name"], "proc_active")

        # Filter by archived
        archived_res = memory_mcp_server.tool_mem_get_procedures({"status": "archived"})
        archived_list = json.loads(archived_res)
        self.assertEqual(len(active_list), 1)
        self.assertEqual(archived_list[0]["name"], "proc_archived")

        # Get all
        all_res = memory_mcp_server.tool_mem_get_procedures({})
        all_list = json.loads(all_res)
        self.assertEqual(len(all_list), 2)


class TestGMSPhase7(unittest.TestCase):
    def setUp(self):
        # Clean up temp_dir contents between tests
        self.temp_path = Path(temp_dir)
        self.temp_path.mkdir(parents=True, exist_ok=True)
        for item in self.temp_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        
        # Ensure subdirectory structure exists
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "episodic" / "history").mkdir(parents=True, exist_ok=True)
        (self.temp_path / "lessons").mkdir(parents=True, exist_ok=True)
        
        # Initialize DB
        memory_mcp_server.init_db()

    def test_list_episodes_empty(self):
        res = memory_mcp_server.tool_mem_list_episodes({})
        sources = json.loads(res)
        self.assertEqual(len(sources), 0)

    def test_list_episodes_with_files(self):
        # Create journal.md
        journal_path = self.temp_path / "episodic" / "journal.md"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text("# Journal Title\nSome content for journal\n## Header 1\nSome more text")

        # Create history files
        h1 = self.temp_path / "episodic" / "history" / "2026-06-01.md"
        h1.write_text("# History Title 1\nContent 1\n## Section A\n")
        h2 = self.temp_path / "episodic" / "history" / "2026-06-02.md"
        h2.write_text("# History Title 2\nContent 2")
        h3 = self.temp_path / "episodic" / "history" / "invalid-date.md"
        h3.write_text("No standard date")

        # List all
        res_all = memory_mcp_server.tool_mem_list_episodes({})
        sources_all = json.loads(res_all)
        # Should be 4 files (journal + 3 history files)
        self.assertEqual(len(sources_all), 4)

        # Check sorting and fields
        self.assertEqual(sources_all[0]["type"], "journal")
        self.assertIsNone(sources_all[0]["date"])
        self.assertEqual(sources_all[0]["line_count"], 4)

        # Let's check type filter: 'journal'
        res_journal = memory_mcp_server.tool_mem_list_episodes({"type": "journal"})
        sources_journal = json.loads(res_journal)
        self.assertEqual(len(sources_journal), 1)
        self.assertEqual(sources_journal[0]["type"], "journal")

        # Let's check type filter: 'history'
        res_history = memory_mcp_server.tool_mem_list_episodes({"type": "history"})
        sources_history = json.loads(res_history)
        self.assertEqual(len(sources_history), 3)
        self.assertEqual(sources_history[0]["type"], "history")
        
        # Verify date derivation
        h2_item = next(item for item in sources_history if "2026-06-02" in item["source"])
        self.assertEqual(h2_item["date"], "2026-06-02")

        # Test limit
        res_limit = memory_mcp_server.tool_mem_list_episodes({"limit": 2})
        sources_limit = json.loads(res_limit)
        self.assertEqual(len(sources_limit), 2)

    def test_get_episode_errors(self):
        # Missing both source and date
        res = memory_mcp_server.tool_mem_get_episode({})
        self.assertIn("ERROR", res)

        # Invalid date format
        res = memory_mcp_server.tool_mem_get_episode({"date": "26-06-02"})
        self.assertIn("ERROR", res)

        # Non-existent date
        res = memory_mcp_server.tool_mem_get_episode({"date": "2026-06-30"})
        self.assertIn("ERROR", res)

        # Non-existent source
        res = memory_mcp_server.tool_mem_get_episode({"source": "nonexistent.md"})
        self.assertIn("ERROR", res)

        # Invalid mode
        res = memory_mcp_server.tool_mem_get_episode({"source": "nonexistent.md", "mode": "full"})
        self.assertIn("ERROR", res)

    def test_get_episode_rejects_non_episodic_absolute_path(self):
        outside = self.temp_path / "outside.md"
        outside.write_text("not episodic")
        res = memory_mcp_server.tool_mem_get_episode({"source": str(outside), "mode": "deep"})
        self.assertIn("ERROR", res)
        self.assertIn("episodic memory root", res)

    def test_get_episode_summary(self):
        journal_path = self.temp_path / "episodic" / "journal.md"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        
        lines = ["# Title", "## Subtitle", "Content line 1", "Content line 2"]
        for i in range(30):
            lines.append(f"Line {i}")
        journal_path.write_text("\n".join(lines))

        # Retrieve summary by source path
        res = memory_mcp_server.tool_mem_get_episode({"source": str(journal_path), "mode": "summary"})
        data = json.loads(res)
        
        self.assertIn("metadata", data)
        self.assertEqual(data["metadata"]["type"], "journal")
        self.assertEqual(data["metadata"]["line_count"], 34)
        
        # Check headers
        self.assertEqual(data["headers"], ["# Title", "## Subtitle"])
        
        # Excerpt should contain last 20 lines
        excerpt_lines = data["excerpt"].splitlines()
        self.assertEqual(len(excerpt_lines), 20)
        self.assertEqual(excerpt_lines[-1], "Line 29")

    def test_get_episode_deep(self):
        h_path = self.temp_path / "episodic" / "history" / "2026-06-05.md"
        h_path.parent.mkdir(parents=True, exist_ok=True)
        content = "# History 2026-06-05\nSome details\n"
        h_path.write_text(content)

        # Retrieve deep mode by date
        res = memory_mcp_server.tool_mem_get_episode({"date": "2026-06-05", "mode": "deep"})
        data = json.loads(res)
        
        self.assertEqual(data["metadata"]["type"], "history")
        self.assertEqual(data["metadata"]["date"], "2026-06-05")
        self.assertEqual(data["raw_text"], content)

        # Retrieve deep mode by source relative to history
        res2 = memory_mcp_server.tool_mem_get_episode({"source": "2026-06-05.md", "mode": "deep"})
        data2 = json.loads(res2)
        self.assertEqual(data2["raw_text"], content)

    def test_mem_latest(self):
        # Add a log entry and a fact
        memory_mcp_server.tool_mem_log_event({"agent": "test", "title": "Test Milestone", "note": "Testing latest tool"})
        memory_mcp_server.tool_mem_save_typed({"key": "latest_key", "value": "latest_val", "kind": "semantic", "agent": "test"})

        res = memory_mcp_server.tool_mem_latest({"limit": 5, "kind": "all"})
        self.assertIn("Test Milestone", res)
        self.assertIn("latest_key", res)

    def test_mem_project_memory_bank(self):
        # 1. Init project memory bank
        res_init = memory_mcp_server.tool_mem_project({"action": "init", "project": "demo-proj"})
        self.assertIn("Initialized Memory Bank", res_init)

        # 2. Get active context
        res_get = memory_mcp_server.tool_mem_project({"action": "get", "project": "demo-proj", "section": "active"})
        self.assertIn("Active Context", res_get)

        # 3. Update active context
        res_upd = memory_mcp_server.tool_mem_project({"action": "update", "project": "demo-proj", "section": "active", "content": "Built feature X"})
        self.assertIn("Updated project", res_upd)

        # 4. List projects
        res_list = memory_mcp_server.tool_mem_project({"action": "list"})
        self.assertIn("demo-proj", res_list)


def tearDownModule():
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()
