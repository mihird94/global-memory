#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
import importlib
from datetime import datetime
from pathlib import Path
from typing import Callable


def _server():
    return importlib.import_module("memory_mcp_server")


def _prepare_memory_root(root: Path) -> None:
    (root / "semantic").mkdir(parents=True, exist_ok=True)
    (root / "episodic" / "history").mkdir(parents=True, exist_ok=True)
    (root / "lessons").mkdir(parents=True, exist_ok=True)


@contextmanager
def _using_memory_root(root: Path):
    server = _server()
    dream_cycle = importlib.import_module("dream_cycle")
    memoryctl = importlib.import_module("memoryctl")
    old_env = os.environ.get("MEMORY_ROOT")
    old_mem_root = server.MEM_ROOT
    old_db_path = server.DB_PATH
    old_dream_mem_root = dream_cycle.MEM_ROOT
    old_ctl_mem_root = memoryctl.MEM_ROOT
    try:
        os.environ["MEMORY_ROOT"] = str(root)
        server.MEM_ROOT = root
        server.DB_PATH = root / "gms_trust.sqlite"
        dream_cycle.MEM_ROOT = root
        memoryctl.MEM_ROOT = root
        _prepare_memory_root(root)
        server.init_db()
        yield
    finally:
        if old_env is None:
            os.environ.pop("MEMORY_ROOT", None)
        else:
            os.environ["MEMORY_ROOT"] = old_env
        server.MEM_ROOT = old_mem_root
        server.DB_PATH = old_db_path
        dream_cycle.MEM_ROOT = old_dream_mem_root
        memoryctl.MEM_ROOT = old_ctl_mem_root


def _set_agent_reputation(agent_id: str, alpha: float, beta: float) -> None:
    server = _server()
    conn = sqlite3.connect(str(server.DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, ?)",
        (agent_id, alpha, beta),
    )
    conn.commit()
    conn.close()


def _load_semantic_facts() -> dict:
    facts_path = _server().MEM_ROOT / "semantic" / "facts.json"
    if not facts_path.exists():
        return {}
    return json.loads(facts_path.read_text())


def _make_result(name: str, category: str, passed: bool, details: str) -> dict:
    return {
        "name": name,
        "category": category,
        "passed": passed,
        "details": details,
    }


def _scenario_trusted_overwrite() -> dict:
    server = _server()
    _set_agent_reputation("agent_low", 1.0, 0.0)
    _set_agent_reputation("agent_high", 12.0, 0.0)
    server.tool_mem_save_fact(
        {"key": "deployment_target", "value": "staging", "agent": "agent_low"}
    )
    result = server.tool_mem_save_fact(
        {"key": "deployment_target", "value": "prod", "agent": "agent_high"}
    )
    facts = _load_semantic_facts()
    passed = "overwrote existing key" in result and facts.get("deployment_target") == "prod"
    return _make_result(
        "trusted_overwrite",
        "knowledge_update",
        passed,
        result,
    )


def _scenario_quarantine_rejection() -> dict:
    server = _server()
    _set_agent_reputation("agent_trusted", 12.0, 0.0)
    _set_agent_reputation("agent_untrusted", 1.0, 6.0)
    server.tool_mem_save_fact(
        {"key": "service_owner", "value": "platform", "agent": "agent_trusted"}
    )
    result = server.tool_mem_save_fact(
        {"key": "service_owner", "value": "attacker", "agent": "agent_untrusted"}
    )
    facts = _load_semantic_facts()
    passed = "CONFLICT/QUARANTINE" in result and facts.get("service_owner") == "platform"
    return _make_result(
        "quarantine_rejection",
        "quarantine",
        passed,
        result,
    )


def _scenario_episodic_summary_recall() -> dict:
    server = _server()
    journal = server.MEM_ROOT / "episodic" / "journal.md"
    journal.write_text(
        "# Session\n"
        "Implemented routing\n"
        "## Notes\n"
        "Validated summary path\n"
        "Captured deep reconstruction\n"
    )
    result = json.loads(
        server.tool_mem_get_episode(
            {"source": str(journal), "mode": "summary"}
        )
    )
    passed = (
        result["metadata"]["type"] == "journal"
        and "Validated summary path" in result["excerpt"]
        and result["headers"] == ["# Session", "## Notes"]
    )
    return _make_result(
        "episodic_summary_recall",
        "episodic_recall",
        passed,
        json.dumps(result),
    )


def _scenario_missing_episode_abstention() -> dict:
    result = _server().tool_mem_get_episode(
        {"date": "2026-06-30", "mode": "deep"}
    )
    passed = result.startswith("ERROR:")
    return _make_result(
        "missing_episode_abstention",
        "abstention",
        passed,
        result,
    )


