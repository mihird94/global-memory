import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from morning_briefing import generate_morning_briefing, list_morning_briefings
from project_briefing import build_resume_bundle
from resumption_eval import (
    run_resumption_evaluation,
    RESUMPTION_SCENARIOS,
    _run_live_agent_continuation,
    _score_agent_answer,
)


def _setup_test_root(tmp_path: Path) -> Path:
    (tmp_path / "semantic").mkdir(parents=True, exist_ok=True)
    (tmp_path / "semantic" / "facts.json").write_text(json.dumps({
        "alphaos.swing.plugin_version": "2.0.0",
        "alphaos_swing_plugin_version": "1.9.0",
        "car_stickers_status": "active",
        "global_memory_sqlite_concurrency": "Use WAL mode and busy_timeout=5000",
    }))

    proj_dir = tmp_path / "projects" / "global-memory"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "projectBrief.md").write_text("# Global Memory\n\nBuild unified multi-agent memory system.")
    (proj_dir / "activeContext.md").write_text(
        "## Decisions\n\n"
        "Decision: Retired global agent trust score in Mbrain because it collapses orthogonal dimensions.\n\n"
        "### Update (2026-09-08 18:00)\n"
        "Verified Dream Cycle schedule at 03:10 AM local time."
    )

    db = tmp_path / "gms_trust.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE gms_tasks (task_id TEXT PRIMARY KEY, project TEXT, title TEXT, objective TEXT, status TEXT, owner_agent TEXT, lease_expires_at TEXT, revision INTEGER, parent_task_id TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT)")
    conn.execute("INSERT INTO gms_tasks VALUES ('t1', 'global-memory', 'Pass 8 Continuation', 'Deliver Pass 8', 'in_progress', 'antigravity', '2026-09-10', 1, NULL, 'mihir', '2026-09-09', '2026-09-09', NULL)")
    conn.commit()
    conn.close()
    return tmp_path


def test_morning_briefing_generation(tmp_path):
    root = _setup_test_root(tmp_path)
    mb = generate_morning_briefing(root, "global-memory")

    assert mb["schema_version"] == "gms-morning-briefing-v1"
    assert mb["project_id"] == "global-memory"
    assert "suggested_first_action" in mb
    assert "blocking_issues" in mb
    assert "summary" in mb


def test_resumption_evaluation_runner_reports_classes(tmp_path):
    root = _setup_test_root(tmp_path)
    report = run_resumption_evaluation(root)

    assert report["schema_version"] == "gms-resumption-eval-report-v1"
    assert report["total_scenarios"] == len(RESUMPTION_SCENARIOS)
    assert 0 <= report["scenarios_passed"] <= report["total_scenarios"]
    assert report["evaluable_scenarios"] + report["not_evaluable_scenarios"] == report["total_scenarios"]
    assert report["quality_gate_passed"] is (
        report["scenarios_passed"] == report["evaluable_scenarios"]
        and report["not_evaluable_scenarios"] == 0
        and report["agent_continuation_trial"]["passed"] is True
    )
    assert report["agent_continuation_trial"]["status"] == "not_run"
    assert report["agent_continuation_trial"]["bundle_contract_valid"] is True
    assert "class_metrics" in report
    assert "average_lane_latencies_ms" in report
    assert report["agent_continuation_trial"]["passed"] is False
    assert report["agent_continuation_trial"]["dispatch_prohibited"] is True


def test_agent_answer_scoring_uses_generated_content(tmp_path):
    root = _setup_test_root(tmp_path)
    bundle = build_resume_bundle(root, "global-memory", target_format="antigravity")
    goal = bundle["briefing"]["goal"]
    answer = {
        "goal": goal["statement"],
        "current_state": "The active task is Pass 8 Continuation and it is ready to resume.",
        "unfinished_work": ["Complete the active task and verify its acceptance criteria."],
        "next_action": bundle["briefing"]["next_action"]["statement"],
        "evidence_refs": [goal["source_refs"][0]],
        "uncertainties": [],
    }
    score = _score_agent_answer(answer, bundle)
    assert score["passed"] is True
    assert score["checks"]["goal_grounded"] is True

    answer["evidence_refs"] = ["invented/source.md"]
    bad = _score_agent_answer(answer, bundle)
    assert bad["passed"] is False
    assert bad["checks"]["evidence_refs_grounded"] is False


@patch("resumption_eval._installed_ollama_models", return_value=(True, ["qwen3:8b"], None))
@patch("resumption_eval.request.urlopen")
def test_live_agent_trial_scores_output_and_unloads(mock_urlopen, _mock_models, tmp_path):
    root = _setup_test_root(tmp_path)
    bundle = build_resume_bundle(root, "global-memory", target_format="antigravity")
    goal = bundle["briefing"]["goal"]
    answer = {
        "goal": goal["statement"],
        "current_state": "The active task is Pass 8 Continuation and it is ready to resume.",
        "unfinished_work": ["Complete and verify the active task."],
        "next_action": bundle["briefing"]["next_action"]["statement"],
        "evidence_refs": [goal["source_refs"][0]],
        "uncertainties": [],
    }

    class Response:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self): return self.body

    mock_urlopen.side_effect = [
        Response(json.dumps({"response": json.dumps(answer)}).encode()),
        Response(b"{}"),
    ]
    result = _run_live_agent_continuation(bundle, model="qwen3:8b", base_url="http://ollama")
    assert result["status"] == "passed"
    assert result["scoring"]["passed"] is True
    assert result["model_unload_success"] is True
    unload_request = mock_urlopen.call_args_list[-1].args[0]
    assert b'"keep_alive": 0' in unload_request.data


@patch("resumption_eval._installed_ollama_models", return_value=(True, ["other:1b"], None))
def test_live_agent_trial_refuses_uninstalled_model_without_download(_mock_models, tmp_path):
    root = _setup_test_root(tmp_path)
    bundle = build_resume_bundle(root, "global-memory", target_format="antigravity")
    result = _run_live_agent_continuation(bundle, model="qwen3:8b", base_url="http://ollama")
    assert result["status"] == "not_run"
    assert "automatic downloads are prohibited" in result["reason"]
