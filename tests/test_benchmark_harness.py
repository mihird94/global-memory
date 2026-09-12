#!/usr/bin/env python3
"""
tests/test_benchmark_harness.py
Unit tests for the Continuous Evaluation Retrieval Benchmark Harness (tools/eval_retrieval_benchmark.py).
"""
import json
import math
import sys
from pathlib import Path

# Add tools directory to path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import eval_retrieval_benchmark as eval_harness


def test_calculate_hit_at_k():
    ranked = ["doc_a", "doc_b", "doc_c", "doc_d", "doc_e"]
    assert eval_harness.calculate_hit_at_k(ranked, "doc_a", 1) == 1
    assert eval_harness.calculate_hit_at_k(ranked, "doc_b", 1) == 0
    assert eval_harness.calculate_hit_at_k(ranked, "doc_b", 3) == 1
    assert eval_harness.calculate_hit_at_k(ranked, "doc_e", 3) == 0
    assert eval_harness.calculate_hit_at_k(ranked, "doc_e", 5) == 1
    assert eval_harness.calculate_hit_at_k(ranked, "doc_missing", 5) == 0


def test_calculate_mrr():
    ranked = ["doc_a", "doc_b", "doc_c", "doc_d"]
    assert eval_harness.calculate_mrr(ranked, "doc_a") == 1.0
    assert eval_harness.calculate_mrr(ranked, "doc_b") == 0.5
    assert eval_harness.calculate_mrr(ranked, "doc_c") == round(1.0 / 3, 6) or abs(eval_harness.calculate_mrr(ranked, "doc_c") - 1/3) < 1e-5
    assert eval_harness.calculate_mrr(ranked, "doc_d") == 0.25
    assert eval_harness.calculate_mrr(ranked, "missing") == 0.0


def test_calculate_dcg_and_idcg_and_ndcg():
    # Perfect ranking test:
    # doc1 (rel=3), doc2 (rel=2), doc3 (rel=1)
    rel_map = {"doc1": 3, "doc2": 2, "doc3": 1}
    perfect_ranking = ["doc1", "doc2", "doc3"]
    idcg = eval_harness.calculate_idcg(rel_map, k=3)
    dcg = eval_harness.calculate_dcg(perfect_ranking, rel_map, k=3)
    assert math.isclose(dcg, idcg)
    assert math.isclose(eval_harness.calculate_ndcg(perfect_ranking, rel_map, k=3), 1.0)

    # Inverted ranking test:
    inverted_ranking = ["doc3", "doc2", "doc1"]
    inv_ndcg = eval_harness.calculate_ndcg(inverted_ranking, rel_map, k=3)
    assert 0.0 < inv_ndcg < 1.0

    # Irrelevant ranking test:
    zero_ranking = ["unrelated1", "unrelated2"]
    assert eval_harness.calculate_ndcg(zero_ranking, rel_map, k=3) == 0.0

    # Empty relevance test:
    assert eval_harness.calculate_ndcg(["doc1"], {}, k=3) == 0.0


def test_deterministic_synthetic_engine():
    corpus = [
        {"id": "c1", "text": "alphaos trading rules and capital sizing heat"},
        {"id": "c2", "text": "capital one credit card billing due on 21st"},
        {"id": "c3", "text": "kunjan birthday celebration february 21"},
    ]
    engine = eval_harness.DeterministicSyntheticEngine(corpus)

    for method in ("dense", "lexical", "hybrid", "rerank"):
        ranked, lat = engine.rank("capital one credit card payment", method)
        assert len(ranked) == 3
        assert lat >= 0.0
        # "capital one credit card payment" should rank c2 at the top
        assert ranked[0] == "c2"


def test_benchmark_full_execution_synthetic():
    report = eval_harness.run_benchmark(
        engine_mode="synthetic",
        include_adversarial=True,
        adversarial_only=False,
    )

    assert report.engine_mode == "synthetic"
    assert report.corpus_size == len(eval_harness.BENCHMARK_CORPUS)
    assert report.num_standard_queries == len(eval_harness.STANDARD_QUERIES)
    assert report.num_adversarial_queries == len(eval_harness.ADVERSARIAL_QUERIES)

    expected_methods = [
        "Dense Bi-Encoder",
        "Lexical (TF-IDF/BM25)",
        "Hybrid RRF",
        "Hybrid + Reranker"
    ]

    for m in expected_methods:
        assert m in report.methods
        metrics = report.methods[m]
        assert "Hit@1" in metrics
        assert "Hit@3" in metrics
        assert "Hit@5" in metrics
        assert "MRR" in metrics
        assert "NDCG@10" in metrics
        assert "Adversarial_Resistance_Rate" in metrics
        assert "Latency_P50_ms" in metrics
        assert "Latency_P95_ms" in metrics
        assert "Latency_P99_ms" in metrics

        # Metric value ranges
        assert 0.0 <= metrics["Hit@1"] <= 1.0
        assert 0.0 <= metrics["Hit@3"] <= 1.0
        assert 0.0 <= metrics["Hit@5"] <= 1.0
        assert metrics["Hit@1"] <= metrics["Hit@3"] <= metrics["Hit@5"]
        assert 0.0 <= metrics["MRR"] <= 1.0
        assert 0.0 <= metrics["NDCG@10"] <= 1.0
        assert 0.0 <= metrics["Adversarial_Resistance_Rate"] <= 1.0

    # Ensure JSON serializability
    report_dict = eval_harness.asdict(report)
    json_str = json.dumps(report_dict)
    assert len(json_str) > 0


def test_benchmark_adversarial_only_mode():
    report = eval_harness.run_benchmark(
        engine_mode="synthetic",
        include_adversarial=True,
        adversarial_only=True,
    )
    assert report.num_standard_queries == 0
    assert report.num_adversarial_queries == len(eval_harness.ADVERSARIAL_QUERIES)
    assert len(report.adversarial_analysis["queries"]) == len(eval_harness.ADVERSARIAL_QUERIES)