def _scenario_weighted_quarantine_resolution() -> dict:
    server = _server()
    _set_agent_reputation("agent_trusted", 12.0, 0.0)
    _set_agent_reputation("agent_untrusted", 1.0, 6.0)
    _set_agent_reputation("reviewer_support", 12.0, 0.0)
    _set_agent_reputation("reviewer_reject", 1.0, 8.0)
    server.tool_mem_save_fact(
        {"key": "deploy_policy", "value": "manual", "agent": "agent_trusted"}
    )
    quarantine_result = server.tool_mem_save_fact(
        {"key": "deploy_policy", "value": "auto", "agent": "agent_untrusted"}
    )
    server.tool_mem_record_review(
        {
            "key": "deploy_policy",
            "agent_id": "agent_untrusted",
            "reviewer_id": "reviewer_support",
            "rating": "endorse",
            "rationale": "Matches the new rollout plan.",
        }
    )
    server.tool_mem_record_review(
        {
            "key": "deploy_policy",
            "agent_id": "agent_untrusted",
            "reviewer_id": "reviewer_reject",
            "rating": "reject",
            "rationale": "Conflicts with prior controls.",
        }
    )
    summary = json.loads(
        server.tool_mem_get_recommendation_summary(
            {"key": "deploy_policy", "agent_id": "agent_untrusted"}
        )
    )
    resolution = server.tool_mem_resolve_quarantine(
        {"key": "deploy_policy", "agent_id": "agent_untrusted", "action": "promote", "agent": "eval"}
    )
    facts = _load_semantic_facts()
    passed = (
        "CONFLICT/QUARANTINE" in quarantine_result
        and summary["recommendation"] == "promote"
        and "SUCCESS" in resolution
        and facts.get("deploy_policy") == "auto"
    )
    return _make_result(
        "weighted_quarantine_resolution",
        "poisoning_resistance",
        passed,
        json.dumps({"summary": summary, "resolution": resolution}),
    )


def _scenario_retention_archival() -> dict:
    server = _server()
    dream_cycle = importlib.import_module("dream_cycle")
    facts_path = server.MEM_ROOT / "semantic" / "facts.json"
    facts_path.write_text(json.dumps({"stale_fact": "old_value"}, indent=2))
    conn = sqlite3.connect(str(server.DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO gms_claims (
            memory_kind, memory_key, value, agent_id, branch, status,
            supersedes_claim_id, confidence, contradiction_type, created_at
        ) VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, NULL, ?)
        """,
        ("semantic", "stale_fact", "old_value", "agent_old", "main", 0.2, "2026-04-01 00:00:00"),
    )
    cursor.execute(
        """
        INSERT INTO gms_fact_provenance (fact_key, agent_id, branch, quarantined, timestamp)
        VALUES (?, ?, ?, 0, ?)
        """,
        ("stale_fact", "agent_old", "main", "2026-04-01 00:00:00"),
    )
    conn.commit()
    conn.close()
    report = dream_cycle.run_retention_pruning(
        now=datetime(2026, 6, 4, 12, 0, 0),
        low_confidence_threshold=0.3,
        stale_active_days=30,
        stale_quarantine_days=14,
    )
    facts = _load_semantic_facts()
    claims = json.loads(server.tool_mem_get_claims({"key": "stale_fact"}))
    passed = (
        report["applied"]["archived_active_claims"] == 1
        and "stale_fact" not in facts
        and claims[0]["status"] == "archived"
    )
    return _make_result(
        "retention_archival",
        "retention",
        passed,
        json.dumps(report),
    )


def _scenario_collusive_low_trust_reviewers() -> dict:
    server = _server()
    _set_agent_reputation("agent_trusted", 12.0, 0.0)
    _set_agent_reputation("agent_untrusted", 1.0, 6.0)
    _set_agent_reputation("reviewer_guardian", 12.0, 0.0)
    _set_agent_reputation("reviewer_colluder_1", 1.0, 10.0)
    _set_agent_reputation("reviewer_colluder_2", 1.0, 10.0)
    server.tool_mem_save_fact(
        {"key": "secrets_backend", "value": "vault", "agent": "agent_trusted"}
    )
    quarantine_result = server.tool_mem_save_fact(
        {"key": "secrets_backend", "value": "plaintext", "agent": "agent_untrusted"}
    )
    server.tool_mem_record_review(
        {
            "key": "secrets_backend",
            "agent_id": "agent_untrusted",
            "reviewer_id": "reviewer_guardian",
            "rating": "reject",
            "rationale": "Violates production controls.",
        }
    )
    for reviewer in ("reviewer_colluder_1", "reviewer_colluder_2"):
        server.tool_mem_record_review(
            {
                "key": "secrets_backend",
                "agent_id": "agent_untrusted",
                "reviewer_id": reviewer,
                "rating": "endorse",
                "rationale": "Looks fine.",
            }
        )
    summary = json.loads(
        server.tool_mem_get_recommendation_summary(
            {"key": "secrets_backend", "agent_id": "agent_untrusted"}
        )
    )
    passed = (
        "CONFLICT/QUARANTINE" in quarantine_result
        and summary["recommendation"] == "discard"
        and summary["reject_weight"] > summary["endorse_weight"]
    )
    return _make_result(
        "collusive_low_trust_reviewers",
        "poisoning_resistance",
        passed,
        json.dumps(summary),
    )


def run_evaluation(memory_root: Path | None = None) -> dict:
    scenario_fns: list[Callable[[], dict]] = [
        _scenario_trusted_overwrite,
        _scenario_quarantine_rejection,
        _scenario_weighted_quarantine_resolution,
        _scenario_collusive_low_trust_reviewers,
        _scenario_episodic_summary_recall,
        _scenario_missing_episode_abstention,
        _scenario_retention_archival,
    ]

    if memory_root is None:
        with tempfile.TemporaryDirectory() as temp_dir:
            return run_evaluation(Path(temp_dir))

    results = []
    with _using_memory_root(memory_root):
        for scenario_fn in scenario_fns:
            results.append(scenario_fn())

    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    return {
        "suite": "gms_foundation_plus_guardrails",
        "memory_root": str(memory_root),
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total else 0.0,
        },
    }


def main() -> int:
    report = run_evaluation()
    print(json.dumps(report, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
