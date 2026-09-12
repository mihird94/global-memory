#!/usr/bin/env python3
"""
tests/test_dry_run_isolation.py — Ensure dry-run zero-durable-mutation guarantee.
"""

import hashlib
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

import dream_cycle
import memory_mcp_server


class TestDryRunIsolation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.mem_root = Path(self.temp_dir.name)
        self.old_dream_root = dream_cycle.MEM_ROOT
        self.old_mcp_root = memory_mcp_server.MEM_ROOT
        dream_cycle.MEM_ROOT = self.mem_root
        memory_mcp_server.MEM_ROOT = self.mem_root

        # Seed sample daily note
        history_dir = self.mem_root / "episodic" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self.today_file = history_dir / f"{today}.md"
        self.today_file.write_text(
            f"# {today} Work Log\nWe decided to enforce WAL mode across all DB connections.\n",
            encoding="utf-8",
        )

        # Seed facts.json and gms_trust.sqlite
        facts_dir = self.mem_root / "semantic"
        facts_dir.mkdir(parents=True, exist_ok=True)
        self.facts_path = facts_dir / "facts.json"
        self.facts_path.write_text("{}", encoding="utf-8")

        self.db_path = self.mem_root / "gms_trust.sqlite"
        memory_mcp_server.init_db(self.db_path)

    def tearDown(self):
        dream_cycle.MEM_ROOT = self.old_dream_root
        memory_mcp_server.MEM_ROOT = self.old_mcp_root
        self.temp_dir.cleanup()

    def _hash_file(self, p: Path) -> str:
        if not p.exists():
            return "absent"
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def _sample_candidate(self):
        return {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "test.dry_run_decision",
            "statement": "Use WAL mode everywhere.",
            "rationale": "High concurrency across multiple agents requires non-blocking reads.",
            "implications": ["Specify busy_timeout=5000 on connections."],
            "scope": {"project": "global-memory", "level": "system"},
            "provenance": {
                "extractor": "TestExtractor",
                "extracted_at": "2026-09-08T18:00:00Z",
                "source_refs": ["episodic/history/2026-09-08.md"],
                "source_hashes": ["sha256:abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234"],
            },
            "evidence": [{"type": "source_document", "ref": "episodic/history/2026-09-08.md"}],
            "review": {"status": "proposed", "requires_human": True},
        }

    def test_dry_run_zero_durable_writes_and_status(self):
        facts_before = self._hash_file(self.facts_path)
        db_before = self._hash_file(self.db_path)
        note_before = self._hash_file(self.today_file)

        mock_candidate = self._sample_candidate()

        with patch.object(sys, "argv", ["dream_cycle.py", "--dry-run"]),              patch("dream_cycle.extract_candidates_with_cascade", return_value=([mock_candidate], "antigravity")),              patch("dream_cycle.unload_ollama_model"):
            exit_code = dream_cycle.main()
            self.assertEqual(exit_code, 0)

        # 1. Assert zero files were mutated
        self.assertEqual(self._hash_file(self.facts_path), facts_before, "facts.json must not change")
        self.assertEqual(self._hash_file(self.db_path), db_before, "gms_trust.sqlite must not change")
        self.assertEqual(self._hash_file(self.today_file), note_before, "daily note must not change")

        # 2. Assert dream_cycle_status.json was NOT written on disk in dry run
        status_file = self.mem_root / "logs" / "dream_cycle_status.json"
        self.assertFalse(status_file.exists(), "dream_cycle_status.json must not be written in dry run")

        # 3. Assert in-memory status exposes dry_run contracts
        last_status = dream_cycle.LAST_RUN_STATUS
        self.assertTrue(last_status.get("dry_run"), "status must declare dry_run: true")
        self.assertEqual(last_status.get("durable_writes"), 0, "status must declare durable_writes: 0")
        self.assertIn("test.dry_run_decision", last_status.get("candidates_would_stage", []))
        self.assertIn("test.dry_run_decision", last_status.get("candidates_extracted", []))

    def test_regression_monkeypatch_write_interceptor(self):
        """Fail test if any durable write is attempted during dry run."""
        orig_get_conn = memory_mcp_server.get_db_connection

        def write_guard_connection(target_path):
            conn = orig_get_conn(target_path)
            orig_cursor = conn.cursor

            def guarded_cursor(*args, **kwargs):
                cur = orig_cursor(*args, **kwargs)
                cur_execute = cur.execute

                def checked_execute(sql, *p_args, **p_kwargs):
                    sql_upper = str(sql).strip().upper()
                    if any(sql_upper.startswith(w) for w in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE TABLE")):
                        raise RuntimeError(f"Forbidden SQLite write during dry run: {sql_upper[:40]}")
                    return cur_execute(sql, *p_args, **p_kwargs)

                cur.execute = checked_execute
                return cur

            conn.cursor = guarded_cursor
            return conn

        mock_candidate = self._sample_candidate()

        with patch.object(sys, "argv", ["dream_cycle.py", "--dry-run"]),              patch("memory_mcp_server.get_db_connection", side_effect=write_guard_connection),              patch("dream_cycle.extract_candidates_with_cascade", return_value=([mock_candidate], "antigravity")),              patch("dream_cycle.unload_ollama_model"):
            exit_code = dream_cycle.main()
            self.assertEqual(exit_code, 0)
            self.assertEqual(dream_cycle.LAST_RUN_STATUS.get("durable_writes"), 0)
