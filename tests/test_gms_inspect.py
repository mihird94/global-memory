import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

tools_dir = str(Path(__file__).parent.parent / "tools")
if tools_dir not in sys.path:
    sys.path.insert(0, tools_dir)

import gms_inspect


class TestGMSInspect(unittest.TestCase):
    def test_snapshot_reports_counts_and_recent_episodes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_mem_root = gms_inspect.MEM_ROOT
            old_db_path = gms_inspect.DB_PATH
            try:
                gms_inspect.MEM_ROOT = root
                gms_inspect.DB_PATH = root / "gms_trust.sqlite"

                (root / "semantic").mkdir(parents=True, exist_ok=True)
                (root / "operational").mkdir(parents=True, exist_ok=True)
                (root / "procedural").mkdir(parents=True, exist_ok=True)
                (root / "episodic" / "history").mkdir(parents=True, exist_ok=True)

                (root / "semantic" / "facts.json").write_text(json.dumps({"a": "1", "b": "2"}))
                (root / "operational" / "facts.json").write_text(json.dumps({"cfg": "x"}))
                (root / "procedural" / "facts.json").write_text(json.dumps({"playbook": "y"}))
                (root / "episodic" / "journal.md").write_text("journal")
                (root / "episodic" / "history" / "2026-06-04.md").write_text("history")

                conn = sqlite3.connect(str(gms_inspect.DB_PATH))
                cursor = conn.cursor()
                cursor.execute("CREATE TABLE gms_claims (status TEXT)")
                cursor.execute("CREATE TABLE gms_quarantined_facts (fact_key TEXT, agent_id TEXT, branch TEXT, timestamp TEXT)")
                cursor.execute("CREATE TABLE gms_quarantine_reviews (reviewer_id TEXT)")
                cursor.execute("CREATE TABLE gms_procedures (name TEXT)")
                cursor.execute("CREATE TABLE gms_entities (name TEXT)")
                cursor.execute("CREATE TABLE gms_relationships (predicate TEXT)")
                cursor.executemany(
                    "INSERT INTO gms_claims (status) VALUES (?)",
                    [("active",), ("active",), ("quarantined",), ("archived",)],
                )
                cursor.execute(
                    "INSERT INTO gms_quarantined_facts (fact_key, agent_id, branch, timestamp) VALUES ('bad_fact', 'agent_bad', 'main', '2026-06-04 12:00:00')"
                )
                cursor.execute("INSERT INTO gms_quarantine_reviews (reviewer_id) VALUES ('reviewer_1')")
                cursor.execute("INSERT INTO gms_procedures (name) VALUES ('proc_1')")
                cursor.execute("INSERT INTO gms_entities (name) VALUES ('entity_1')")
                cursor.execute("INSERT INTO gms_relationships (predicate) VALUES ('uses')")
                conn.commit()
                conn.close()

                snapshot = gms_inspect.build_snapshot()
            finally:
                gms_inspect.MEM_ROOT = old_mem_root
                gms_inspect.DB_PATH = old_db_path

        self.assertEqual(snapshot["facts"]["semantic"], 2)
        self.assertEqual(snapshot["facts"]["operational"], 1)
        self.assertEqual(snapshot["facts"]["procedural"], 1)
        self.assertEqual(snapshot["episodes"]["count"], 2)
        self.assertEqual(snapshot["db"]["claims_by_status"]["active"], 2)
        self.assertEqual(snapshot["db"]["claims_by_status"]["archived"], 1)
        self.assertEqual(snapshot["db"]["quarantined_facts"], 1)
        self.assertEqual(snapshot["db"]["quarantine_reviews"], 1)
        self.assertEqual(snapshot["db"]["procedures"], 1)
        self.assertEqual(snapshot["db"]["entities"], 1)
        self.assertEqual(snapshot["db"]["relationships"], 1)
        self.assertEqual(snapshot["quarantine"]["recent"][0]["fact_key"], "bad_fact")


if __name__ == "__main__":
    unittest.main()
