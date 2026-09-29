"""Unit and integration tests for Memory Evaluation Lab (eval/)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.ablations import run_ablation_study
from eval.datasets.continuation import CONTINUATION_CASES
from eval.datasets.longmemeval import LONGMEMEVAL_CASES
from eval.datasets.memoryagentbench import MEMORYAGENTBENCH_CASES
from eval.harness import MemoryEvalHarness, create_fixture_memory_root, fixture_query_embedding
from eval.metrics import (
    abstention_accuracy,
    constraint_retention_rate,
    dcg_at_k,
    hit_at_k,
    latency_percentiles,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    stale_leakage_rate,
)
from context_retrieval_planner import LANES, make_plan, retrieve


def test_metrics_calculation():
    retrieved = ["doc_a", "doc_b", "doc_c", "doc_d", "doc_e"]
    relevant = {"doc_b", "doc_d"}

    # Hit@1, Hit@3
    assert hit_at_k(retrieved, relevant, k=1) == 0.0
    assert hit_at_k(retrieved, relevant, k=2) == 1.0

    # Recall@2, Recall@5
    assert recall_at_k(retrieved, relevant, k=2) == 0.5
    assert recall_at_k(retrieved, relevant, k=5) == 1.0

    # Reciprocal Rank (first match is doc_b at rank 2)
    assert reciprocal_rank(retrieved, relevant) == 0.5

    # NDCG@10
    ndcg = ndcg_at_k(retrieved, relevant, k=10)
    assert 0.0 < ndcg <= 1.0

    # Abstention
    assert abstention_accuracy(is_abstention=True, should_abstain=True) == 1.0
    assert abstention_accuracy(is_abstention=False, should_abstain=True) == 0.0
    assert abstention_accuracy(is_abstention=False, should_abstain=False) == 1.0

    # Stale leakage
    superseded = {"doc_b"}
    assert stale_leakage_rate(retrieved, superseded) == 1 / 5

    # Latency percentiles
    lats = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p = latency_percentiles(lats)
    assert p["p50"] == 50.0
    assert p["p90"] == 90.0
    assert p["count"] == 10


def test_harness_sandbox_isolation(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    assert (root / "semantic" / "facts.json").exists()
    assert (root / "gms_trust.sqlite").exists()
    assert (root / "projects" / "global-memory" / "projectBrief.md").exists()

    with MemoryEvalHarness(root) as harness:
        assert harness.root == root
        # Read facts
        facts = json.loads((harness.root / "semantic" / "facts.json").read_text())
        assert "global_memory_sqlite_concurrency" in facts


def test_longmemeval_adapter_execution(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    with MemoryEvalHarness(root) as harness:
        report = harness.run_longmemeval()
        assert report["suite"].endswith("LongMemEval-inspired")
        assert report["official_public_benchmark"] is False
        assert report["canonical_cases"] == 12
        assert report["robustness_variants"] == 48
        assert report["total_cases"] == len(LONGMEMEVAL_CASES)
        assert report["passed_cases"] >= 8
        assert "per_ability" in report
        assert "factual_extraction" in report["per_ability"]
        assert "temporal_reasoning" in report["per_ability"]
        assert "knowledge_update" in report["per_ability"]
        assert "abstention" in report["per_ability"]


def test_memoryagentbench_adapter_execution(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    with MemoryEvalHarness(root) as harness:
        report = harness.run_memoryagentbench()
        assert report["suite"].endswith("MemoryAgentBench-inspired")
        assert report["official_public_benchmark"] is False
        assert report["canonical_cases"] == 5
        assert report["robustness_variants"] == 15
        assert report["total_cases"] == len(MEMORYAGENTBENCH_CASES)
        assert report["passed_cases"] >= 3
        assert "latency" in report


def test_continuation_adapter_execution(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    with MemoryEvalHarness(root) as harness:
        report = harness.run_continuation()
        assert report["suite"] == "Brain Context Bundle Structure"
        assert report["evaluates_agent_behavior"] is False
        assert report["total_cases"] == len(CONTINUATION_CASES)
        assert report["passed_cases"] >= 1
        assert "latency" in report


def test_ablation_study_execution(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    res = run_ablation_study(root)
    assert res["schema_version"] == "gms-retrieval-ablation-report-v1"
    assert "strategies" in res
    assert "lexical_bm25" in res["strategies"]
    assert "hybrid_rrf" in res["strategies"]
    assert "mean_recall@5" in res["strategies"]["hybrid_rrf"]
    assert res["official_public_benchmark"] is False
    assert res["strategies"]["dense_vector"]["available"] is True
    assert res["strategies"]["relational_graph"]["available"] is True
    assert res["strategies"]["hybrid_reranked"]["reranking_enabled"] is True
    for strategy, data in res["strategies"].items():
        assert all(set(executed) == set(data["lanes_used"]) for executed in data["executed_lane_sets"])


def test_fixture_dense_vector_lane_uses_stored_embeddings(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    query = "What SQLite WAL concurrency setting is required?"
    result = retrieve(
        root, query, required_lanes=["vector"], enable_indexed_vector=True,
        embedding_model="test-embed", query_embedding=fixture_query_embedding(query),
    )
    assert result["vector_backend"]["available"] is True
    assert result["items"][0]["vector_similarity"] is not None
    assert "sqlite" in result["items"][0]["statement"].lower()


def test_graph_lane_returns_evidence_bearing_relationships(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    result = retrieve(root, "Why was Mbrain agent trust retired?", required_lanes=["graph"])
    assert result["items"]
    assert result["items"][0]["graph_path"]
    assert "provenance" in " ".join(item["statement"].lower() for item in result["items"])


def test_injected_cross_encoder_controls_fused_order(tmp_path):
    root = create_fixture_memory_root(tmp_path)

    def reverse_reranker(_query, items):
        for rank, item in enumerate(reversed(items), start=1):
            item["cross_encoder_score"] = 1.0 / rank
        return list(reversed(items))

    result = retrieve(
        root, "SQLite GMS concurrency", required_lanes=["exact", "bm25"],
        enable_reranking=True, reranker=reverse_reranker,
    )
    assert result["reranker"]["available"] is True
    assert result["reranker"]["backend"] == "injected"
    assert result["items"][0].get("cross_encoder_score") is not None


@pytest.mark.parametrize("lane", LANES)
def test_required_lanes_execute_only_the_requested_lane(tmp_path, lane):
    root = create_fixture_memory_root(tmp_path)
    res = retrieve(root, "Mbrain GMS SQLite current task", project="global-memory", required_lanes=[lane])
    assert set(res["lane_latencies_ms"]) == {lane}
    assert set(res["manifest"]["lane_candidates"]) == {lane}
    assert res["manifest"]["requested_lanes"] == [lane]
    assert all(item["lane"] == lane for item in res["items"])


def test_empty_and_unknown_required_lanes_are_honest(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    empty = retrieve(root, "anything", required_lanes=[])
    assert empty["items"] == []
    assert empty["evidence_status"] == "insufficient"
    assert empty["actionable"] is False
    with pytest.raises(ValueError, match="Unknown retrieval lane"):
        make_plan("anything", required_lanes=["imaginary"])


def test_archived_status_is_stale_and_not_actionable(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    res = retrieve(root, "Execute car stickers status next action", project="global-memory")
    assert res["evidence_status"] == "stale"
    assert res["actionable"] is False
    assert all(item["key"] != "car_stickers_status" for item in res["items"])
    archived = [item for item in res["lifecycle_evidence"] if item["key"] == "car_stickers_status"]
    assert archived and archived[0]["lifecycle_status"] == "archived"
    assert any(item["key"] == "car_stickers_status" for item in res["omission_manifest"])


def test_unknown_query_has_explicit_insufficient_evidence(tmp_path):
    root = create_fixture_memory_root(tmp_path)
    res = retrieve(root, "Ethereum validator private key", project="global-memory")
    assert res["evidence_status"] == "insufficient"
    assert res["actionable"] is False
