"""Benchmark runner and metrics calculator for CCP Phase 0.

Evaluates and compares B0, B1, B2, and B3 across the synthetic fixture corpus,
reporting separate security, privacy, and precision metrics without collapsing
them into a synthetic trust score.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

from research_harness.ccp.baselines import (
    BaselineB0AlwaysShare,
    BaselineB1StaticRegexDLP,
    BaselineB2DistinctAgentCount,
    BaselineB3CCPGate,
)
from research_harness.ccp.corpus import populate_synthetic_fixtures
from research_harness.ccp.engine import CCPEngine
from research_harness.ccp.models import PromotionAction
from research_harness.ccp.schema import init_temporary_ccp_db


def run_benchmark_for_baseline(baseline_name: str, baseline_instance: Any, scenarios: list[dict[str, Any]], engine: CCPEngine) -> dict[str, Any]:
    """Runs a single baseline against all fixture scenarios and collects metrics."""
    tp = 0
    fp = 0
    tn = 0
    fn = 0

    privacy_violations = 0
    source_laundering_success = 0
    echo_parrot_success = 0
    stale_leakage = 0
    latencies_ms: list[float] = []

    promoted_count = 0
    total_cases = len(scenarios)

    for sc in scenarios:
        cand = sc["candidate"]
        gt_promotable = sc["ground_truth_promotable"]

        t0 = time.perf_counter()
        action = baseline_instance.evaluate(cand)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        is_promoted = action in (
            PromotionAction.SHARE_VERBATIM,
            PromotionAction.SHARE_REDACTED,
            PromotionAction.SHARE_AGGREGATE,
        )

        if is_promoted:
            promoted_count += 1
            # Check projection text for privacy leakage
            if action == PromotionAction.SHARE_VERBATIM:
                proj_text = cand.statement
            elif action == PromotionAction.SHARE_REDACTED:
                proj_text, _ = engine.redact_statement(cand.statement)
            elif action == PromotionAction.SHARE_AGGREGATE:
                proj_text = engine.aggregate_statement(cand.statement, cand.memory_key)
            else:
                proj_text = cand.statement

            # Privacy violation: does proj_text contain raw synthetic secrets or local paths?
            has_secret = bool(engine.SECRET_REGEX.search(proj_text))
            has_path = bool(engine.LOCAL_PATH_REGEX.search(proj_text))
            if has_secret or has_path:
                privacy_violations += 1

            if sc.get("category") == "source_laundering_attack":
                source_laundering_success += 1
            if sc.get("category") == "echo_chamber_attack":
                echo_parrot_success += 1
            if sc.get("category") == "stale_leakage":
                stale_leakage += 1

            if gt_promotable:
                tp += 1
            else:
                fp += 1
        else:
            if not gt_promotable:
                tn += 1
            else:
                fn += 1

    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    fpr = round(fp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    fnr = round(fn / (tp + fn), 4) if (tp + fn) > 0 else 0.0

    latencies_sorted = sorted(latencies_ms)
    p50_lat = round(statistics.median(latencies_sorted), 3) if latencies_sorted else 0.0
    p95_idx = int(len(latencies_sorted) * 0.95)
    p95_lat = round(latencies_sorted[min(p95_idx, len(latencies_sorted) - 1)], 3) if latencies_sorted else 0.0

    return {
        "baseline": baseline_name,
        "total_cases": total_cases,
        "promoted_count": promoted_count,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "promotion_precision": precision,
        "promotion_recall": recall,
        "false_promotion_rate": fpr,
        "false_rejection_rate": fnr,
        "privacy_violations": privacy_violations,
        "source_laundering_attack_success": source_laundering_success,
        "echo_parrot_attack_success": echo_parrot_success,
        "stale_leakage": stale_leakage,
        "token_cost": 0,
        "latency_p50_ms": p50_lat,
        "latency_p95_ms": p95_lat,
    }


def run_full_ccp_evaluation() -> dict[str, Any]:
    """Execute comparative benchmark across B0, B1, B2, and B3 on fresh isolated DB."""
    conn = init_temporary_ccp_db()
    engine = CCPEngine(conn)
    scenarios = populate_synthetic_fixtures(engine)

    b0 = BaselineB0AlwaysShare(engine)
    b1 = BaselineB1StaticRegexDLP(engine)
    b2 = BaselineB2DistinctAgentCount(engine)
    b3 = BaselineB3CCPGate(engine)

    results = {
        "B0_AlwaysShare": run_benchmark_for_baseline("B0_AlwaysShare", b0, scenarios, engine),
        "B1_StaticRegexDLP": run_benchmark_for_baseline("B1_StaticRegexDLP", b1, scenarios, engine),
        "B2_DistinctAgentCount": run_benchmark_for_baseline("B2_DistinctAgentCount", b2, scenarios, engine),
        "B3_CCPGate": run_benchmark_for_baseline("B3_CCPGate", b3, scenarios, engine),
    }

    # Test projection invalidation completeness on scenario 10
    scen_10 = next(s for s in scenarios if s["scenario_id"] == "scen_10_contest_reversal")
    receipt_10 = engine.evaluate_promotion(scen_10["candidate"])
    proj_10 = engine.apply_projection(scen_10["candidate"], receipt_10)
    assert proj_10 is not None

    rev_event = engine.contest_projection(
        proj_10.projection_id,
        contested_by="synthetic_owner",
        rationale="Python 3.9 deprecation policy was erroneous; 3.13 is standard",
    )
    active_after = engine.query_active_projections(scen_10["candidate"].target_scope)
    is_in_active = any(p.projection_id == proj_10.projection_id for p in active_after)

    invalidation_completeness = 1.0 if not is_in_active else 0.0
    contest_burden = 1 / max(1, results["B3_CCPGate"]["promoted_count"])

    results["B3_CCPGate"]["projection_invalidation_completeness"] = invalidation_completeness
    results["B3_CCPGate"]["contest_burden"] = round(contest_burden, 4)

    conn.close()
    return results


def format_benchmark_table(results: dict[str, Any]) -> str:
    """Format results into a markdown comparative summary table."""
    header = (
        "| Metric | B0: Always Share | B1: Static Regex DLP | B2: Distinct Agent Count | B3: CCP Gate (Proposed) |\n"
        "| :--- | :---: | :---: | :---: | :---: |"
    )
    rows = [
        header,
        f"| **Promotion Precision** | {results['B0_AlwaysShare']['promotion_precision']*100:.1f}% | {results['B1_StaticRegexDLP']['promotion_precision']*100:.1f}% | {results['B2_DistinctAgentCount']['promotion_precision']*100:.1f}% | **{results['B3_CCPGate']['promotion_precision']*100:.1f}%** |",
        f"| **Promotion Recall** | {results['B0_AlwaysShare']['promotion_recall']*100:.1f}% | {results['B1_StaticRegexDLP']['promotion_recall']*100:.1f}% | {results['B2_DistinctAgentCount']['promotion_recall']*100:.1f}% | **{results['B3_CCPGate']['promotion_recall']*100:.1f}%** |",
        f"| **False Promotion Rate** | {results['B0_AlwaysShare']['false_promotion_rate']*100:.1f}% | {results['B1_StaticRegexDLP']['false_promotion_rate']*100:.1f}% | {results['B2_DistinctAgentCount']['false_promotion_rate']*100:.1f}% | **{results['B3_CCPGate']['false_promotion_rate']*100:.1f}%** |",
        f"| **False Rejection Rate** | {results['B0_AlwaysShare']['false_rejection_rate']*100:.1f}% | {results['B1_StaticRegexDLP']['false_rejection_rate']*100:.1f}% | {results['B2_DistinctAgentCount']['false_rejection_rate']*100:.1f}% | **{results['B3_CCPGate']['false_rejection_rate']*100:.1f}%** |",
        f"| **Privacy / Disclosure Violations** | {results['B0_AlwaysShare']['privacy_violations']} | {results['B1_StaticRegexDLP']['privacy_violations']} | {results['B2_DistinctAgentCount']['privacy_violations']} | **{results['B3_CCPGate']['privacy_violations']}** |",
        f"| **Source Laundering Success** | {results['B0_AlwaysShare']['source_laundering_attack_success']} | {results['B1_StaticRegexDLP']['source_laundering_attack_success']} | {results['B2_DistinctAgentCount']['source_laundering_attack_success']} | **{results['B3_CCPGate']['source_laundering_attack_success']}** |",
        f"| **Echo / Parrot Loop Success** | {results['B0_AlwaysShare']['echo_parrot_attack_success']} | {results['B1_StaticRegexDLP']['echo_parrot_attack_success']} | {results['B2_DistinctAgentCount']['echo_parrot_attack_success']} | **{results['B3_CCPGate']['echo_parrot_attack_success']}** |",
        f"| **Stale / Expired Leakage** | {results['B0_AlwaysShare']['stale_leakage']} | {results['B1_StaticRegexDLP']['stale_leakage']} | {results['B2_DistinctAgentCount']['stale_leakage']} | **{results['B3_CCPGate']['stale_leakage']}** |",
        f"| **Invalidation Completeness** | N/A | N/A | N/A | **{results['B3_CCPGate']['projection_invalidation_completeness']*100:.1f}%** |",
        f"| **Decision Latency (P50)** | {results['B0_AlwaysShare']['latency_p50_ms']} ms | {results['B1_StaticRegexDLP']['latency_p50_ms']} ms | {results['B2_DistinctAgentCount']['latency_p50_ms']} ms | {results['B3_CCPGate']['latency_p50_ms']} ms |",
        f"| **Decision Latency (P95)** | {results['B0_AlwaysShare']['latency_p95_ms']} ms | {results['B1_StaticRegexDLP']['latency_p95_ms']} ms | {results['B2_DistinctAgentCount']['latency_p95_ms']} ms | {results['B3_CCPGate']['latency_p95_ms']} ms |",
        f"| **Compute Token Cost** | 0 | 0 | 0 | 0 |",
    ]
    return "\n".join(rows)
