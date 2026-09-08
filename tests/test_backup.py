import os
import sys
import unittest
import tempfile
import sqlite3
from pathlib import Path

# Add tools directory to sys.path
tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import backup_db


class TestGMSBackup(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.db_path = self.mem_root / "gms_trust.sqlite"
        self.bak_path = self.mem_root / "gms_trust.sqlite.bak"

        # Create a mock database with sample data
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_memories (id INTEGER PRIMARY KEY, content TEXT)")
        cursor.execute("CREATE TABLE test_facts (key TEXT PRIMARY KEY, val TEXT)")
        cursor.execute("INSERT INTO test_memories (content) VALUES ('Initial memory record')")
        cursor.execute("INSERT INTO test_facts (key, val) VALUES ('agent', 'antigravity')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backup_creates_valid_backup(self):
        report = backup_db.backup_database(mem_root=self.mem_root, dest_path=self.bak_path)
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["integrity"], "ok")
        self.assertEqual(report["table_count"], 2)
        self.assertTrue(self.bak_path.exists())
        self.assertGreater(report["size_bytes"], 0)

        # Verify content in backup
        conn = sqlite3.connect(str(self.bak_path))
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM test_memories")
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Initial memory record")
        conn.close()

    def test_backup_overwrites_existing_backup_cleanly(self):
        # Run first backup
        rep1 = backup_db.backup_database(mem_root=self.mem_root, dest_path=self.bak_path)
        self.assertEqual(rep1["status"], "success")

        # Mutate the source DB
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("INSERT INTO test_memories (content) VALUES ('Second memory record')")
        conn.commit()
        conn.close()

        # Run second backup (should cleanly overwrite)
        rep2 = backup_db.backup_database(mem_root=self.mem_root, dest_path=self.bak_path)
        self.assertEqual(rep2["status"], "success")
        self.assertEqual(rep2["integrity"], "ok")

        # Verify backup contains updated data
        conn = sqlite3.connect(str(self.bak_path))
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM test_memories")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 2)
        conn.close()

    def test_backup_missing_source_db(self):
        missing_root = self.mem_root / "nonexistent"
        report = backup_db.backup_database(mem_root=missing_root)
        self.assertEqual(report["status"], "error")
        self.assertIn("Source DB does not exist", report["message"])


if __name__ == "__main__":
    unittest.main()
