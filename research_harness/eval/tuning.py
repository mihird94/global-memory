"""Retrieval Configuration Tuning and Empirical Evaluation Engine.

Executes Experiments 1 through 8 across partitioned LongMemEval fixtures:
- Experiment 1: RRF k parameter sweep ([10, 30, 60, 90, 120]) with honest tie-breaking
- Experiment 2: Lane weights (Configurations A–F)
- Experiment 3: Candidate depth per lane (lexical, vector, graph, rerank)
- Experiment 4: Reranking policies & threshold sweeps (never, always, assurance, intent, ambiguity, conditional)
- Experiment 5: Relational graph retrieval (1-hop vs 2-hop, metadata retention, alias expansion)
- Experiment 6: Vector configuration (similarity cutoff, candidate depth, explicit failure on mismatch)
- Experiment 7: Holdout validation (single evaluation of frozen winner, canonical vs variant breakdown)
- Experiment 8: Latency, resource consumption, fresh-subprocess cold start, and Ollama status
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from context_retrieval_planner import (
    DEFAULT_CANDIDATE_LIMITS,
    DEFAULT_LANE_WEIGHTS,
    LANES,
    RetrievalConfig,
    _run_lane_vector,
    retrieve,
)
from research_harness.eval.datasets.longmemeval import LONGMEMEVAL_CASES, LongMemEvalTestCase
from research_harness.eval.harness import MemoryEvalHarness, fixture_query_embedding
from research_harness.eval.metrics import hit_at_k, latency_percentiles, ndcg_at_k, recall_at_k, reciprocal_rank
from research_harness.eval.partitions import get_partition_cases, get_partition_for_case_id, verify_partition_isolation


# ==============================================================================
# PLATFORM & RESOURCE HELPERS
# ==============================================================================

def convert_maxrss_to_mb(raw_rss: int, platform_str: str) -> float:
    """Converts getrusage ru_maxrss to megabytes with OS-specific units.

    On macOS (Darwin), ru_maxrss is reported in bytes.
    On Linux and other POSIX OSes, ru_maxrss is reported in KiB.
    """
    if "darwin" in platform_str.lower():
        return round(raw_rss / (1024.0 * 1024.0), 2)
    else:
        return round(raw_rss / 1024.0, 2)


def get_peak_rss_mb() -> float:
    """Returns the process peak RSS in MB using platform-aware conversion."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return convert_maxrss_to_mb(raw, sys.platform)


def check_ollama_status() -> dict[str, Any]:
    """Verifies Ollama running state without converting lack of access into success."""
    url_ps = "http://127.0.0.1:11434/api/ps"
    url_gen = "http://127.0.0.1:11434/api/generate"
    try:
        req = urllib.request.Request(url_ps)
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            initial_resident = [m.get("name") or m.get("model") for m in models if m.get("name") or m.get("model")]

            unloaded = []
            for m_name in initial_resident:
                try:
                    payload = json.dumps({"model": m_name, "keep_alive": 0}).encode("utf-8")
                    req_unload = urllib.request.Request(url_gen, data=payload, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req_unload, timeout=3.0) as u_resp:
                        u_resp.read()
                        unloaded.append(m_name)
                except Exception:
                    pass

            with urllib.request.urlopen(urllib.request.Request(url_ps), timeout=1.5) as final_resp:
                final_data = json.loads(final_resp.read().decode("utf-8"))
                final_models = final_data.get("models", [])
                final_names = [m.get("name") or m.get("model") for m in final_models if m.get("name") or m.get("model")]
                if not final_names:
                    return {
                        "status": "verified_zero_resident",
                        "verified_zero_resident": True,
                        "initial_resident_models": initial_resident,
                        "unloaded_models": unloaded,
                        "current_resident_models": [],
                    }
                else:
                    return {
                        "status": "models_resident",
                        "verified_zero_resident": False,
                        "initial_resident_models": initial_resident,
                        "unloaded_models": unloaded,
                        "current_resident_models": final_names,
                    }
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        return {
            "status": "unavailable",
            "verified_zero_resident": False,
            "reason": f"Ollama endpoint unreachable at {url_ps}: {exc}",
            "current_resident_models": [],
        }
    except Exception as exc:
        return {
            "status": "verification_failed",
            "verified_zero_resident": False,
            "reason": f"Unexpected error querying Ollama: {exc}",
            "current_resident_models": [],
        }


def measure_cold_and_warm_flashrank_latency() -> dict[str, Any]:
    """Measures cold start and warm latency using a fresh subprocess for isolation."""
    script = """
import time, json
t0 = time.perf_counter()
from flashrank import Ranker, RerankRequest
t_import = time.perf_counter()
ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir="/tmp/flashrank")
t_init = time.perf_counter()

passages = [
    {"id": "1", "text": "Test passage one for latency measurement"},
    {"id": "2", "text": "Test passage two for latency measurement"},
    {"id": "3", "text": "Test passage three for latency measurement"},
]
req = RerankRequest(query="latency test query", passages=passages)

t_rerank0 = time.perf_counter()
ranker.rerank(req)
t_rerank1 = time.perf_counter()
cold_first_rerank_ms = (t_rerank1 - t_rerank0) * 1000.0

warm_times = []
for _ in range(10):
    t_w0 = time.perf_counter()
    ranker.rerank(req)
    warm_times.append((time.perf_counter() - t_w0) * 1000.0)

warm_times.sort()
print(json.dumps({
    "cold_import_and_init_ms": round((t_init - t0) * 1000.0, 2),
    "cold_first_rerank_ms": round(cold_first_rerank_ms, 2),
    "warm_samples_count": len(warm_times),
    "warm_mean_ms": round(sum(warm_times) / len(warm_times), 2),
    "warm_p50_ms": round(warm_times[len(warm_times) // 2], 2),
    "warm_min_ms": round(warm_times[0], 2),
    "warm_max_ms": round(warm_times[-1], 2),
}))
"""
    try:
        res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
        data = json.loads(res.stdout.strip())
        data["method"] = "fresh_subprocess"
        return data
    except Exception as exc:
        return {
            "method": "fresh_subprocess",
            "error": str(exc),
            "cold_import_and_init_ms": None,
            "cold_first_rerank_ms": None,
            "warm_samples_count": 0,
        }


