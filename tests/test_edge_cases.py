#!/usr/bin/env python3
"""
tests/test_edge_cases.py — Comprehensive Test Suite for Missing Edge Cases
=============================================================================
Tests:
  1. Concurrent SQLite write lock contention (WAL mode, thread contention, lock recovery)
  2. Corrupt journal.md parsing (binary corruption, malformed headers, empty files, unclosed fences)
  3. Network outage during Ollama embedding (connection refused, timeouts, graceful fallback)
  4. launchd recovery & database restore (restore from .bak, corruption recovery, backup integrity)
  5. AppleScript timeout & permission handling (subprocess.TimeoutExpired, -1743 error, escaping)
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add tools directory to sys.path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import backup_db
import harvest
import memory_mcp_server
import memoryctl
import migrate_journal_to_daily


# ==============================================================================
# 1. Concurrent SQLite Write Lock Contention Tests
# ==============================================================================

class TestConcurrentSQLiteContention:
    @pytest.fixture(autouse=True)
    def setup_isolated_env(self, tmp_path):
        old_root = memory_mcp_server.MEM_ROOT
        old_db = memory_mcp_server.DB_PATH
        self.mem_root = tmp_path / "memories"
        self.mem_root.mkdir(parents=True, exist_ok=True)
        (self.mem_root / "semantic").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "episodic" / "history").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "lessons").mkdir(parents=True, exist_ok=True)
        self.db_path = self.mem_root / "gms_trust.sqlite"

        # Initialize schema
        memory_mcp_server.MEM_ROOT = self.mem_root
        memory_mcp_server.DB_PATH = self.db_path
        memory_mcp_server.init_db(self.db_path)

        # Enable WAL mode for high concurrency
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
        conn.close()

        yield

        memory_mcp_server.MEM_ROOT = old_root
        memory_mcp_server.DB_PATH = old_db

    def test_concurrent_multithreaded_claim_writes(self):
        """Verify multiple threads writing claims concurrently do not corrupt DB or crash."""
        num_threads = 8
        writes_per_thread = 15

        def writer_worker(thread_id: int):
            for i in range(writes_per_thread):
                conn = sqlite3.connect(str(self.db_path), timeout=10.0)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO gms_claims (
                        memory_kind, memory_key, value, agent_id, branch, status, confidence
                    ) VALUES (?, ?, ?, ?, 'main', 'active', 1.0)
                    """,
                    ("semantic", f"thread_key_{thread_id}_{i}", f"val_{thread_id}_{i}", f"agent_{thread_id}")
                )
                conn.commit()
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(writer_worker, t) for t in range(num_threads)]
            for f in concurrent.futures.as_completed(futures):
                f.result()  # Should not raise OperationalError

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM gms_claims")
        total_claims = cursor.fetchone()[0]
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        conn.close()

        assert total_claims == num_threads * writes_per_thread
        assert integrity == "ok"

    def test_write_lock_contention_and_recovery(self):
        """Test behavior when a thread holds an exclusive lock and another attempts to write."""
        lock_acquired = threading.Event()
        can_release_lock = threading.Event()
        contention_detected = []

        def lock_holder():
            conn = sqlite3.connect(str(self.db_path), isolation_level=None)
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute("INSERT INTO gms_claims (memory_kind, memory_key, value) VALUES ('sem', 'locked_key', '1')")
            lock_acquired.set()
            can_release_lock.wait(timeout=5.0)
            conn.execute("COMMIT")
            conn.close()

        t_holder = threading.Thread(target=lock_holder)
        t_holder.start()

        assert lock_acquired.wait(timeout=3.0)

        # Attempt to write with very short timeout (should hit lock contention)
        try:
            blocked_conn = sqlite3.connect(str(self.db_path), timeout=0.1)
            blocked_conn.execute("BEGIN IMMEDIATE")
            blocked_conn.execute("INSERT INTO gms_claims (memory_kind, memory_key, value) VALUES ('sem', 'k2', '2')")
            blocked_conn.commit()
            blocked_conn.close()
        except sqlite3.OperationalError as e:
            contention_detected.append(str(e))

        # Release the lock
        can_release_lock.set()
        t_holder.join()

        assert len(contention_detected) == 1
        assert "locked" in contention_detected[0].lower()

        # Verify DB is completely healthy after lock release
        healthy_conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        healthy_conn.execute("INSERT INTO gms_claims (memory_kind, memory_key, value) VALUES ('sem', 'after_unlock', '3')")
        healthy_conn.commit()
        cursor = healthy_conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        assert cursor.fetchone()[0] == "ok"
        healthy_conn.close()

    def test_concurrent_init_db_idempotence(self):
        """Verify calling init_db concurrently across 10 threads is safe and idempotent."""
        def run_init():
            memory_mcp_server.init_db(self.db_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(run_init) for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]
        conn.close()
        assert table_count >= 8


