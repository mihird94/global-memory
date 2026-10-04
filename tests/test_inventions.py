"""Unit tests for GMS 3.0 Frontier Inventions:
- Reflexive Prospective Memory Traps
- Anticipatory Speculative Memory Prefetch
- Executable Programmatic Memory Guards
"""

import json
import pytest
from pathlib import Path
import memory_mcp_server


@pytest.fixture
def clean_memory_root(tmp_path, monkeypatch):
    root = tmp_path / "memories"
    root.mkdir()
    (root / "operational").mkdir()
    (root / "semantic").mkdir()
    db_path = root / "gms_trust.sqlite"
    monkeypatch.setattr(memory_mcp_server, "MEM_ROOT", root)
    monkeypatch.setattr(memory_mcp_server, "DB_PATH", db_path)
    return root


def test_prospective_trap_lifecycle(clean_memory_root):
    # 1. Create a one-shot trap
    res = json.loads(memory_mcp_server.tool_mem_trap_create({
        "name": "sqlite_lock_tripwire",
        "pattern": r".*PRAGMA\s+journal_mode.*",
        "payload": "ALERT: SQLite locks detected. Ensure WAL mode is active.",
        "trigger_type": "command",
        "recurring": False,
        "agent": "Antigravity",
    }))
    assert res["status"] == "ok"
    assert res["trap"]["name"] == "sqlite_lock_tripwire"
    assert res["trap"]["active"] is True

    # 2. List traps
    listed = json.loads(memory_mcp_server.tool_mem_trap_list({}))
    assert listed["total_traps"] == 1
    assert listed["traps"][0]["name"] == "sqlite_lock_tripwire"

    # 3. Eval against non-matching text
    eval_no_match = json.loads(memory_mcp_server.tool_mem_trap_eval({
        "context": "SELECT * FROM users;"
    }))
    assert eval_no_match["triggered_count"] == 0

    # 4. Eval against matching command (trips the trap)
    eval_match = json.loads(memory_mcp_server.tool_mem_trap_eval({
        "context": "Executing PRAGMA journal_mode = WAL;"
    }))
    assert eval_match["triggered_count"] == 1
    assert eval_match["triggered"][0]["trap_name"] == "sqlite_lock_tripwire"
    assert "WAL mode" in eval_match["triggered"][0]["directive"]

    # 5. Since recurring=False, subsequent eval should NOT trigger again
    eval_again = json.loads(memory_mcp_server.tool_mem_trap_eval({
        "context": "Executing PRAGMA journal_mode = WAL;"
    }))
    assert eval_again["triggered_count"] == 0

    # 6. Check list shows hit_count = 1 and active = False
    traps_after = json.loads(memory_mcp_server.tool_mem_trap_list({}))
    assert traps_after["traps"][0]["hit_count"] == 1
    assert traps_after["traps"][0]["active"] is False


def test_prospective_recurring_trap(clean_memory_root):
    # Create recurring trap
    memory_mcp_server.tool_mem_trap_create({
        "name": "master_branch_guard",
        "pattern": r"git\s+push\s+origin\s+master",
        "payload": "CRITICAL: Pushing directly to master requires review.",
        "trigger_type": "command",
        "recurring": True,
    })

    # Trigger twice
    res1 = json.loads(memory_mcp_server.tool_mem_trap_eval({"context": "git push origin master"}))
    assert res1["triggered_count"] == 1

    res2 = json.loads(memory_mcp_server.tool_mem_trap_eval({"context": "git push origin master"}))
    assert res2["triggered_count"] == 1

    traps = json.loads(memory_mcp_server.tool_mem_trap_list({}))
    assert traps["traps"][0]["hit_count"] == 2
    assert traps["traps"][0]["active"] is True

    # Dismiss trap
    d_res = json.loads(memory_mcp_server.tool_mem_trap_dismiss({"name": "master_branch_guard"}))
    assert d_res["status"] == "ok"

    res3 = json.loads(memory_mcp_server.tool_mem_trap_eval({"context": "git push origin master"}))
    assert res3["triggered_count"] == 0


def test_speculative_prefetch(clean_memory_root, tmp_path):
    # Setup prior error retrospective
    errs_file = clean_memory_root / "operational" / "errors.json"
    errs_file.write_text(json.dumps([{
        "timestamp": "2026-10-04T05:00:00Z",
        "trace": "Failed to import sqlite3 with foreign_keys enabled",
        "root_cause": "Missing sqlite3 PRAGMA foreign_keys = ON",
        "mitigation": "Always configure PRAGMA foreign_keys on connection opening",
        "agent": "developer"
    }]))

    # Setup semantic fact
    facts_file = clean_memory_root / "semantic" / "facts.json"
    facts_file.write_text(json.dumps({
        "sqlite.concurrency.policy": "Always use WAL mode with 5.0s timeout."
    }))

    # Setup trap
    memory_mcp_server.tool_mem_trap_create({
        "name": "sqlite_edit_trap",
        "pattern": "sqlite",
        "payload": "PRE-FLIGHT: Remember to execute tests with test_sqlite_vec.py",
        "recurring": True
    })

    # Create dummy python file for symbol extraction
    dummy_code = tmp_path / "db_helper.py"
    dummy_code.write_text("class DatabaseManager:\n    def connect_sqlite(self):\n        pass\n")

    prefetch = json.loads(memory_mcp_server.tool_mem_speculative_prefetch({
        "active_file": str(dummy_code),
        "intent": "Refactor sqlite connection pool",
        "project": "global-memory"
    }))

    assert prefetch["status"] == "ok"
    bundle = prefetch["speculative_bundle"]
    assert len(bundle["hazards"]) >= 1
    assert "test_sqlite_vec.py" in bundle["hazards"][0]
    assert len(bundle["prior_regrets"]) >= 1
    assert "foreign_keys" in bundle["prior_regrets"][0]["mitigation"]
    assert "DatabaseManager" in bundle["symbols"]
    assert len(bundle["invariants"]) >= 1
    assert "sqlite.concurrency.policy" in bundle["invariants"][0]["key"]


def test_programmatic_guard():
    # 1. Schema keys guard
    pass_keys = json.loads(memory_mcp_server.tool_mem_programmatic_guard({
        "guard_name": "schema_keys",
        "context": {"key": "alpha.1", "value": "val", "agent": "tester"},
        "required_keys": ["key", "value"]
    }))
    assert pass_keys["passed"] is True

    fail_keys = json.loads(memory_mcp_server.tool_mem_programmatic_guard({
        "guard_name": "schema_keys",
        "context": {"key": "alpha.1"},
        "required_keys": ["key", "value"]
    }))
    assert fail_keys["passed"] is False
    assert "Missing required keys" in fail_keys["error"]

    # 2. Budget limit guard
    pass_budget = json.loads(memory_mcp_server.tool_mem_programmatic_guard({
        "guard_name": "budget_limit",
        "target_text": "short text",
        "max_chars": 100
    }))
    assert pass_budget["passed"] is True

    fail_budget = json.loads(memory_mcp_server.tool_mem_programmatic_guard({
        "guard_name": "budget_limit",
        "target_text": "x" * 200,
        "max_chars": 100
    }))
    assert fail_budget["passed"] is False

    # 3. Custom assertion guard
    custom_guard = json.loads(memory_mcp_server.tool_mem_programmatic_guard({
        "guard_name": "custom",
        "condition": True,
        "reason": "Branch must be git worktree isolated"
    }))
    assert custom_guard["passed"] is True
