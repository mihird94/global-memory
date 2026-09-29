"""Metrics engine for Memory Evaluation Lab.

Provides standard Information Retrieval (IR) metrics (Hit@K, Recall@K, MRR, NDCG@K),
epistemic memory quality metrics (Abstention, Stale Leakage, Constraint Retention),
and latency percentile aggregation.
"""
from __future__ import annotations

import math
from typing import Any, Sequence


def hit_at_k(retrieved: Sequence[str], relevant: set[str], k: int = 5) -> float:
    """Returns 1.0 if at least one relevant item appears in the top-k retrieved items, else 0.0."""
    if not relevant:
        return 1.0
    top_k = retrieved[:k]
    return 1.0 if any(item in relevant for item in top_k) else 0.0


def recall_at_k(retrieved: Sequence[str], relevant: set[str], k: int = 5) -> float:
    """Calculates recall@k: fraction of relevant items present in the top-k retrieved items."""
    if not relevant:
        return 1.0
    top_k = set(retrieved[:k])
    hits = len(top_k.intersection(relevant))
    return hits / len(relevant)


def reciprocal_rank(retrieved: Sequence[str], relevant: set[str]) -> float:
    """Calculates reciprocal rank (1 / rank of first relevant item, 1-indexed)."""
    if not relevant:
        return 1.0
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def dcg_at_k(retrieved: Sequence[str], relevant: set[str], k: int = 10) -> float:
    """Calculates Discounted Cumulative Gain at rank k."""
    dcg = 0.0
    for idx, item in enumerate(retrieved[:k], start=1):
        rel = 1.0 if item in relevant else 0.0
        if rel > 0:
            dcg += rel / math.log2(idx + 1)
    return dcg


def ndcg_at_k(retrieved: Sequence[str], relevant: set[str], k: int = 10) -> float:
    """Calculates Normalized Discounted Cumulative Gain at rank k."""
    if not relevant:
        return 1.0
    actual_dcg = dcg_at_k(retrieved, relevant, k)
    # Ideal DCG: all relevant items ranked at the top
    ideal_retrieved = list(relevant)
    idcg = dcg_at_k(ideal_retrieved, relevant, k)
    if idcg == 0.0:
        return 0.0
    return min(1.0, actual_dcg / idcg)


def abstention_accuracy(
    is_abstention: bool,
    should_abstain: bool,
) -> float:
    """Returns 1.0 if the retrieval/decision correctly abstained when evidence was insufficient,
    or correctly proceeded when evidence was sufficient."""
    return 1.0 if (is_abstention == should_abstain) else 0.0


def stale_leakage_rate(retrieved: Sequence[str], superseded: set[str]) -> float:
    """Fraction of retrieved items that are known superseded / stale items."""
    if not retrieved or not superseded:
        return 0.0
    leaked = [item for item in retrieved if item in superseded]
    return len(leaked) / len(retrieved)


def constraint_retention_rate(context_text: str, expected_constraints: Sequence[str]) -> float:
    """Fraction of expected operational constraints/policies present in the context text."""
    if not expected_constraints:
        return 1.0
    norm_text = context_text.lower()
    hits = sum(1 for c in expected_constraints if c.lower() in norm_text)
    return hits / len(expected_constraints)


def latency_percentiles(latencies_ms: Sequence[float]) -> dict[str, float]:
    """Computes p50, p90, p95, p99, and mean latency percentiles."""
    if not latencies_ms:
        return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "count": 0}

    s = sorted(latencies_ms)
    n = len(s)

    def _perc(p: float) -> float:
        idx = int(math.ceil(p * n)) - 1
        idx = max(0, min(idx, n - 1))
        return round(s[idx], 2)

    return {
        "p50": _perc(0.50),
        "p90": _perc(0.90),
        "p95": _perc(0.95),
        "p99": _perc(0.99),
        "mean": round(sum(s) / n, 2),
        "count": n,
    }