# ==============================================================================
# 2. Corrupt journal.md Parsing Tests
# ==============================================================================

class TestCorruptJournalParsing:
    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path):
        old_root = memory_mcp_server.MEM_ROOT
        old_db = memory_mcp_server.DB_PATH
        self.mem_root = tmp_path / "memories"
        self.mem_root.mkdir(parents=True, exist_ok=True)
        self.episodic_dir = self.mem_root / "episodic"
        self.history_dir = self.episodic_dir / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.episodic_dir / "journal.md"
        memory_mcp_server.MEM_ROOT = self.mem_root

        yield

        memory_mcp_server.MEM_ROOT = old_root
        memory_mcp_server.DB_PATH = old_db

    def test_corrupt_binary_null_bytes_parsing(self):
        """Verify parsing handles null bytes and invalid UTF-8 without raising UnicodeDecodeError."""
        corrupt_bytes = b"# Valid Header\nSome regular log text\x00\xff\xfe\x80\x81Corrupted binary trailing"
        self.journal_path.write_bytes(corrupt_bytes)

        # tool_mem_get_episode summary
        res = memory_mcp_server.tool_mem_get_episode({
            "source": str(self.journal_path),
            "mode": "summary"
        })
        parsed = json.loads(res)
        assert parsed["metadata"]["type"] == "journal"
        assert "# Valid Header" in parsed["headers"]
        assert parsed["metadata"]["line_count"] >= 1

        # tool_mem_get_episode deep
        res_deep = memory_mcp_server.tool_mem_get_episode({
            "source": str(self.journal_path),
            "mode": "deep"
        })
        parsed_deep = json.loads(res_deep)
        assert "Valid Header" in parsed_deep["raw_content"]

    def test_malformed_headers_migration_graceful_handling(self):
        """Verify migrate_journal handles broken, missing, or corrupt date headers."""
        corrupt_content = (
            "### Not A Date\n"
            "This entry has no date format.\n\n"
            "### 2026-99-99 Invalid Month Date\n"
            "This entry has an impossible calendar date.\n\n"
            "###   \n"
            "Empty header whitespace\n\n"
            "### 2026-08-15 Valid Date Entry\n"
            "- Legitimate milestone completed.\n"
        )
        self.journal_path.write_text(corrupt_content)

        report = migrate_journal_to_daily.migrate_journal(mem_root=self.mem_root, backup=False)
        assert report["migrated_days"] >= 1

        # Only the valid YYYY-MM-DD format should produce a daily file
        assert (self.history_dir / "2026-08-15.md").exists()
        daily_text = (self.history_dir / "2026-08-15.md").read_text()
        assert "Legitimate milestone completed." in daily_text

    def test_empty_or_whitespace_journal_abstention(self):
        """Verify empty journal does not crash and returns clean metadata/abstention."""
        self.journal_path.write_text("   \n\t  \n  ")
        res = memory_mcp_server.tool_mem_get_episode({
            "source": str(self.journal_path),
            "mode": "summary"
        })
        parsed = json.loads(res)
        assert parsed["headers"] == []
        assert parsed["excerpt"] == ""

    def test_deeply_nested_unclosed_codeblocks(self):
        """Verify unclosed markdown blocks and special characters do not break chunking."""
        unclosed = (
            "# Session Alpha\n"
            "```python\n"
            "def broken_function():\n"
            "    # Missing closing codeblock fence\n"
            "### 2026-08-20 [14:00] - agent\n"
            "- Note inside open code block\n"
        )
        self.journal_path.write_text(unclosed)

        res = memory_mcp_server.tool_mem_get_episode({
            "source": str(self.journal_path),
            "mode": "summary"
        })
        parsed = json.loads(res)
        assert "# Session Alpha" in parsed["headers"]
        assert "### 2026-08-20 [14:00] - agent" in parsed["headers"]


