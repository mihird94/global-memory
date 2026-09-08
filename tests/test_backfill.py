import json
import os
import sqlite3
import sys
import tempfile

if not os.environ.get("MEMORY_ROOT"):
    os.environ["MEMORY_ROOT"] = tempfile.mkdtemp()

import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

import backfill
import memory_mcp_server


class TestGMSBackfill(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "memories"
        (self.root / "semantic").mkdir(parents=True)
        (self.root / "operational").mkdir(parents=True)
        (self.root / "procedural").mkdir(parents=True)
        (self.root / "episodic" / "index").mkdir(parents=True)

        semantic_facts = {
            "infra.worker.alpha": {"host": "alpha-1", "status": "UP", "ip": "10.0.0.1", "role": "worker"},
            "system_name": "Antigravity Hub",
        }
        operational_facts = {
            "policy.security.strict": {"policy_id": "SEC-01", "scope": "network", "enforcement": "strict", "rule_text": "No plain http"},
        }
        procedural_facts = {
            "playbook.deploy": "When deploying code, run unit tests first, then restart the system daemon.",
        }

        (self.root / "semantic" / "facts.json").write_text(json.dumps(semantic_facts))
        (self.root / "operational" / "facts.json").write_text(json.dumps(operational_facts))
        (self.root / "procedural" / "facts.json").write_text(json.dumps(procedural_facts))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backfill_dry_run(self):
        report = backfill.run_backfill(mem_root=self.root, dry_run=True, skip_embeddings=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["claims_backfilled"], 4)
        self.assertEqual(report["procedures_backfilled"], 1)

        db_path = self.root / "gms_trust.sqlite"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            self.assertEqual(len(c.fetchall()), 0)
            conn.close()

    def test_backfill_live_and_idempotency(self):
        # Pass 1: Live Backfill
        report1 = backfill.run_backfill(mem_root=self.root, dry_run=False, skip_embeddings=True)
        self.assertEqual(report1["status"], "success")
        self.assertEqual(report1["claims_backfilled"], 4)
        self.assertEqual(report1["provenance_backfilled"], 4)
        self.assertEqual(report1["procedures_backfilled"], 1)
        self.assertGreaterEqual(report1["relationships_backfilled"], 4)

        db_path = self.root / "gms_trust.sqlite"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()

        claims = c.execute("SELECT memory_key, status, confidence FROM gms_claims").fetchall()
        self.assertEqual(len(claims), 4)
        self.assertTrue(all(r[1] == "active" for r in claims))

        procs = c.execute("SELECT name, \"trigger\", action, status, source_claim_id FROM gms_procedures").fetchall()
        self.assertEqual(len(procs), 1)
        self.assertEqual(procs[0][0], "playbook.deploy")
        self.assertEqual(procs[0][3], "active")
        self.assertIsNotNone(procs[0][4])

        rels = c.execute("SELECT relationship_id, valid_from, valid_to FROM gms_relationships").fetchall()
        self.assertGreaterEqual(len(rels), 4)
        self.assertTrue(all(r[1] is not None for r in rels))
        conn.close()

        # Pass 2: Idempotent re-run
        report2 = backfill.run_backfill(mem_root=self.root, dry_run=False, skip_embeddings=True)
        self.assertEqual(report2["claims_backfilled"], 0)
        self.assertEqual(report2["provenance_backfilled"], 0)
        self.assertEqual(report2["procedures_backfilled"], 0)

        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        count = c.execute("SELECT count(*) FROM gms_claims").fetchone()[0]
        self.assertEqual(count, 4)
        conn.close()

    def test_backfill_embeddings_mock(self):
        mock_items = [
            {"source": "test.md", "chunk": 0, "text": "Chunk zero", "embedding": [0.1, 0.2, 0.3, 0.4]},
            {"source": "test.md", "chunk": 1, "text": "Chunk one", "embedding": [0.5, 0.6, 0.7, 0.8]},
        ]
        orig_extract = backfill._extract_vectors_from_faiss
        try:
            backfill._extract_vectors_from_faiss = lambda f, m: (mock_items, "mock")
            report = backfill.run_backfill(mem_root=self.root, dry_run=False, skip_embeddings=False)
            self.assertEqual(report["embeddings_backfilled"], 2)
            self.assertEqual(report["embeddings_method"], "mock")

            db_path = self.root / "gms_trust.sqlite"
            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()
            count = c.execute("SELECT count(*) FROM gms_embeddings").fetchone()[0]
            self.assertEqual(count, 2)
            conn.close()

            results = memory_mcp_server.search_sqlite_embeddings(
                query_vector=[0.1, 0.2, 0.3, 0.4],
                top_k=1,
                db_path=db_path
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["chunk"], 0)
        finally:
            backfill._extract_vectors_from_faiss = orig_extract


if __name__ == "__main__":
    unittest.main()