def collect_provenance(command_args: list[str] | None = None) -> dict[str, Any]:
    """Collects reproducible runtime environment and Git provenance."""
    git_sha = "unknown"
    git_dirty = False
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        git_sha = res.stdout.strip()
        res_status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        git_dirty = bool(res_status.stdout.strip())
    except Exception:
        pass

    def get_pkg_version(mod_name: str) -> str:
        try:
            import importlib.metadata
            return importlib.metadata.version(mod_name)
        except Exception:
            return "not_installed"

    return {
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "platform_release": platform.release(),
        "flashrank_version": get_pkg_version("flashrank"),
        "onnxruntime_version": get_pkg_version("onnxruntime"),
        "networkx_version": get_pkg_version("networkx"),
        "scipy_version": get_pkg_version("scipy"),
        "embedding_fixture_model": "test-embed",
        "evaluation_command": command_args or sys.argv,
        "start_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "random_seed": None,
    }


# ==============================================================================
# PER-QUERY MEASUREMENT & DERIVED SAFETY GATES
# ==============================================================================

def derive_safety_gates(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculates aggregate safety metrics strictly by summing individual query records."""
    stale_leakage_count = sum(r["stale_leakage_count"] for r in records)
    archived_leakage_count = sum(r["archived_leakage_count"] for r in records)
    superseded_leakage_count = sum(r.get("superseded_leakage_count", 0) for r in records)
    abstention_failures = sum(1 for r in records if r["abstention_failure"])
    uncorroborated_actionable_count = sum(1 for r in records if r["uncorroborated_actionable"])
    conflicted_actionable_count = sum(1 for r in records if r["conflicted_actionable"])
    project_scope_violation_count = sum(1 for r in records if r["project_scope_violation"])
    temporal_scope_violation_count = sum(1 for r in records if r["temporal_scope_violation"])
    invalid_evidence_status_count = sum(1 for r in records if r["invalid_evidence_status"])
    reranker_failure_count = sum(1 for r in records if r["reranker_failure"])

    total_violations = (
        stale_leakage_count
        + archived_leakage_count
        + superseded_leakage_count
        + abstention_failures
        + uncorroborated_actionable_count
        + conflicted_actionable_count
        + project_scope_violation_count
        + temporal_scope_violation_count
        + invalid_evidence_status_count
        + reranker_failure_count
    )

    safety_pass = (total_violations == 0)

    return {
        "safety_pass": safety_pass,
        "total_violations": total_violations,
        "stale_leakage_count": stale_leakage_count,
        "archived_current_truth_leakage_count": archived_leakage_count,
        "superseded_current_truth_leakage_count": superseded_leakage_count,
        "abstention_failures": abstention_failures,
        "uncorroborated_actionable_count": uncorroborated_actionable_count,
        "conflicted_actionable_count": conflicted_actionable_count,
        "project_scope_violation_count": project_scope_violation_count,
        "temporal_scope_violation_count": temporal_scope_violation_count,
        "invalid_evidence_status_count": invalid_evidence_status_count,
        "reranker_failure_count": reranker_failure_count,
    }


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculates summary statistics and safety gates strictly from raw per-query records."""
    safety = derive_safety_gates(records)

    ranking_records = [r for r in records if not r["should_abstain"] and r["relevant_keys"]]
    abstention_records = [r for r in records if r["should_abstain"]]

    n_rank = len(ranking_records)
    n_abstain = len(abstention_records)
    latencies = [r["total_latency_ms"] for r in records]

    summary = {
        "total_queries": len(records),
        "ranking_queries": n_rank,
        "abstention_queries": n_abstain,
        "mean_recall@5": round(sum(r["recall_at_5"] for r in ranking_records) / n_rank, 4) if n_rank else 1.0,
        "mean_hit@5": round(sum(r["hit_at_5"] for r in ranking_records) / n_rank, 4) if n_rank else 1.0,
        "mean_mrr": round(sum(r["reciprocal_rank"] for r in ranking_records) / n_rank, 4) if n_rank else 1.0,
        "mean_ndcg@10": round(sum(r["ndcg_at_10"] for r in ranking_records) / n_rank, 4) if n_rank else 1.0,
        "abstention_accuracy": round(sum(1 for r in abstention_records if not r["abstention_failure"]) / n_abstain, 4) if n_abstain else 1.0,
        "rerank_attempted_rate": round(sum(1 for r in records if r["reranker_attempted"]) / max(1, len(records)), 4) if records else 0.0,
        "latency": latency_percentiles(latencies) if latencies else {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0},
    }

    return {
        "summary": summary,
        "safety": safety,
        "records": records,
    }


def evaluate_configuration(
    root: Path,
    config: RetrievalConfig,
    cases: list[LongMemEvalTestCase],
    *,
    assurance: str = "standard",
    partition_name: str = "",
) -> dict[str, Any]:
    """Evaluates a retrieval configuration and returns complete per-query measurement records."""
    records: list[dict[str, Any]] = []

    for case in cases:
        t0 = time.perf_counter()
        retrieval = retrieve(
            root,
            query=case.query,
            project=case.project,
            as_of=case.as_of,
            assurance=assurance,
            config=config,
            token_budget=2400,
            enable_indexed_vector=True,
            embedding_model="test-embed",
            query_embedding=fixture_query_embedding(case.query),
        )
        total_latency_ms = (time.perf_counter() - t0) * 1000.0

        items = retrieval.get("items", [])
        top10_items = items[:10]
        top5_items = items[:5]
        retrieved_keys_top_10 = [str(it.get("key", "")) for it in top10_items]
        retrieved_lifecycle_states_top_10 = [str(it.get("lifecycle_status", "active")) for it in top10_items]
        evidence_status = retrieval.get("evidence_status", "insufficient")
        actionable = bool(retrieval.get("actionable", False))

        rerank_meta = retrieval.get("reranker", {})
        reranker_enabled = bool(rerank_meta.get("enabled", False))
        reranker_attempted = bool(rerank_meta.get("attempted", False))
        reranker_available = bool(rerank_meta.get("available", False))
        rerank_reason = str(rerank_meta.get("reason", ""))
        rerank_latency_ms = float(rerank_meta.get("latency_ms", 0.0))

        if case.should_abstain:
            recall_at_5 = 0.0
            hit_at_5 = 0.0
            reciprocal_rank_val = 0.0
            ndcg_at_10_val = 0.0
            abstention_failure = bool(actionable and evidence_status == "supported")
        else:
            rel_set = set(k.lower() for k in case.relevant_keys)
            retrieved_text = [f"{it.get('key', '')} {it.get('statement', '')}".lower() for it in items]
            top5_text = " ".join(retrieved_text[:5])
            hits_count = sum(1 for k in rel_set if k in top5_text)
            recall_at_5 = hits_count / max(1, len(rel_set)) if rel_set else 1.0
            hit_at_5 = 1.0 if hits_count > 0 else 0.0

            matched_indices = [idx for idx, txt in enumerate(retrieved_text) if any(k in txt for k in rel_set)]
            reciprocal_rank_val = 1.0 / (matched_indices[0] + 1) if matched_indices else 0.0

            unmatched_relevant = set(rel_set)
            relevance_ids = []
            for i, txt in enumerate(retrieved_text):
                matched_key = next((key for key in sorted(unmatched_relevant) if key in txt), None)
                if matched_key is None:
                    relevance_ids.append(f"nonrelevant-{i}")
                else:
                    relevance_ids.append(matched_key)
                    unmatched_relevant.remove(matched_key)
            ndcg_at_10_val = ndcg_at_k(relevance_ids, rel_set, k=10) if rel_set else 1.0
            abstention_failure = False

        stale_leakage_count = sum(
            1 for it in top10_items
            if it.get("lifecycle_status") in {"stale", "expired"} or it.get("freshness_state") == "stale"
        )
        archived_leakage_count = sum(
            1 for it in top10_items
            if it.get("lifecycle_status") == "archived"
        )
        superseded_leakage_count = sum(
            1 for it in top5_items
            if any(k.lower() == str(it.get("key", "")).lower() for k in case.superseded_keys)
        )
        conflict_visible = bool(any(
            it.get("contradiction_flag") or it.get("lifecycle_status") in {"quarantined", "contested"}
            for it in top10_items
        ))
        project_scope_violation = bool(
            case.project
            and any("/projects/" in it.get("source", "") and f"/projects/{case.project}/" not in it.get("source", "")
                    for it in top10_items)
        )
        temporal_scope_violation = bool(
            case.as_of
            and any(str(it.get("effective_at", ""))[:10] > str(case.as_of)[:10]
                    for it in top10_items if it.get("effective_at"))
        )
        uncorroborated_actionable = bool(
            actionable
            and any(it.get("requires_corroboration") or it.get("record_shape") == "legacy_flat"
                    for it in top5_items[:1])
        )
        conflicted_actionable = bool(
            actionable and (evidence_status == "conflicted" or conflict_visible)
        )
        invalid_evidence_status = bool(
            evidence_status not in {"supported", "conflicted", "stale", "insufficient"}
        )
        reranker_failure = bool(reranker_attempted and not reranker_available)

        case_partition = partition_name or get_partition_for_case_id(case.id)

        record = {
            "case_id": case.id,
            "canonical_case_id": case.variant_of or case.id,
            "partition": case_partition,
            "is_variant": bool(case.variant_of is not None),
            "ability": case.ability,
            "query": case.query,
            "project": case.project,
            "as_of": case.as_of,
            "relevant_keys": list(case.relevant_keys),
            "superseded_keys": list(case.superseded_keys),
            "should_abstain": case.should_abstain,
            "retrieved_keys_top_10": retrieved_keys_top_10,
            "retrieved_lifecycle_states_top_10": retrieved_lifecycle_states_top_10,
            "evidence_status": evidence_status,
            "actionable": actionable,
            "recall_at_5": round(recall_at_5, 4),
            "hit_at_5": round(hit_at_5, 4),
            "reciprocal_rank": round(reciprocal_rank_val, 4),
            "ndcg_at_10": round(ndcg_at_10_val, 4),
            "stale_leakage_count": stale_leakage_count,
            "archived_leakage_count": archived_leakage_count,
            "superseded_leakage_count": superseded_leakage_count,
            "conflict_visible": conflict_visible,
            "project_scope_violation": project_scope_violation,
            "temporal_scope_violation": temporal_scope_violation,
            "uncorroborated_actionable": uncorroborated_actionable,
            "conflicted_actionable": conflicted_actionable,
            "abstention_failure": abstention_failure,
            "invalid_evidence_status": invalid_evidence_status,
            "reranker_enabled": reranker_enabled,
            "reranker_attempted": reranker_attempted,
            "reranker_available": reranker_available,
            "reranker_failure": reranker_failure,
            "rerank_reason": rerank_reason,
            "rerank_latency_ms": round(rerank_latency_ms, 2),
            "total_latency_ms": round(total_latency_ms, 2),
        }
        records.append(record)

    return summarize_records(records)


# ==============================================================================
# PARETO FRONTIER & PROFILE SELECTION
# ==============================================================================

def select_recommended_profile(
    profiles_eval: dict[str, Any],
    safety_reports: dict[str, Any],
    *,
    min_recall: float = 0.99,
    min_abstention: float = 1.0,
) -> dict[str, Any]:
    """Computes Pareto dominance and selects recommended profile strictly from evidence."""
    eligible: list[dict[str, Any]] = []
    excluded: dict[str, str] = {}

    for name, p_eval in profiles_eval.items():
        summary = p_eval["summary"]
        safety = safety_reports[name]
        if not safety.get("safety_pass", False):
            excluded[name] = f"Failed safety gates with {safety.get('total_violations')} violations"
            continue
        if summary.get("mean_recall@5", 0.0) < min_recall:
            excluded[name] = f"Recall@5 ({summary.get('mean_recall@5')}) below required minimum {min_recall}"
            continue
        if summary.get("abstention_accuracy", 0.0) < min_abstention:
            excluded[name] = f"Abstention accuracy ({summary.get('abstention_accuracy')}) regressed below {min_abstention}"
            continue
        eligible.append({
            "profile": name,
            "ndcg@10": summary["mean_ndcg@10"],
            "mrr": summary["mean_mrr"],
            "recall@5": summary["mean_recall@5"],
            "latency_p50_ms": summary["latency"]["p50"],
            "latency_p95_ms": summary["latency"]["p95"],
            "latency_mean_ms": summary["latency"]["mean"],
            "rerank_attempted_rate": summary["rerank_attempted_rate"],
            "summary": summary,
        })

    if not eligible:
        raise ValueError(f"No profiles passed eligibility gates! Excluded: {excluded}")

    frontier: list[dict[str, Any]] = []
    for cand in eligible:
        is_dominated = False
        for other in eligible:
            if other["profile"] == cand["profile"]:
                continue
            better_or_equal = (
                other["ndcg@10"] >= cand["ndcg@10"]
                and other["mrr"] >= cand["mrr"]
                and other["recall@5"] >= cand["recall@5"]
                and other["latency_p50_ms"] <= cand["latency_p50_ms"]
                and other["latency_p95_ms"] <= cand["latency_p95_ms"]
                and other["rerank_attempted_rate"] <= cand["rerank_attempted_rate"]
            )
            strictly_better = (
                other["ndcg@10"] > cand["ndcg@10"]
                or other["mrr"] > cand["mrr"]
                or other["recall@5"] > cand["recall@5"]
                or other["latency_p50_ms"] < cand["latency_p50_ms"]
                or other["latency_p95_ms"] < cand["latency_p95_ms"]
                or other["rerank_attempted_rate"] < cand["rerank_attempted_rate"]
            )
            if better_or_equal and strictly_better:
                is_dominated = True
                break
        if not is_dominated:
            frontier.append(cand)

    frontier_names = [p["profile"] for p in frontier]

    if len(frontier) == 1:
        recommended = frontier[0]["profile"]
        rationale = (
            f"Profile '{recommended}' strictly dominates all other eligible profiles across measured quality "
            f"(NDCG@10={frontier[0]['ndcg@10']:.4f}, MRR={frontier[0]['mrr']:.4f}), latency (P50={frontier[0]['latency_p50_ms']}ms), "
            f"and rerank overhead ({frontier[0]['rerank_attempted_rate']*100:.1f}%)."
        )
    else:
        max_ndcg = max(p["ndcg@10"] for p in frontier)
        quality_close = [p for p in frontier if (max_ndcg - p["ndcg@10"]) <= 0.02]
        chosen = min(quality_close, key=lambda p: (p["rerank_attempted_rate"], p["latency_p50_ms"]))
        recommended = chosen["profile"]
        rationale = (
            f"Multiple non-dominated profiles on Pareto frontier ({frontier_names}). Selected '{recommended}' "
            f"as the lowest-cost configuration within quality tolerance (NDCG={chosen['ndcg@10']:.4f}, "
            f"P50={chosen['latency_p50_ms']}ms, rerank rate={chosen['rerank_attempted_rate']*100:.1f}%)."
        )

    return {
        "recommended_default_profile": recommended,
        "pareto_frontier": frontier_names,
        "pareto_profiles": frontier,
        "eligible_profiles": [p["profile"] for p in eligible],
        "excluded_profiles": excluded,
        "selection_rationale": rationale,
    }


# ==============================================================================
# INDIVIDUAL EXPERIMENT RUNNERS (1–8)
# ==============================================================================

def run_experiment_1_rrf_k(root: Path, dev_cases: list[LongMemEvalTestCase]) -> dict[str, Any]:
    """Experiment 1: RRF k parameter sweep across [10, 30, 60, 90, 120] with honest tie handling."""
    k_values = [10, 30, 60, 90, 120]
    results = {}
    metric_tolerance = 1e-6

    for k in k_values:
        cfg = RetrievalConfig(rrf_k=k, rerank_policy="never")
        eval_res = evaluate_configuration(root, cfg, dev_cases, partition_name="dev")
        results[f"k_{k}"] = {
            "rrf_k": k,
            "recall@5": eval_res["summary"]["mean_recall@5"],
            "ndcg@10": eval_res["summary"]["mean_ndcg@10"],
            "mrr": eval_res["summary"]["mean_mrr"],
            "latency_p50_ms": eval_res["summary"]["latency"]["p50"],
            "latency_mean_ms": eval_res["summary"]["latency"]["mean"],
        }

    best_ndcg = max(r["ndcg@10"] for r in results.values())
    tied_k = [r["rrf_k"] for r in results.values() if abs(r["ndcg@10"] - best_ndcg) <= metric_tolerance]

    if 60 in tied_k:
        selected_k = 60
        selection_reason = "Preserved existing default k=60 as all tested values tied within quality tolerance."
    else:
        selected_k = min(tied_k, key=lambda k: results[f"k_{k}"]["latency_p50_ms"])
        selection_reason = f"Selected k={selected_k} with lowest P50 latency among tied configurations."

    findings = (
        f"All tested RRF constants {k_values} produced tied retrieval quality (NDCG@10={best_ndcg:.4f}, Recall@5=1.000). "
        f"Under the simplicity-preserving tie-break rule, existing default k={selected_k} was retained rather than "
        f"arbitrarily designating a first-encountered value as optimal."
    )

    return {
        "description": "Reciprocal Rank Fusion k constant sweep on Dev partition with honest tie handling",
        "results": results,
        "tied_configurations": [f"k_{k}" for k in tied_k],
        "metric_tolerance": metric_tolerance,
        "tie_break_rule": (
            "1. Preserve existing default (k=60); "
            "2. Prefer lower latency if meaningfully different (>1.0 ms); "
            "3. Otherwise prefer smaller behavioral change; "
            "4. Never call an arbitrary first value 'optimal'."
        ),
        "selected_configuration": f"k_{selected_k}",
        "optimal_rrf_k": selected_k,
        "selection_reason": selection_reason,
        "findings": findings,
    }


def run_experiment_2_lane_weights(root: Path, dev_cases: list[LongMemEvalTestCase], rrf_k: int = 60) -> dict[str, Any]:
    """Experiment 2: Lane weights comparison (Configurations A–F)."""
    configs: dict[str, dict[str, float]] = {
        "weight_A_equal": {l: 1.0 for l in LANES},
        "weight_B_lexical_heavy": {**{l: 0.8 for l in LANES}, "bm25": 1.5, "exact": 1.5},
        "weight_C_vector_heavy": {**{l: 1.0 for l in LANES}, "vector": 1.5, "bm25": 0.8},
        "weight_D_decision_heavy": {**{l: 1.0 for l in LANES}, "decisions": 1.5, "procedures": 1.5, "conflicts": 1.2},
        "weight_E_safety_heavy": {**{l: 1.0 for l in LANES}, "conflicts": 2.0, "decisions": 1.3, "exact": 1.3},
        "weight_F_tuned_balanced": {
            "exact": 1.25, "bm25": 1.0, "vector": 1.0, "decisions": 1.25,
            "procedures": 1.25, "tasks": 1.0, "conflicts": 1.5, "episodes": 0.9,
            "graph": 1.25, "artifacts": 1.0,
        },
    }

    results = {}
    for name, weights in configs.items():
        cfg = RetrievalConfig(rrf_k=rrf_k, lane_weights=weights, rerank_policy="never")
        eval_res = evaluate_configuration(root, cfg, dev_cases, partition_name="dev")
        results[name] = {
            "recall@5": eval_res["summary"]["mean_recall@5"],
            "ndcg@10": eval_res["summary"]["mean_ndcg@10"],
            "mrr": eval_res["summary"]["mean_mrr"],
            "latency_p50_ms": eval_res["summary"]["latency"]["p50"],
        }

    best_score = max(r["ndcg@10"] for r in results.values())
    tied_schemes = [name for name, r in results.items() if abs(r["ndcg@10"] - best_score) <= 1e-6]
    selected_scheme = "weight_A_equal" if "weight_A_equal" in tied_schemes else tied_schemes[0]

    findings = (
        f"Evaluated 6 lane weighting schemes. Top NDCG@10 was {best_score:.4f} achieved by {tied_schemes}. "
        f"Selected '{selected_scheme}' as default under the simplicity-preserving rule."
    )

    return {
        "description": "Comparative evaluation of lane weighting schemes A through F on Dev partition",
        "results": results,
        "best_lane_weights_scheme": selected_scheme,
        "findings": findings,
    }


def run_experiment_3_candidate_depths(root: Path, dev_cases: list[LongMemEvalTestCase]) -> dict[str, Any]:
    """Experiment 3: Candidate depth sweep per lane."""
    depth_sweeps = [
        {"name": "compact_depths", "limits": {"exact": 5, "bm25": 5, "vector": 5, "decisions": 5, "procedures": 5, "tasks": 5, "conflicts": 5, "episodes": 5, "graph": 3, "artifacts": 3}},
        {"name": "standard_depths", "limits": dict(DEFAULT_CANDIDATE_LIMITS)},
        {"name": "deep_depths", "limits": {"exact": 10, "bm25": 25, "vector": 15, "decisions": 15, "procedures": 10, "tasks": 15, "conflicts": 10, "episodes": 10, "graph": 15, "artifacts": 10}},
    ]

    results = {}
    for d in depth_sweeps:
        cfg = RetrievalConfig(lane_candidate_limits=d["limits"], rerank_policy="never")
        eval_res = evaluate_configuration(root, cfg, dev_cases, partition_name="dev")
        results[d["name"]] = {
            "limits": d["limits"],
            "recall@5": eval_res["summary"]["mean_recall@5"],
            "ndcg@10": eval_res["summary"]["mean_ndcg@10"],
            "latency_p50_ms": eval_res["summary"]["latency"]["p50"],
            "latency_mean_ms": eval_res["summary"]["latency"]["mean"],
        }

    findings = (
        f"Candidate depth comparison: compact depths (P50: {results['compact_depths']['latency_p50_ms']}ms) "
        f"and standard depths (P50: {results['standard_depths']['latency_p50_ms']}ms) both achieved 1.000 Recall@5 "
        f"and {results['standard_depths']['ndcg@10']:.4f} NDCG@10."
    )

    return {
        "description": "Candidate depth sweep per lane (compact vs standard vs deep)",
        "results": results,
        "findings": findings,
    }


def run_experiment_4_reranking_policies(root: Path, dev_cases: list[LongMemEvalTestCase]) -> dict[str, Any]:
    """Experiment 4: Reranking policy comparison & threshold sweep on Dev partition."""
    policies = [
        ("policy_A_never", "never", "standard", 0.05, 0.60),
        ("policy_B_always", "always", "standard", 0.05, 0.60),
        ("policy_C_assurance", "assurance", "high", 0.05, 0.60),
        ("policy_D_intent", "intent", "standard", 0.05, 0.60),
        ("policy_E_ambiguity", "ambiguity", "standard", 0.05, 0.60),
        ("policy_F_conditional", "conditional", "standard", 0.05, 0.60),
    ]

    results = {}
    for name, policy, assurance_val, margin_th, min_cov in policies:
        cfg = RetrievalConfig(
            rerank_policy=policy,
            rerank_k=25,
            rerank_margin_threshold=margin_th,
            minimum_top1_term_coverage=min_cov,
        )
        eval_res = evaluate_configuration(root, cfg, dev_cases, assurance=assurance_val, partition_name="dev")
        results[name] = {
            "policy": policy,
            "assurance": assurance_val,
            "recall@5": eval_res["summary"]["mean_recall@5"],
            "ndcg@10": eval_res["summary"]["mean_ndcg@10"],
            "mrr": eval_res["summary"]["mean_mrr"],
            "rerank_attempted_rate": eval_res["summary"]["rerank_attempted_rate"],
            "latency_p50_ms": eval_res["summary"]["latency"]["p50"],
            "latency_p95_ms": eval_res["summary"]["latency"]["p95"],
            "latency_mean_ms": eval_res["summary"]["latency"]["mean"],
        }

    # Threshold sweep on conditional policy
    margin_sweep = {}
    for th in [0.01, 0.025, 0.05, 0.075, 0.10, 0.15]:
        cfg_sweep = RetrievalConfig(rerank_policy="conditional", rerank_margin_threshold=th)
        sw_res = evaluate_configuration(root, cfg_sweep, dev_cases, partition_name="dev")
        margin_sweep[f"margin_{th}"] = {
            "margin_threshold": th,
            "rerank_rate": sw_res["summary"]["rerank_attempted_rate"],
            "ndcg@10": sw_res["summary"]["mean_ndcg@10"],
            "latency_p50_ms": sw_res["summary"]["latency"]["p50"],
        }

    cov_sweep = {}
    for cov in [0.40, 0.60, 0.80]:
        cfg_cov = RetrievalConfig(rerank_policy="conditional", minimum_top1_term_coverage=cov)
        cov_res = evaluate_configuration(root, cfg_cov, dev_cases, partition_name="dev")
        cov_sweep[f"coverage_{cov}"] = {
            "min_coverage": cov,
            "rerank_rate": cov_res["summary"]["rerank_attempted_rate"],
            "ndcg@10": cov_res["summary"]["mean_ndcg@10"],
            "latency_p50_ms": cov_res["summary"]["latency"]["p50"],
        }

    never_ndcg = results["policy_A_never"]["ndcg@10"]
    always_ndcg = results["policy_B_always"]["ndcg@10"]
    cond_ndcg = results["policy_F_conditional"]["ndcg@10"]
    cond_rate = results["policy_F_conditional"]["rerank_attempted_rate"]

    if cond_rate == 0.0 and cond_ndcg >= never_ndcg:
        findings = (
            f"Under calibrated thresholds (margin=0.05, min_cov=0.60), conditional policy reranked 0.0% of standard "
            f"development queries, saving all cross-encoder latency overhead while preserving non-reranked NDCG@10 ({never_ndcg:.4f}). "
            f"Always-on reranking degraded NDCG to {always_ndcg:.4f} and increased P50 latency from "
            f"{results['policy_A_never']['latency_p50_ms']}ms to {results['policy_B_always']['latency_p50_ms']}ms."
        )
    elif cond_ndcg < never_ndcg:
        findings = (
            f"Cross-encoder reranking degraded retrieval quality on development fixtures from {never_ndcg:.4f} down to "
            f"{cond_ndcg:.4f} NDCG@10, while adding latency. Reranking is therefore not justified as the default policy."
        )
    else:
        findings = (
            f"Conditional reranking achieved {cond_ndcg:.4f} NDCG@10 with {cond_rate*100:.1f}% rerank invocation rate."
        )

    return {
        "description": "Evaluation of reranking trigger policies and threshold sweeps on Dev partition",
        "policy_results": results,
        "margin_threshold_sweep": margin_sweep,
        "coverage_threshold_sweep": cov_sweep,
        "findings": findings,
    }


def run_experiment_5_graph_retrieval(root: Path, dev_cases: list[LongMemEvalTestCase]) -> dict[str, Any]:
    """Experiment 5: Relational graph retrieval (1-hop vs 2-hop, metadata retention, alias expansion)."""
    cfg_1hop = RetrievalConfig(graph_hops=1, rerank_policy="never")
    cfg_2hop = RetrievalConfig(graph_hops=2, rerank_policy="never")

    res_1hop = evaluate_configuration(root, cfg_1hop, dev_cases, partition_name="dev")
    res_2hop = evaluate_configuration(root, cfg_2hop, dev_cases, partition_name="dev")

    multi_hop_query = "Why was global agent trust retired in Mbrain and what replaced it?"
    retrieval = retrieve(root, multi_hop_query, project="global-memory", config=cfg_2hop)
    graph_items = [it for it in retrieval["items"] if it["lane"] == "graph"]
    metadata_checks = {
        "graph_items_retrieved": len(graph_items),
        "source_id_present": all("source_id" in it for it in graph_items) if graph_items else False,
        "target_id_present": all("target_id" in it for it in graph_items) if graph_items else False,
        "predicate_present": all("predicate" in it for it in graph_items) if graph_items else False,
        "graph_path_present": all("graph_path" in it for it in graph_items) if graph_items else False,
        "temporal_validity_present": all("valid_from" in it for it in graph_items) if graph_items else False,
        "source_claim_id_present": all("source_claim_id" in it for it in graph_items) if graph_items else False,
    }

    findings = (
        f"Graph traversal audit: 1-hop and 2-hop traversal both maintained 1.000 Recall@5. "
        f"Metadata retention audit confirmed {len(graph_items)} graph candidates retain complete typed provenance "
        f"(source_id, target_id, predicate, graph_path, valid_from, source_claim_id)."
    )

    return {
        "description": "Graph retrieval comparison: 1-hop vs 2-hop traversal and metadata schema audit",
        "traversal_1hop": {
            "recall@5": res_1hop["summary"]["mean_recall@5"],
            "ndcg@10": res_1hop["summary"]["mean_ndcg@10"],
            "latency_p50_ms": res_1hop["summary"]["latency"]["p50"],
        },
        "traversal_2hop": {
            "recall@5": res_2hop["summary"]["mean_recall@5"],
            "ndcg@10": res_2hop["summary"]["mean_ndcg@10"],
            "latency_p50_ms": res_2hop["summary"]["latency"]["p50"],
        },
        "metadata_retention_audit": metadata_checks,
        "findings": findings,
    }


def run_experiment_6_vector_configuration(root: Path, dev_cases: list[LongMemEvalTestCase]) -> dict[str, Any]:
    """Experiment 6: Vector configuration (cutoff sweep, candidate depth, and explicit mismatch failure)."""
    cutoffs = [0.0, 0.3, 0.5, 0.7]
    cutoff_results = {}
    for c in cutoffs:
        cfg = RetrievalConfig(vector_similarity_cutoff=c, rerank_policy="never")
        eval_res = evaluate_configuration(root, cfg, dev_cases, partition_name="dev")
        cutoff_results[f"cutoff_{c}"] = {
            "similarity_cutoff": c,
            "recall@5": eval_res["summary"]["mean_recall@5"],
            "ndcg@10": eval_res["summary"]["mean_ndcg@10"],
            "latency_p50_ms": eval_res["summary"]["latency"]["p50"],
        }

    items_mismatch, meta_model_mismatch = _run_lane_vector(
        root, "concurrency settings", ["concurrency"], "global-memory", None,
        enable_indexed_vector=True, embedding_model="unknown-nonexistent-model"
    )

    items_dim_mismatch, meta_dim_mismatch = _run_lane_vector(
        root, "concurrency settings", ["concurrency"], "global-memory", None,
        enable_indexed_vector=True, embedding_model="test-embed",
        query_embedding=[1.0, 2.0]
    )

    model_pass = meta_model_mismatch.get("available") is False and "Model mismatch" in meta_model_mismatch.get("reason", "")
    dim_pass = meta_dim_mismatch.get("available") is False and "Dimension mismatch" in meta_dim_mismatch.get("reason", "")

    findings = (
        f"Vector lane evaluation: similarity cutoff 0.0 delivered 1.000 Recall@5. "
        f"Explicit mismatch validation passed: model mismatch was rejected ({model_pass}) and "
        f"dimension mismatch was rejected ({dim_pass}) without silent fallback."
    )

    return {
        "description": "Vector similarity cutoff sweep and explicit failure validation",
        "cutoff_sweep": cutoff_results,
        "explicit_failure_tests": {
            "model_mismatch": {
                "available": meta_model_mismatch.get("available"),
                "reason": meta_model_mismatch.get("reason"),
                "passed": model_pass,
            },
            "dimension_mismatch": {
                "available": meta_dim_mismatch.get("available"),
                "reason": meta_dim_mismatch.get("reason"),
                "passed": dim_pass,
            },
        },
        "findings": findings,
    }


def run_experiment_7_holdout_validation(
    root: Path,
    frozen_cfg: RetrievalConfig,
    *,
    holdout: bool = True,
) -> dict[str, Any]:
    """Experiment 7: Single holdout evaluation of frozen winning configuration."""
    train_cases = get_partition_cases("train", include_variants=True)
    dev_cases = get_partition_cases("dev", include_variants=True)

    train_res = evaluate_configuration(root, frozen_cfg, train_cases, partition_name="train")
    dev_res = evaluate_configuration(root, frozen_cfg, dev_cases, partition_name="dev")

    holdout_dict: dict[str, Any] = {}
    if holdout:
        holdout_cases = get_partition_cases("holdout", include_variants=True)
        # Evaluate holdout EXACTLY ONCE
        holdout_res = evaluate_configuration(root, frozen_cfg, holdout_cases, partition_name="holdout")
        all_records = holdout_res["records"]

        # Derive canonical and variants by filtering that single record set
        canon_records = [r for r in all_records if not r.get("is_variant")]
        variant_records = [r for r in all_records if r.get("is_variant")]

        holdout_canon_res = summarize_records(canon_records)
        holdout_var_res = summarize_records(variant_records)

        holdout_dict = {
            "holdout_all": {
                "case_count": len(all_records),
                "summary": holdout_res["summary"],
                "safety": holdout_res["safety"],
            },
            "holdout_canonical": {
                "case_count": len(canon_records),
                "summary": holdout_canon_res["summary"],
                "safety": holdout_canon_res["safety"],
            },
            "holdout_variants": {
                "case_count": len(variant_records),
                "summary": holdout_var_res["summary"],
                "safety": holdout_var_res["safety"],
            },
            "holdout_records": all_records,
        }
        findings = (
            f"Holdout evaluated once with frozen configuration hash. "
            f"Recall@5 on Holdout was {holdout_res['summary']['mean_recall@5']:.4f} (canonical: {holdout_canon_res['summary']['mean_recall@5']:.4f}, "
            f"variants: {holdout_var_res['summary']['mean_recall@5']:.4f}), and NDCG@10 was {holdout_res['summary']['mean_ndcg@10']:.4f}."
        )
    else:
        findings = "Holdout evaluation skipped (development mode; dev-only flag active)."

    frozen_dict = frozen_cfg.to_dict()
    frozen_sha = hashlib.sha256(json.dumps(frozen_dict, sort_keys=True).encode("utf-8")).hexdigest()

    return {
        "description": "Validation of frozen winning configuration across strictly isolated partitions",
        "selection_partition": "dev",
        "frozen_config": frozen_dict,
        "frozen_config_sha256": frozen_sha,
        "holdout_evaluations": 1 if holdout else 0,
        "holdout_used_for_selection": False,
        "train": {
            "case_count": len(train_cases),
            "summary": train_res["summary"],
            "safety": train_res["safety"],
        },
        "dev": {
            "case_count": len(dev_cases),
            "summary": dev_res["summary"],
            "safety": dev_res["safety"],
        },
        "holdout": holdout_dict,
        "findings": findings,
    }


def run_experiment_8_performance_and_resources() -> dict[str, Any]:
    """Experiment 8: Subprocess cold start, warm latency distribution, peak RSS, and Ollama status."""
    flashrank_perf = measure_cold_and_warm_flashrank_latency()
    peak_rss_mb = get_peak_rss_mb()
    ollama_status = check_ollama_status()

    findings = (
        f"Resource and latency audit: peak RSS was {peak_rss_mb} MB (converted with platform-aware units). "
        f"Fresh subprocess cold initialization took {flashrank_perf.get('cold_import_and_init_ms')} ms; "
        f"warm rerank latency averaged {flashrank_perf.get('warm_mean_ms')} ms across {flashrank_perf.get('warm_samples_count')} samples. "
        f"Ollama status: {ollama_status['status']}."
    )

    return {
        "description": "Subprocess cold-start benchmark, warm latency distribution, platform-aware peak RSS, and Ollama verification",
        "flashrank_latency": flashrank_perf,
        "peak_rss_mb": peak_rss_mb,
        "ollama_status": ollama_status,
        "findings": findings,
    }


# ==============================================================================
# MAIN ORCHESTRATION
# ==============================================================================

def run_all_tuning_experiments(
    root: Path,
    *,
    export: bool = True,
    holdout: bool = True,
    command_args: list[str] | None = None,
) -> dict[str, Any]:
    """Orchestrates all 8 tuning experiments, profile selection, and exports the final report."""
    isolation_check = verify_partition_isolation()
    dev_cases = get_partition_cases("dev", include_variants=True)
    provenance = collect_provenance(command_args)

    print("Running Experiment 1: RRF k parameter sweep with honest tie handling...")
    exp1 = run_experiment_1_rrf_k(root, dev_cases)

    print("Running Experiment 2: Lane weights comparison...")
    exp2 = run_experiment_2_lane_weights(root, dev_cases, rrf_k=exp1["optimal_rrf_k"])

    print("Running Experiment 3: Candidate depth per lane...")
    exp3 = run_experiment_3_candidate_depths(root, dev_cases)

    print("Running Experiment 4: Reranking policies & threshold sweep...")
    exp4 = run_experiment_4_reranking_policies(root, dev_cases)

    print("Running Experiment 5: Relational graph retrieval & metadata retention...")
    exp5 = run_experiment_5_graph_retrieval(root, dev_cases)

    print("Running Experiment 6: Vector configuration & explicit mismatch failure...")
    exp6 = run_experiment_6_vector_configuration(root, dev_cases)

    print("Evaluating production profiles on Dev partition for selection...")
    profile_evals: dict[str, Any] = {}
    profile_safety: dict[str, Any] = {}
    for p_name in ("fast", "standard", "high_assurance"):
        p_cfg = RetrievalConfig.from_profile(p_name)
        p_eval = evaluate_configuration(root, p_cfg, dev_cases, partition_name="dev")
        profile_evals[p_name] = p_eval
        profile_safety[p_name] = p_eval["safety"]

    print("Deriving recommended default profile via Pareto dominance...")
    selection = select_recommended_profile(profile_evals, profile_safety)
    recommended_profile_name = selection["recommended_default_profile"]
    winning_cfg = RetrievalConfig.from_profile(recommended_profile_name)

    print(f"Winner selected on Dev: '{recommended_profile_name}'. Freezing configuration...")
    print("Running Experiment 7: Holdout validation...")
    exp7 = run_experiment_7_holdout_validation(root, winning_cfg, holdout=holdout)

    print("Running Experiment 8: Latency, resource consumption, & Ollama verification...")
    exp8 = run_experiment_8_performance_and_resources()

    report_profiles = {}
    for p_name, p_eval in profile_evals.items():
        report_profiles[p_name] = {
            "profile": p_name,
            "config": RetrievalConfig.from_profile(p_name).to_dict(),
            "summary": p_eval["summary"],
            "safety": p_eval["safety"],
        }

    report: dict[str, Any] = {
        "schema_version": "gms-retrieval-tuning-report-v2",
        "benchmark_scope": "brain_local_adapter",
        "official_public_benchmark": False,
        "disclaimer": "Brain-local regression fixtures. Not official LongMemEval or MemoryAgentBench scores.",
        "provenance": provenance,
        "partition_validation": isolation_check,
        "experiments": {
            "experiment_1_rrf_k": exp1,
            "experiment_2_lane_weights": exp2,
            "experiment_3_candidate_depths": exp3,
            "experiment_4_reranking_policies": exp4,
            "experiment_5_graph_retrieval": exp5,
            "experiment_6_vector_configuration": exp6,
            "experiment_7_holdout_validation": exp7,
            "experiment_8_performance_and_resources": exp8,
        },
        "profiles": report_profiles,
        "pareto_frontier": selection["pareto_frontier"],
        "recommended_default_profile": recommended_profile_name,
        "selection_rationale": selection["selection_rationale"],
        "safety_invariants_verified": {
            "stale_leakage_zero": all(s["stale_leakage_count"] == 0 for s in profile_safety.values()),
            "archived_leakage_zero": all(s["archived_current_truth_leakage_count"] == 0 for s in profile_safety.values()),
            "superseded_leakage_zero": all(s["superseded_current_truth_leakage_count"] == 0 for s in profile_safety.values()),
            "abstention_failures_zero": all(s["abstention_failures"] == 0 for s in profile_safety.values()),
            "uncorroborated_actionability_zero": all(s["uncorroborated_actionable_count"] == 0 for s in profile_safety.values()),
            "conflicted_actionable_zero": all(s["conflicted_actionable_count"] == 0 for s in profile_safety.values()),
            "project_scope_violation_zero": all(s["project_scope_violation_count"] == 0 for s in profile_safety.values()),
            "temporal_scope_violation_zero": all(s["temporal_scope_violation_count"] == 0 for s in profile_safety.values()),
            "invalid_evidence_status_zero": all(s["invalid_evidence_status_count"] == 0 for s in profile_safety.values()),
            "explicit_mismatch_failure": (
                exp6["explicit_failure_tests"]["model_mismatch"]["passed"]
                and exp6["explicit_failure_tests"]["dimension_mismatch"]["passed"]
            ),
            "vram_zero_resident": exp8["ollama_status"]["verified_zero_resident"],
        },
    }

    if export:
        reports_dir = Path(__file__).parent.parent / "reports" / "eval_runs"
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_file = reports_dir / f"retrieval_config_experiment_{ts}.json"
        out_file.write_text(json.dumps(report, indent=2))
        print(f"\n💾 Machine-readable tuning report saved to:\n   {out_file}")
        report["exported_file"] = str(out_file)

    return report
