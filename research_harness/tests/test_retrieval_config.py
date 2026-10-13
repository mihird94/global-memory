"""Comprehensive unit tests for RetrievalConfig, tuning methodology, safety gates, and partitioning."""
from __future__ import annotations

import hashlib
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch
import pytest

from context_retrieval_planner import (
    DEFAULT_CANDIDATE_LIMITS,
    DEFAULT_LANE_WEIGHTS,
    LANES,
    RetrievalConfig,
    _run_lane_graph,
    _run_lane_vector,
    retrieve,
)
from research_harness.eval.harness import MemoryEvalHarness, fixture_query_embedding
from research_harness.eval.partitions import (
    PARTITION_CANONICAL_IDS,
    get_partition_cases,
    get_partition_for_case_id,
    verify_partition_isolation,
)
from research_harness.eval.tuning import (
    check_ollama_status,
    collect_provenance,
    convert_maxrss_to_mb,
    derive_safety_gates,
    evaluate_configuration,
    measure_cold_and_warm_flashrank_latency,
    run_experiment_1_rrf_k,
    run_experiment_7_holdout_validation,
    select_recommended_profile,
)


# ==============================================================================
# 1. Config Defaults, Validation, and Profiles
# ==============================================================================

def test_retrieval_config_defaults_and_roundtrip():
    cfg = RetrievalConfig()
    assert cfg.rrf_k == 60
    assert cfg.lane_weights == DEFAULT_LANE_WEIGHTS
    assert cfg.lane_candidate_limits == DEFAULT_CANDIDATE_LIMITS
    assert cfg.graph_hops == 1
    assert cfg.vector_similarity_cutoff == 0.0
    assert cfg.rerank_policy == "never"
    assert cfg.profile == "custom"

    data = cfg.to_dict()
    assert data["rrf_k"] == 60
    assert data["rerank_policy"] == "never"

    restored = RetrievalConfig.from_dict(data)
    assert restored.rrf_k == cfg.rrf_k
    assert restored.rerank_policy == cfg.rerank_policy
    assert restored.lane_weights == cfg.lane_weights


def test_invalid_configurations_fail_early():
    # 1. rrf_k <= 0
    with pytest.raises(ValueError, match="rrf_k must be positive"):
        RetrievalConfig(rrf_k=0)

    # 2. graph_hops out of bounds
    with pytest.raises(ValueError, match="graph_hops must be in 1..3"):
        RetrievalConfig(graph_hops=4)

    # 3. rerank_k out of bounds
    with pytest.raises(ValueError, match="rerank_k must be in 1..100"):
        RetrievalConfig(rerank_k=0)

    # 4. rerank_policy invalid
    with pytest.raises(ValueError, match="rerank_policy must be one of"):
        RetrievalConfig(rerank_policy="magic_rerank")

    # 5. unknown lane in weights
    with pytest.raises(ValueError, match="Unknown lane 'unknown_lane'"):
        RetrievalConfig(lane_weights={"unknown_lane": 1.0})

    # 6. margin threshold out of bounds
    with pytest.raises(ValueError, match="rerank_margin_threshold must be in"):
        RetrievalConfig(rerank_margin_threshold=1.5)

    # 7. unknown profile name
    with pytest.raises(ValueError, match="Unknown retrieval profile"):
        RetrievalConfig.from_profile("unknown_profile")


def test_retrieval_config_profiles():
    fast = RetrievalConfig.from_profile("fast")
    assert fast.profile == "fast"
    assert fast.rerank_policy == "never"
    assert fast.graph_hops == 1

    standard = RetrievalConfig.from_profile("standard")
    assert standard.profile == "standard"
    assert standard.rerank_policy == "conditional"

    high = RetrievalConfig.from_profile("high_assurance")
    assert high.profile == "high_assurance"
    assert high.rerank_policy == "always"
    assert high.graph_hops == 2
    assert high.lane_weights["conflicts"] == 1.5


# ==============================================================================
# 2. Partition Isolation & Invariance
# ==============================================================================

def test_partition_isolation_and_variant_invariance():
    res = verify_partition_isolation()
    assert res["isolated"] is True
    assert res["canonical_counts"]["train"] == 6
    assert res["canonical_counts"]["dev"] == 3
    assert res["canonical_counts"]["holdout"] == 3

    assert res["total_case_counts"]["train"] == 30
    assert res["total_case_counts"]["dev"] == 15
    assert res["total_case_counts"]["holdout"] == 15

    for c in get_partition_cases("holdout", include_variants=True):
        assert get_partition_for_case_id(c.id) == "holdout"
        if c.variant_of:
            assert get_partition_for_case_id(c.variant_of) == "holdout"