# ==============================================================================
# 3. Network Outage During Ollama Embedding Tests
# ==============================================================================

class TestOllamaNetworkOutage:
    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path):
        old_root = memory_mcp_server.MEM_ROOT
        old_db = memory_mcp_server.DB_PATH
        self.mem_root = tmp_path / "memories"
        self.mem_root.mkdir(parents=True, exist_ok=True)
        (self.mem_root / "semantic").mkdir(parents=True, exist_ok=True)
        (self.mem_root / "episodic" / "history").mkdir(parents=True, exist_ok=True)
        self.db_path = self.mem_root / "gms_trust.sqlite"
        memory_mcp_server.MEM_ROOT = self.mem_root
        memory_mcp_server.DB_PATH = self.db_path
        memory_mcp_server.init_db(self.db_path)

        yield

        memory_mcp_server.MEM_ROOT = old_root
        memory_mcp_server.DB_PATH = old_db

    def test_memoryctl_embed_connection_refused_retries_and_raises(self):
        """Verify memoryctl._embed retries and raises RuntimeError on connection refused."""
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            with patch("time.sleep") as mock_sleep:
                with pytest.raises(RuntimeError) as exc_info:
                    memoryctl._embed("sample test text", "qwen3-embedding:0.6b")
                assert "embedding call failed after retries" in str(exc_info.value)
                assert mock_sleep.call_count == memoryctl.EMBED_RETRIES - 1

    def test_memory_mcp_server_embed_outage_returns_none(self):
        """Verify memory_mcp_server._embed returns None cleanly without throwing unhandled error."""
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            emb = memory_mcp_server._embed("test query")
            assert emb is None

    def test_harvest_session_persists_facts_despite_ollama_outage(self):
        """Verify session harvest still commits facts and claims even if Ollama embedding fails."""
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Ollama daemon down")):
            res = harvest.harvest_session(
                agent="agent_resilient",
                summary="Implemented fallback mechanism",
                text="[FACT:infra.redis] {'host': 'redis-cluster', 'port': 6379}",
                incremental_index=True,
                mem_root=self.mem_root,
            )

        assert res["valid_facts"] >= 1
        facts_file = self.mem_root / "semantic" / "facts.json"
        assert facts_file.exists()
        facts = json.loads(facts_file.read_text())
        assert "infra.redis" in facts
        assert facts["infra.redis"]["port"] == 6379

    def test_tool_mem_search_degrades_gracefully_during_ollama_outage(self):
        """Verify tool_mem_search does not crash when index-query fails due to Ollama outage."""
        with patch("memory_mcp_server._run_memoryctl", return_value=(1, "ERROR: embedding failed after retries")):
            res = memory_mcp_server.tool_mem_search({
                "query": "alphaos workspace",
                "mode": "high"
            })
            assert res == "No results." or "ERROR" not in res


# ==============================================================================
# 4. launchd Recovery & Database Restore Tests
# ==============================================================================

