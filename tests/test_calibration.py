import os
import sys
import tempfile

# Ensure MEMORY_ROOT is set before importing any GMS tools
# so they do not fall back to live home memories directory.
if not os.environ.get("MEMORY_ROOT"):
    os.environ["MEMORY_ROOT"] = tempfile.mkdtemp()

import json
import sqlite3
import unittest
from pathlib import Path
from argparse import Namespace

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import dream_cycle
import memoryctl
import memory_mcp_server


class TestBoundedTrustCalibration(unittest.TestCase):
    def setUp(self):
        # We will use a temporary directory for memory roots
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "gms_trust.sqlite"

        # Patch dream_cycle and memoryctl MEM_ROOT
        self.old_dream_mem_root = dream_cycle.MEM_ROOT
        self.old_memoryctl_mem_root = memoryctl.MEM_ROOT
        self.old_mcp_db_path = memory_mcp_server.DB_PATH
        self.old_mcp_mem_root = memory_mcp_server.MEM_ROOT

        dream_cycle.MEM_ROOT = self.root
        memoryctl.MEM_ROOT = self.root
        memory_mcp_server.DB_PATH = self.db_path
        memory_mcp_server.MEM_ROOT = self.root

        # Create needed tables
        self.init_test_db()

    def tearDown(self):
        # Restore original settings
        dream_cycle.MEM_ROOT = self.old_dream_mem_root
        memoryctl.MEM_ROOT = self.old_memoryctl_mem_root
        memory_mcp_server.DB_PATH = self.old_mcp_db_path
        memory_mcp_server.MEM_ROOT = self.old_mcp_mem_root
        self.temp_dir.cleanup()

    def init_test_db(self):
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gms_claims (
                claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_kind TEXT,
                memory_key TEXT,
                value TEXT,
                agent_id TEXT,
                branch TEXT,
                status TEXT,
                supersedes_claim_id INTEGER,
                confidence REAL DEFAULT 1.0,
                contradiction_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gms_agent_reputation (
                agent_id TEXT PRIMARY KEY,
                alpha REAL,
                beta REAL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def test_generate_calibration_report(self):
        # Insert mock claims
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                # k1: overlapping, agreement between A and B, A later updated
                ("semantic", "k1", "v1", "agent_A", "active"),
                ("semantic", "k1", "v1", "agent_B", "active"),
                # k2: overlapping, disagreement between A and B
                ("semantic", "k2", "val_A", "agent_A", "active"),
                ("semantic", "k2", "val_B", "agent_B", "active"),
                # k3: single observer, no overlap
                ("semantic", "k3", "val_C", "agent_C", "active"),
            ]
        )
        conn.commit()
        conn.close()

        report = dream_cycle.generate_calibration_report(self.db_path)
        self.assertEqual(report["overlapping_keys_count"], 2) # k1 and k2 have >1 observers
        
        agents = report["agents"]
        self.assertIn("agent_A", agents)
        self.assertIn("agent_B", agents)
        self.assertIn("agent_C", agents)

        # agent_A shares k1 (agrees with B) and k2 (disagrees with B)
        self.assertEqual(agents["agent_A"]["overlap_count"], 2)
        self.assertEqual(agents["agent_A"]["agreement_count"], 1)
        self.assertEqual(agents["agent_A"]["disagreement_count"], 1)
        self.assertEqual(agents["agent_A"]["agreement_rate"], 0.5)

        # agent_B shares k1 (agrees with A) and k2 (disagrees with A)
        self.assertEqual(agents["agent_B"]["overlap_count"], 2)
        self.assertEqual(agents["agent_B"]["agreement_count"], 1)
        self.assertEqual(agents["agent_B"]["disagreement_count"], 1)
        self.assertEqual(agents["agent_B"]["agreement_rate"], 0.5)

        # agent_C has no overlap
        self.assertEqual(agents["agent_C"]["overlap_count"], 0)
        self.assertEqual(agents["agent_C"]["agreement_count"], 0)
        self.assertEqual(agents["agent_C"]["disagreement_count"], 0)
        self.assertEqual(agents["agent_C"]["agreement_rate"], 0.0)

    def test_calibration_skips_on_insufficient_overlap(self):
        # Insert non-overlapping claims only
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
            ("agent_A", 10.0, 2.0)
        )
        cursor.executemany(
            """
            INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("semantic", "k1", "v1", "agent_A", "active"),
                ("semantic", "k2", "v2", "agent_B", "active"),
            ]
        )
        conn.commit()
        conn.close()

        # Calibration should skip since overlapping_keys_count is 0
        dream_cycle.run_beta_binomial_trust_calibration()

        # Verify agent_A's reputation is NOT modified or overwritten
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT alpha, beta FROM gms_agent_reputation WHERE agent_id = ?", ("agent_A",))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 10.0)
        self.assertEqual(row[1], 2.0)

    def test_calibration_avoids_clobbering_sparse_agent(self):
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        # Seed reputations
        cursor.execute("INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)", ("agent_A", 5.0, 1.0))
        cursor.execute("INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)", ("agent_sparse", 8.0, 0.0))
        
        cursor.executemany(
            """
            INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                # agent_A overlaps with agent_B on k1
                ("semantic", "k1", "v1", "agent_A", "active"),
                ("semantic", "k1", "v1", "agent_B", "active"),
                # agent_sparse is single observer on k2
                ("semantic", "k2", "v2", "agent_sparse", "active"),
            ]
        )
        conn.commit()
        conn.close()

        # Calibration should run (1 overlapping key: k1)
        # But agent_sparse should be skipped because overlap_count = 0
        dream_cycle.run_beta_binomial_trust_calibration()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        # agent_A should be calibrated
        cursor.execute("SELECT alpha, beta FROM gms_agent_reputation WHERE agent_id = ?", ("agent_A",))
        row_A = cursor.fetchone()
        # agent_sparse should NOT be calibrated or modified
        cursor.execute("SELECT alpha, beta FROM gms_agent_reputation WHERE agent_id = ?", ("agent_sparse",))
        row_sparse = cursor.fetchone()
        conn.close()

        # agent_A: overlap=1 (agrees with B), alpha=1+1.0=2.0, beta=0+0.0=0.0
        self.assertEqual(row_A[0], 2.0)
        self.assertEqual(row_A[1], 0.0)

        # agent_sparse: remained unchanged at 8.0, 0.0
        self.assertEqual(row_sparse[0], 8.0)
        self.assertEqual(row_sparse[1], 0.0)

    def test_cli_and_mcp_calibration_report(self):
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("semantic", "k1", "v1", "agent_A", "active"),
                ("semantic", "k1", "v1", "agent_B", "active"),
            ]
        )
        conn.commit()
        conn.close()

        # Test CLI subcommand: calibration-report --json
        args = Namespace(json=True)
        # Mock printing stdout
        import io
        from unittest.mock import patch
        
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            code = memoryctl.cmd_calibration_report(args)
            self.assertEqual(code, 0)
            output = fake_out.getvalue().strip()
            data = json.loads(output)
            self.assertEqual(data["overlapping_keys_count"], 1)
            self.assertIn("agent_A", data["agents"])

        # Test MCP tool_mem_calibration_report
        from unittest.mock import patch

        with patch.object(memory_mcp_server, "_run_memoryctl", return_value=(0, output)):
            mcp_res = memory_mcp_server.tool_mem_calibration_report({})
        mcp_data = json.loads(mcp_res)
        self.assertEqual(mcp_data["overlapping_keys_count"], 1)
        self.assertIn("agent_A", mcp_data["agents"])


if __name__ == "__main__":
    unittest.main()
