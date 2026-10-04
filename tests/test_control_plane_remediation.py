"""Regression test suite for control-plane audit remediation (P0, P1, P2).

Tests:
- P0: brain eval-lab CLI executes cleanly without ModuleNotFoundError when invoked from non-repo directories.
- P1: Generic keys ('error', 'status', etc.) and parser-error payloads are rejected by admission guards.
- P2: Current-context retrieval ranks recent project updates above older updates and respects as_of filtering.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from autonomous_curation import assess_candidate
from context_retrieval_planner import retrieve
from schemas import (
    is_generic_key,
    is_parser_error_statement,
    validate_context_candidate,
    validate_fact,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ==============================================================================
# P0: eval-lab CLI Import Resolution from Foreign CWD
# ==============================================================================

def test_eval_lab_cli_from_foreign_cwd(tmp_path: Path):
    """Verify brain eval-lab runs from outside the repo root without ModuleNotFoundError."""
    brain_bin = REPO_ROOT / "tools" / "brain"
    assert brain_bin.exists(), f"Brain executable missing at {brain_bin}"

    # Execute from an isolated temporary directory with minimal env
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    cmd = [str(brain_bin), "eval-lab", "run", "--suite", "all", "--no-export"]
    proc = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, f"eval-lab failed with stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
    assert "ModuleNotFoundError" not in proc.stderr
    assert "ModuleNotFoundError" not in proc.stdout
    assert "Pass Rate: 100.0%" in proc.stdout


# ==============================================================================
# P1: Generic-Key & Parser-Error Admission Guards
# ==============================================================================

def test_admission_guard_generic_key_detection():
    """Verify is_generic_key correctly flags unnamespaced generic tokens."""
    for key in ("error", "errors", "exception", "status", "result", "output", "temp", "data", "test", "foo", "bar"):
        assert is_generic_key(key) is True
        assert is_generic_key(f"  {key.upper()}  ") is True

    # Namespaced keys must NOT be treated as generic keys
    for valid_key in ("system.error_count", "service.status", "alphaos.trade_result", "memory.test_metric"):
        assert is_generic_key(valid_key) is False


def test_admission_guard_parser_error_detection():
    """Verify is_parser_error_statement detects parser errors and tracebacks."""
    parser_samples = [
        "Invalid JSON: Expecting value: line 1 column 1 (char 0)",
        "json.decoder.JSONDecodeError: Expecting ',' delimiter: line 2 column 5 (char 12)",
        "Traceback (most recent call last):\n  File 'test.py', line 1, in <module>\nValueError: invalid literal",
        "SyntaxError: invalid syntax (<string>, line 1)",
    ]
    for sample in parser_samples:
        assert is_parser_error_statement(sample) is True

    # Meaningful durable statements must NOT be flagged as parser errors
    legitimate_samples = [
        "Use SQLite WAL mode and busy_timeout=5000 for database concurrency.",
        "Plugin version 2.0.1 deployed to production cluster.",
        "Error handling policy requires recording rationale and implications for all failures.",
    ]
    for sample in legitimate_samples:
        assert is_parser_error_statement(sample) is False


def test_validate_fact_rejects_generic_keys_and_parser_errors():
    """Verify validate_fact rejects generic keys and parser-error statements."""
    ok_key, _, err_key = validate_fact("error", "An unhandled exception occurred")
    assert ok_key is False
    assert "generic" in err_key.lower()

    ok_val, _, err_val = validate_fact(
        "system.status",
        "Invalid JSON: Expecting value: line 1 column 1 (char 0)"
    )
    assert ok_val is False
    assert "parser-error" in err_val.lower()

    # Valid fact must pass
    ok_valid, norm, err_valid = validate_fact(
        "system.database.concurrency",
        "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;"
    )
    assert ok_valid is True
    assert err_valid is None


def test_validate_context_candidate_rejects_generic_keys_and_parser_errors():
    """Verify validate_context_candidate rejects invalid candidate structures."""
    candidate_generic = {
        "schema_version": "gms-context-record-v1",
        "record_type": "fact",
        "key": "error",
        "statement": "Valid statement with bad key",
        "source": "tests/fixture.md",
    }
    ok_gen, _, err_gen = validate_context_candidate(candidate_generic)
    assert ok_gen is False
    assert "generic" in err_gen.lower()

    candidate_parser = {
        "schema_version": "gms-context-record-v1",
        "record_type": "fact",
        "key": "system.parser_failure",
        "statement": "Invalid JSON: Expecting value: line 1 column 1 (char 0)",
        "source": "tests/fixture.md",
    }
    ok_par, _, err_par = validate_context_candidate(candidate_parser)
    assert ok_par is False
    assert "parser-error" in err_par.lower()


def test_assess_candidate_rejects_generic_error_and_parser_traceback(tmp_path: Path):
    """Verify autonomous_curation.assess_candidate rejects generic error candidates."""
    cand = {
        "candidate_id": 999,
        "canonical_key": "error",
        "record_type": "fact",
        "payload_json": json.dumps({
            "key": "error",
            "statement": "Invalid JSON: Expecting value: line 1 column 1 (char 0)",
            "source": "session_audit",
            "rationale": "Automated capture",
            "evidence": "Observed traceback in stderr",
        }),
        "status": "proposed",
    }
    assessment = assess_candidate(cand, mem_root=tmp_path)
    assert assessment["decision"] == "reject"
    assert assessment["eligible"] is False
    assert "admission guard" in assessment["basis"]


# ==============================================================================
# P2: Effective-Time-Aware Current-Context Ranking
# ==============================================================================

def test_current_context_ranks_newer_update_above_older(tmp_path: Path):
    """Verify current-context retrieval ranks newer project updates above older updates."""
    proj_dir = tmp_path / "projects" / "alpha"
    proj_dir.mkdir(parents=True)
    (proj_dir / "activeContext.md").write_text(
        "# Active Context — Alpha\n\n"
        "## Active Constraints & Boundaries\n"
        "- Constraint: Never load generative LLM during interactive desktop browsing.\n\n"
        "### Update (2026-09-11 10:00)\n"
        "Alpha project status: initial implementation began with basic adapter.\n\n"
        "### Update (2026-09-28 17:30)\n"
        "Alpha project status: feature complete, migrated to standalone adapter package and verified 59 tests.\n"
    )

    # Context query for alpha status
    res = retrieve(tmp_path, "Alpha project status update", project="alpha")
    items = res["items"]
    assert len(items) >= 2

    # Top item must be the recent (2026-09-28) update
    top_item = items[0]
    assert "2026-09-28" in str(top_item.get("effective_at", ""))
    assert "feature complete" in top_item["statement"]

    # Older item (2026-09-11) must be ranked below the newer update
    older_items = [it for it in items if "2026-09-11" in str(it.get("effective_at", ""))]
    assert len(older_items) >= 1
    assert items.index(top_item) < items.index(older_items[0])


def test_current_context_temporal_as_of_filtering(tmp_path: Path):
    """Verify temporal as_of filtering omits updates occurring after as_of timestamp."""
    proj_dir = tmp_path / "projects" / "alpha"
    proj_dir.mkdir(parents=True)
    (proj_dir / "activeContext.md").write_text(
        "# Active Context — Alpha\n\n"
        "### Update (2026-09-11 10:00)\n"
        "Alpha project status: initial implementation began with basic adapter.\n\n"
        "### Update (2026-09-28 17:30)\n"
        "Alpha project status: feature complete, migrated to standalone adapter package and verified 59 tests.\n"
    )

    # Query with as_of set to 2026-09-15 (between the two updates)
    res = retrieve(tmp_path, "Alpha project status update", project="alpha", as_of="2026-09-15")
    items = res["items"]

    # The 2026-09-28 update must NOT be present in active items
    assert not any("2026-09-28" in str(it.get("effective_at", "")) for it in items)

    # The 2026-09-11 update must be retrieved
    assert any("2026-09-11" in str(it.get("effective_at", "")) for it in items)

    # Verify omission manifest records the future item if filtered at retrieval time
    all_seen = [it["key"] for it in items]
    assert not any("2026-09-28" in k for k in all_seen)