# ==============================================================================
# 3. Reranker Schema, Conditional Triggers, and Skip Behavior
# ==============================================================================

def test_reranker_10_field_schema_and_policy_never():
    with MemoryEvalHarness() as harness:
        cfg = RetrievalConfig.from_profile("fast")
        ret = retrieve(harness.root, "What is the SQLite WAL setting?", config=cfg)
        reranker = ret["reranker"]
        expected_fields = {
            "enabled", "attempted", "available", "backend", "model",
            "pool_size", "reranked", "policy", "reason", "latency_ms"
        }
        assert set(reranker.keys()) == expected_fields
        assert reranker["enabled"] is False
        assert reranker["attempted"] is False
        assert reranker["reason"] == "policy_never"
        assert reranker["reranked"] == 0
        assert reranker["latency_ms"] == 0.0

        # Diagnostics exposed at top level
        assert "rerank_diagnostics" in ret
        diag = ret["rerank_diagnostics"]
        assert "top1_rrf_score" in diag
        assert "normalized_margin" in diag
        assert "selected_trigger" in diag

        assert "config" in ret["manifest"]
        assert ret["manifest"]["profile"] == "fast"


def test_conditional_reranking_can_execute_and_skip():
    with MemoryEvalHarness() as harness:
        cfg = RetrievalConfig(rerank_policy="conditional")

        # 1. High assurance trigger -> executes
        ret_high = retrieve(harness.root, "What is the MiniPC Tailscale IP?", assurance="high", config=cfg)
        assert ret_high["reranker"]["attempted"] is True
        assert ret_high["reranker"]["reason"] == "high_assurance"

        # 2. Unambiguous query under standard assurance with 0.0 margin threshold -> skips
        cfg_skip = RetrievalConfig(rerank_policy="conditional", rerank_margin_threshold=0.0)
        ret_skip = retrieve(harness.root, "minipc", config=cfg_skip)
        assert ret_skip["reranker"]["attempted"] is False
        assert ret_skip["reranker"]["reason"] == "not_required"


def test_conditional_policy_does_not_rerank_100_percent_of_dev_set():
    with MemoryEvalHarness() as harness:
        cfg = RetrievalConfig.from_profile("standard")
        dev_cases = get_partition_cases("dev", include_variants=True)
        eval_res = evaluate_configuration(harness.root, cfg, dev_cases, partition_name="dev")
        # Under calibrated thresholds (margin=0.05, coverage=0.60), dev queries do not 100% trigger reranking
        assert eval_res["summary"]["rerank_attempted_rate"] < 1.0


# ==============================================================================
# 4. Profile Selection & Pareto Dominance
# ==============================================================================

def test_recommendation_not_hard_coded():
    # Mock profiles: Case A, fast dominates
    mock_evals_a = {
        "fast": {"summary": {"mean_ndcg@10": 0.85, "mean_mrr": 1.0, "mean_recall@5": 1.0, "abstention_accuracy": 1.0, "rerank_attempted_rate": 0.0, "latency": {"p50": 3.0, "p95": 5.0, "mean": 3.2}}},
        "standard": {"summary": {"mean_ndcg@10": 0.70, "mean_mrr": 0.8, "mean_recall@5": 1.0, "abstention_accuracy": 1.0, "rerank_attempted_rate": 0.5, "latency": {"p50": 15.0, "p95": 20.0, "mean": 16.0}}},
    }
    safety_clean = {
        "fast": {"safety_pass": True, "total_violations": 0},
        "standard": {"safety_pass": True, "total_violations": 0},
    }
    sel_a = select_recommended_profile(mock_evals_a, safety_clean)
    assert sel_a["recommended_default_profile"] == "fast"

    # Mock profiles: Case B, standard has higher quality within allowed trade-off
    mock_evals_b = {
        "fast": {"summary": {"mean_ndcg@10": 0.60, "mean_mrr": 0.6, "mean_recall@5": 1.0, "abstention_accuracy": 1.0, "rerank_attempted_rate": 0.0, "latency": {"p50": 3.0, "p95": 5.0, "mean": 3.2}}},
        "standard": {"summary": {"mean_ndcg@10": 0.95, "mean_mrr": 1.0, "mean_recall@5": 1.0, "abstention_accuracy": 1.0, "rerank_attempted_rate": 0.2, "latency": {"p50": 10.0, "p95": 15.0, "mean": 11.0}}},
    }
    sel_b = select_recommended_profile(mock_evals_b, safety_clean)
    assert sel_b["recommended_default_profile"] == "standard"


