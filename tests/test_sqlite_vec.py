import json
import os
import sys
import unittest
import tempfile
import sqlite3
from pathlib import Path

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import memory_mcp_server


class TestSQLiteVec(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        self.old_db_path = memory_mcp_server.DB_PATH
        memory_mcp_server.MEM_ROOT = self.temp_path
        memory_mcp_server.DB_PATH = self.temp_path / "gms_trust.sqlite"
        (self.temp_path / "semantic").mkdir(parents=True, exist_ok=True)
        memory_mcp_server.init_db()

    def tearDown(self):
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        memory_mcp_server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_store_and_search_sqlite_embeddings(self):
        # Create test embedding items (4-dimensional for simple verification)
        items = [
            {
                "source": "journal.md",
                "chunk": 0,
                "text": "AlphaOS algorithmic swing trading system in production",
                "embedding": [1.0, 0.0, 0.0, 0.0]
            },
            {
                "source": "journal.md",
                "chunk": 1,
                "text": "Minipc compute cluster running ubuntu on tailscale",
                "embedding": [0.0, 1.0, 0.0, 0.0]
            },
            {
                "source": "notes.md",
                "chunk": 0,
                "text": "Twitch two-tower recommendation model training",
                "embedding": [0.0, 0.0, 1.0, 0.0]
            }
        ]

        stored = memory_mcp_server.store_sqlite_embeddings(items, model="test-model")
        self.assertEqual(stored, 3)

        # Verify DB directly
        conn = sqlite3.connect(str(memory_mcp_server.DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM gms_embeddings")
        self.assertEqual(cursor.fetchone()[0], 3)
        conn.close()

        # Query for item closest to AlphaOS [1.0, 0.1, 0.0, 0.0]
        query_vec = [1.0, 0.1, 0.0, 0.0]
        hits = memory_mcp_server.search_sqlite_embeddings(query_vec, top_k=2, model="test-model")
        self.assertTrue(len(hits) > 0)
        self.assertIn("AlphaOS", hits[0]["text"])
        self.assertTrue(hits[0]["score"] > 0.9)

        # Query for item closest to Minipc [0.0, 1.0, 0.0, 0.0]
        hits2 = memory_mcp_server.search_sqlite_embeddings([0.0, 1.0, 0.0, 0.0], top_k=1, model="test-model")
        self.assertEqual(len(hits2), 1)
        self.assertIn("Minipc", hits2[0]["text"])


if __name__ == "__main__":
    unittest.main()
