"""Multi-method retrieval ablation engine for Memory Evaluation Lab.

Ablates and compares 5 distinct retrieval strategies on identical benchmark queries:
1. Lexical Only (BM25)
2. Dense Vector Only (SQLite embeddings / Cosine)
3. Relational Graph Only (Personalized PageRank)
4. Hybrid RRF (Multi-lane reciprocal rank fusion)
5. Hybrid RRF + local FlashRank cross-encoder reranker
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from research_harness.eval.datasets.longmemeval import LONGMEMEVAL_CASES
from research_harness.eval.harness import fixture_query_embedding
from research_harness.eval.metrics import hit_at_k, latency_percentiles, ndcg_at_k, recall_at_k, reciprocal_rank

ABLATION_CONFIGS = [
    {"name": "lexical_bm25", "lanes": ["bm25"], "rerank": False},
    {"name": "dense_vector", "lanes": ["vector"], "rerank": False},
    {"name": "relational_graph", "lanes": ["graph"], "rerank": False},
    {"name": "hybrid_rrf", "lanes": ["exact", "bm25", "vector", "graph", "decisions", "procedures", "tasks", "conflicts"], "rerank": False},
    {"name": "hybrid_reranked", "lanes": ["exact", "bm25", "vector", "graph", "decisions", "procedures", "tasks", "conflicts"], "rerank": True},
]


def run_ablation_study(root: Path) -> dict[str, Any]:
    """Executes comparative ablation across all configured retrieval strategies."""
    from context_retrieval_planner import retrieve

    # Filter out abstention queries for retrieval quality ranking comparison
    eval_cases = [c for c in LONGMEMEVAL_CASES if not c.should_abstain and c.relevant_keys]

    ablation_results = {}

    for cfg in ABLATION_CONFIGS:
        strat_name = cfg["name"]
        lanes = cfg["lanes"]
        rerank = cfg["rerank"]

        recalls = []
        hits = []
        mrrs = []
        ndcgs = []
        latencies = []
        executed_lane_sets: list[list[str]] = []
        reranker_states: list[dict[str, Any]] = []

        for case in eval_cases:
            t0 = time.perf_counter()
            retrieval = retrieve(
                root,
                query=case.query,
                project=case.project,
                as_of=case.as_of,
                required_lanes=lanes,
                token_budget=2400,
                enable_indexed_vector="vector" in lanes,
                embedding_model="test-embed",
                query_embedding=fixture_query_embedding(case.query) if "vector" in lanes else None,
                enable_reranking=rerank,
            )
            lat_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(lat_ms)

            items = retrieval.get("items", [])
            if rerank:
                reranker_states.append(retrieval.get("reranker", {}))
            executed_lane_sets.append(sorted(retrieval.get("lane_latencies_ms", {}).keys()))
            retrieved_keys = [it.get("key", "").lower() for it in items]
            retrieved_text = [f"{it.get('key', '')} {it.get('statement', '')}".lower() for it in items]

            rel_set = set(k.lower() for k in case.relevant_keys)

            # Match items
            matched_indices = []
            for rank_idx, txt in enumerate(retrieved_text):
                if any(k in txt for k in rel_set):
                    matched_indices.append(rank_idx)

            # Recall & Hit
            top_text = " ".join(retrieved_text[:5])
            hits_count = sum(1 for k in rel_set if k in top_text)
            rec = hits_count / max(1, len(rel_set))
            hit = 1.0 if hits_count > 0 else 0.0

            # MRR (first match rank)
            mrr = 1.0 / (matched_indices[0] + 1) if matched_indices else 0.0

            # NDCG
            unmatched_relevant = set(rel_set)
            relevance_ids = []
            for i, txt in enumerate(retrieved_text):
                matched_key = next((key for key in sorted(unmatched_relevant) if key in txt), None)
                if matched_key is None:
                    relevance_ids.append(f"nonrelevant-{i}")
                else:
                    relevance_ids.append(matched_key)
                    unmatched_relevant.remove(matched_key)
            ndcg = ndcg_at_k(relevance_ids, rel_set, k=10)

            recalls.append(rec)
            hits.append(hit)
            mrrs.append(mrr)
            ndcgs.append(ndcg)

        n = max(1, len(eval_cases))
        reranker_available = not rerank or any(state.get("available") for state in reranker_states)
        available = any(hits) and reranker_available
        ablation_results[strat_name] = {
            "strategy": strat_name,
            "lanes_used": lanes,
            "reranking_enabled": rerank,
            "available": available,
            "reason": None if available else (
                reranker_states[0].get("reason", "Cross-encoder unavailable") if rerank and reranker_states
                else "Requested lane produced no usable candidates in deterministic fixture evaluation."
            ),
            "reranker": reranker_states[0] if reranker_states else None,
            "executed_lane_sets": executed_lane_sets,
            "queries_evaluated": len(eval_cases),
            "mean_recall@5": round(sum(recalls) / n, 3),
            "mean_hit@5": round(sum(hits) / n, 3),
            "mean_mrr": round(sum(mrrs) / n, 3),
            "mean_ndcg@10": round(sum(ndcgs) / n, 3),
            "latency": latency_percentiles(latencies),
        }

    return {
        "schema_version": "gms-retrieval-ablation-report-v1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "benchmark_scope": "brain_local_adapter",
        "official_public_benchmark": False,
        "strategies": ablation_results,
    }