def test_fast_wins_when_dominating_standard():
    mock_evals = {
        "fast": {"summary": {"mean_ndcg@10": 0.6860, "mean_mrr": 1.0000, "mean_recall@5": 1.0, "abstention_accuracy": 1.0, "rerank_attempted_rate": 0.0, "latency": {"p50": 2.5, "p95": 4.0, "mean": 2.8}}},
        "standard": {"summary": {"mean_ndcg@10": 0.6671, "mean_mrr": 0.8083, "mean_recall@5": 1.0, "abstention_accuracy": 1.0, "rerank_attempted_rate": 0.4, "latency": {"p50": 14.0, "p95": 22.0, "mean": 15.0}}},
    }
    safety_clean = {
        "fast": {"safety_pass": True, "total_violations": 0},
        "standard": {"safety_pass": True, "total_violations": 0},
    }
    sel = select_recommended_profile(mock_evals, safety_clean)
    assert sel["recommended_default_profile"] == "fast"
    assert sel["pareto_frontier"] == ["fast"]


def test_unsafe_profiles_cannot_be_recommended():
    mock_evals = {
        "fast": {"summary": {"mean_ndcg@10": 0.70, "mean_mrr": 0.8, "mean_recall@5": 1.0, "abstention_accuracy": 1.0, "rerank_attempted_rate": 0.0, "latency": {"p50": 3.0, "p95": 5.0, "mean": 3.2}}},
        "standard": {"summary": {"mean_ndcg@10": 0.99, "mean_mrr": 1.0, "mean_recall@5": 1.0, "abstention_accuracy": 1.0, "rerank_attempted_rate": 0.1, "latency": {"p50": 12.0, "p95": 18.0, "mean": 13.0}}},
    }
    # standard fails safety
    safety_reports = {
        "fast": {"safety_pass": True, "total_violations": 0},
        "standard": {"safety_pass": False, "total_violations": 2},
    }
    sel = select_recommended_profile(mock_evals, safety_reports)
    assert sel["recommended_default_profile"] == "fast"
    assert "standard" in sel["excluded_profiles"]


# ==============================================================================
# 5. RRF Honest Tie Handling
# ==============================================================================

def test_tied_rrf_configurations_preserve_default():
    with MemoryEvalHarness() as harness:
        dev_cases = get_partition_cases("dev", include_variants=True)
        exp1 = run_experiment_1_rrf_k(harness.root, dev_cases)
        assert exp1["optimal_rrf_k"] == 60
        assert "k_60" in exp1["tied_configurations"]
        assert "Preserved existing default k=60" in exp1["selection_reason"]


# ==============================================================================
# 6. Derived Safety Gates & Per-Query Sums
# ==============================================================================

def test_aggregate_safety_values_equal_per_query_violation_sums():
    mock_records = [
        {
            "stale_leakage_count": 1,
            "archived_leakage_count": 0,
            "superseded_leakage_count": 0,
            "abstention_failure": True,
            "uncorroborated_actionable": False,
            "conflicted_actionable": False,
            "project_scope_violation": True,
            "temporal_scope_violation": False,
            "invalid_evidence_status": False,
            "reranker_failure": False,
        },
        {
            "stale_leakage_count": 2,
            "archived_leakage_count": 1,
            "superseded_leakage_count": 1,
            "abstention_failure": False,
            "uncorroborated_actionable": True,
            "conflicted_actionable": True,
            "project_scope_violation": False,
            "temporal_scope_violation": True,
            "invalid_evidence_status": True,
            "reranker_failure": True,
        },
    ]
    safety = derive_safety_gates(mock_records)
    assert safety["stale_leakage_count"] == 3
    assert safety["archived_current_truth_leakage_count"] == 1
    assert safety["superseded_current_truth_leakage_count"] == 1
    assert safety["abstention_failures"] == 1
    assert safety["uncorroborated_actionable_count"] == 1
    assert safety["conflicted_actionable_count"] == 1
    assert safety["project_scope_violation_count"] == 1
    assert safety["temporal_scope_violation_count"] == 1
    assert safety["invalid_evidence_status_count"] == 1
    assert safety["reranker_failure_count"] == 1
    assert safety["total_violations"] == 12
    assert safety["safety_pass"] is False


# ==============================================================================
# 7. Resources: Ollama, Platform-Aware RSS, Subprocess Cold Start
# ==============================================================================