class TestLaunchdRecoveryAndRestore:
    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path):
        self.mem_root = tmp_path / "memories"
        self.mem_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.mem_root / "gms_trust.sqlite"
        self.bak_path = self.mem_root / "gms_trust.sqlite.bak"

        # Initialize sample database
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE fleet_status (id INTEGER PRIMARY KEY, status TEXT)")
        cursor.execute("INSERT INTO fleet_status (status) VALUES ('operational')")
        conn.commit()
        conn.close()

    def test_restore_database_from_valid_backup(self):
        """Verify restore_database restores state from .bak cleanly when DB is corrupted."""
        # 1. Create a valid backup
        bkp_report = backup_db.backup_database(mem_root=self.mem_root, dest_path=self.bak_path)
        assert bkp_report["status"] == "success"

        # 2. Corrupt the primary database
        self.db_path.write_bytes(b"CORRUPTED_RAW_GARBAGE_HEADER_DATA_NOT_SQLITE")

        # 3. Perform restore
        restore_report = backup_db.restore_database(
            mem_root=self.mem_root,
            backup_path=self.bak_path,
            dest_path=self.db_path
        )
        assert restore_report["status"] == "success"
        assert restore_report["integrity"] == "ok"

        # 4. Verify data was completely restored
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM fleet_status")
        val = cursor.fetchone()[0]
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        conn.close()

        assert val == "operational"
        assert integrity == "ok"

    def test_restore_refuses_corrupted_backup_file(self):
        """Verify restore refuses to restore if the backup file itself fails integrity check."""
        self.bak_path.write_bytes(b"CORRUPTED_BACKUP_FILE")
        report = backup_db.restore_database(
            mem_root=self.mem_root,
            backup_path=self.bak_path,
            dest_path=self.db_path
        )
        assert report["status"] == "error"
        assert "integrity" in report["message"].lower() or "read" in report["message"].lower()

    def test_restore_handles_missing_backup_file(self):
        """Verify restore gracefully fails when backup file does not exist."""
        nonexistent = self.mem_root / "nonexistent.bak"
        report = backup_db.restore_database(
            mem_root=self.mem_root,
            backup_path=nonexistent,
            dest_path=self.db_path
        )
        assert report["status"] == "error"
        assert "does not exist" in report["message"]

    def test_backup_handles_active_read_connections(self):
        """Verify backup succeeds online even when active reader connection is open."""
        read_conn = sqlite3.connect(str(self.db_path))
        cursor = read_conn.cursor()
        cursor.execute("SELECT count(*) FROM fleet_status")

        report = backup_db.backup_database(mem_root=self.mem_root, dest_path=self.bak_path)
        assert report["status"] == "success"
        assert report["integrity"] == "ok"

        read_conn.close()


# ==============================================================================
# 5. AppleScript Timeout & Permission Handling Tests
# ==============================================================================

class TestAppleScriptTimeoutHandling:
    def test_run_osascript_timeout_expired(self):
        """Verify _run_osascript catches subprocess.TimeoutExpired and returns exit code 124."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["osascript"], timeout=5)):
            rc, stdout, stderr = memoryctl._run_osascript("tell application \"Reminders\" to return name", timeout=5)
            assert rc == 124
            assert stdout == ""
            assert "timed out after 5 seconds" in stderr

    def test_cmd_apple_timeout_handling(self, capsys):
        """Verify memoryctl apple command reports timeout error without crashing."""
        args = argparse.Namespace(app_type="reminder", action="list")
        with patch("sys.platform", "darwin"):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["osascript"], timeout=10)):
                rc = memoryctl.cmd_apple(args)
                assert rc == 1
                captured = capsys.readouterr()
                assert "[ERROR] AppleScript execution timed out" in captured.out

    def test_cmd_apple_permission_denied_handling(self, capsys):
        """Verify permission failure (error -1743) is cleanly reported with returncode 1."""
        args = argparse.Namespace(app_type="reminder", action="list")
        mock_res = MagicMock(returncode=1, stdout="", stderr="execution error: Not authorized to send Apple events to Reminders. (-1743)")
        with patch("sys.platform", "darwin"):
            with patch("subprocess.run", return_value=mock_res):
                rc = memoryctl.cmd_apple(args)
                assert rc == 1
                captured = capsys.readouterr()
                assert "Not authorized to send Apple events" in captured.out

    def test_cmd_apple_add_reminder_quote_escaping(self):
        """Verify double quotes and injection strings are safely escaped in osascript payload."""
        args = argparse.Namespace(
            app_type="reminder",
            action="add",
            title='Buy "organic" milk & eggs',
            notes='Check expiration; "urgent"',
            due="2026-09-10"
        )
        with patch("sys.platform", "darwin"):
            with patch("memoryctl._run_osascript", return_value=(0, "", "")) as mock_run:
                rc = memoryctl.cmd_apple(args)
                assert rc == 0
                mock_run.assert_called_once()
                script = mock_run.call_args[0][0]
                assert '\\"organic\\"' in script
                assert '\\"urgent\\"' in script

    def test_cmd_apple_non_darwin_platform(self, capsys):
        """Verify executing Apple automation on Linux returns error code 1."""
        args = argparse.Namespace(app_type="reminder", action="list")
        with patch("sys.platform", "linux"):
            rc = memoryctl.cmd_apple(args)
            assert rc == 1
            captured = capsys.readouterr()
            assert "only supported on macOS" in captured.out