def test_unreachable_ollama_reports_unverified_unavailable():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        status = check_ollama_status()
        assert status["status"] == "unavailable"
        assert status["verified_zero_resident"] is False
        assert "unreachable" in status["reason"]


def test_macos_and_linux_rss_conversions():
    # On macOS, ru_maxrss is in bytes
    darwin_mb = convert_maxrss_to_mb(104857600, "darwin")
    assert darwin_mb == 100.0

    # On Linux, ru_maxrss is in KiB
    linux_mb = convert_maxrss_to_mb(102400, "linux")
    assert linux_mb == 100.0


def test_cold_start_measurement_uses_fresh_subprocess():
    res = measure_cold_and_warm_flashrank_latency()
    assert res["method"] == "fresh_subprocess"
    assert res["warm_samples_count"] == 10
    assert res["cold_first_rerank_ms"] is not None
    assert res["cold_first_rerank_ms"] > 0.0


# ==============================================================================
# 8. Holdout Discipline, Frozen Hash, and Provenance
# ==============================================================================

def test_holdout_discipline_and_frozen_hash():
    with MemoryEvalHarness() as harness:
        cfg = RetrievalConfig.from_profile("fast")
        # Run with holdout=True
        exp7 = run_experiment_7_holdout_validation(harness.root, cfg, holdout=True)
        assert exp7["holdout_evaluations"] == 1
        assert exp7["holdout_used_for_selection"] is False
        assert exp7["selection_partition"] == "dev"

        # Check hash stability
        frozen_dict = cfg.to_dict()
        expected_hash = hashlib.sha256(json.dumps(frozen_dict, sort_keys=True).encode("utf-8")).hexdigest()
        assert exp7["frozen_config_sha256"] == expected_hash

        # Run with holdout=False (dev-only mode)
        exp7_dev = run_experiment_7_holdout_validation(harness.root, cfg, holdout=False)
        assert exp7_dev["holdout_evaluations"] == 0
        assert "skipped" in exp7_dev["findings"]


def test_report_provenance_collection():
    prov = collect_provenance(["tune", "--dev-only"])
    assert "git_sha" in prov
    assert "git_dirty" in prov
    assert isinstance(prov["git_dirty"], bool)
    assert "python_version" in prov
    assert "flashrank_version" in prov
    assert "platform" in prov


# ==============================================================================
# 9. Lane Isolation & Safety Invariants
# ==============================================================================

def test_vector_explicit_mismatch_failure():
    with MemoryEvalHarness() as harness:
        items_model, meta_model = _run_lane_vector(
            harness.root, "concurrency", ["concurrency"], "", None,
            enable_indexed_vector=True, embedding_model="unknown-nonexistent-model"
        )
        assert len(items_model) == 0
        assert meta_model["available"] is False
        assert "Model mismatch" in meta_model["reason"]

        items_dim, meta_dim = _run_lane_vector(
            harness.root, "concurrency", ["concurrency"], "", None,
            enable_indexed_vector=True, embedding_model="test-embed",
            query_embedding=[1.0, 2.0]
        )
        assert len(items_dim) == 0
        assert meta_dim["available"] is False
        assert "Dimension mismatch" in meta_dim["reason"]


def test_graph_2hop_traversal_and_metadata_retention():
    with MemoryEvalHarness() as harness:
        items_2hop = _run_lane_graph(harness.root, ["gms", "mbrain"], "", None, graph_hops=2)
        assert len(items_2hop) > 0

        for item in items_2hop:
            assert "source_id" in item
            assert "target_id" in item
            assert "predicate" in item
            assert "graph_path" in item
            assert "valid_from" in item
            assert "source_claim_id" in item


def test_safety_invariants_holdout_cleanliness():
    with MemoryEvalHarness() as harness:
        cfg = RetrievalConfig.from_profile("standard")
        holdout_cases = get_partition_cases("holdout", include_variants=True)

        for case in holdout_cases:
            res = retrieve(
                harness.root,
                query=case.query,
                project=case.project,
                as_of=case.as_of,
                config=cfg,
                enable_indexed_vector=True,
                embedding_model="test-embed",
                query_embedding=fixture_query_embedding(case.query),
            )
            assert res["evidence_status"] in {"supported", "conflicted", "stale", "insufficient"}

            if case.should_abstain:
                assert res["actionable"] is False or res["evidence_status"] != "supported"

            for item in res["items"]:
                assert item.get("lifecycle_status") not in {"archived", "superseded", "discarded", "expired"}
