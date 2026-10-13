"""Reproducible benchmark reporting module and CLI for CCP.

Generates structured JSON benchmark reports for synthetic seeded robustness evaluations.
Captures system provenance (git commit, Python version, policy version), source/test manifests,
deterministic report identity hash, and per-seed/aggregate metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from research_harness.ccp.engine import CCPEngine
from research_harness.ccp.seeded_synthetic_robustness import run_multi_seed_robustness_benchmark


def get_git_status() -> tuple[str, bool]:
    """Retrieve git HEAD commit and working tree dirty flag."""
    head = "unknown"
    dirty = False
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        head = res.stdout.strip()
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        dirty = bool(res.stdout.strip())
    except Exception:
        pass

    return head, dirty


def get_git_commit() -> str:
    """Retrieve git HEAD commit if available."""
    head, _ = get_git_status()
    return head


def compute_file_sha256(path: Path) -> str:
    """Calculate SHA-256 digest of a single file."""
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def compute_source_manifest(repo_root: Optional[Path] = None) -> dict[str, Any]:
    """
    Computes a sorted file manifest and aggregate SHA-256 for research_harness/ccp/.
    Excludes byte-compiled and cache files.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    ccp_dir = repo_root / "research_harness" / "ccp"
    files_map: dict[str, str] = {}

    for p in ccp_dir.rglob("*"):
        if p.is_file() and not p.name.endswith(".pyc") and "__pycache__" not in p.parts:
            rel_path = str(p.relative_to(repo_root))
            files_map[rel_path] = compute_file_sha256(p)

    sorted_entries = sorted(files_map.items())
    raw_joined = "\n".join(f"{path}:{digest}" for path, digest in sorted_entries)
    agg_sha = hashlib.sha256(raw_joined.encode("utf-8")).hexdigest()

    return {
        "files": files_map,
        "aggregate_source_sha256": agg_sha,
    }


def compute_test_manifest(repo_root: Optional[Path] = None) -> dict[str, Any]:
    """
    Computes a test file manifest and aggregate SHA-256 for tests/test_ccp_harness.py.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    test_file = repo_root / "research_harness" / "tests" / "test_ccp_harness.py"
    files_map: dict[str, str] = {}
    if test_file.exists():
        rel_path = str(test_file.relative_to(repo_root))
        files_map[rel_path] = compute_file_sha256(test_file)

    sorted_entries = sorted(files_map.items())
    raw_joined = "\n".join(f"{path}:{digest}" for path, digest in sorted_entries)
    agg_sha = hashlib.sha256(raw_joined.encode("utf-8")).hexdigest()

    return {
        "files": files_map,
        "aggregate_test_sha256": agg_sha,
    }


def compute_report_identity_hash(
    policy_version: str,
    aggregate_source_sha256: str,
    aggregate_test_sha256: str,
    python_version: str,
    seeds: tuple[int, ...],
    scenarios_per_seed: int,
    aggregate_metrics: dict[str, Any],
) -> str:
    """
    Computes a deterministic identity hash covering code provenance, test suite provenance,
    runtime environment, evaluation seed configuration, and baseline aggregate metrics.
    Explicitly excludes non-deterministic execution timestamps and wall-clock latencies.
    """
    clean_agg: dict[str, Any] = {}
    for b_key in sorted(aggregate_metrics.keys()):
        metrics = dict(aggregate_metrics[b_key])
        clean_agg[b_key] = metrics

    canonical_metrics_json = json.dumps(clean_agg, sort_keys=True)
    seeds_str = ",".join(str(s) for s in sorted(seeds))

    payload = (
        f"POLICY={policy_version}|"
        f"SRC_AGG={aggregate_source_sha256}|"
        f"TEST_AGG={aggregate_test_sha256}|"
        f"PY={python_version}|"
        f"SEEDS={seeds_str}|"
        f"SCENARIOS={scenarios_per_seed}|"
        f"METRICS={canonical_metrics_json}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_robustness_report(
    seeds: tuple[int, ...] = (42, 123, 999), scenarios_per_seed: int = 26
) -> dict[str, Any]:
    """
    Run the deterministic multi-seed robustness evaluation and compile the standardized JSON report.
    This report is the canonical source of truth for CCP Phase 0 synthetic evaluation metrics.
    """
    bench_summary = run_multi_seed_robustness_benchmark(
        seeds=seeds, scenarios_per_seed=scenarios_per_seed
    )

    git_head, working_tree_dirty = get_git_status()
    now_iso = datetime.now(timezone.utc).isoformat()

    source_manifest = compute_source_manifest()
    test_manifest = compute_test_manifest()

    # Build per-metric aggregate stats (mean, min, max) for every metric
    metric_keys = [
        "promotion_precision",
        "promotion_recall",
        "false_promotion_rate",
        "false_rejection_rate",
        "privacy_violations",
        "source_laundering_attack_success",
        "echo_parrot_attack_success",
        "stale_leakage",
    ]

    baseline_keys = ["B0_AlwaysShare", "B1_StaticRegexDLP", "B2_DistinctAgentCount", "B3_CCPGate"]
    aggregate_metrics: dict[str, dict[str, Any]] = {}

    for b_key in baseline_keys:
        b_agg: dict[str, Any] = {}
        for m in metric_keys:
            vals = [bench_summary["per_seed_results"][s][b_key][m] for s in seeds]
            b_agg[m] = {
                "mean": round(sum(vals) / len(vals), 4),
                "min": min(vals),
                "max": max(vals),
            }
        # Add summary counts
        b_agg["total_false_positives"] = sum(bench_summary["per_seed_results"][s][b_key]["fp"] for s in seeds)
        b_agg["total_false_negatives"] = sum(bench_summary["per_seed_results"][s][b_key]["fn"] for s in seeds)
        b_agg["privacy_violations_sum"] = sum(bench_summary["per_seed_results"][s][b_key]["privacy_violations"] for s in seeds)
        b_agg["source_laundering_sum"] = sum(bench_summary["per_seed_results"][s][b_key]["source_laundering_attack_success"] for s in seeds)
        b_agg["echo_parrot_sum"] = sum(bench_summary["per_seed_results"][s][b_key]["echo_parrot_attack_success"] for s in seeds)
        b_agg["stale_leakage_sum"] = sum(bench_summary["per_seed_results"][s][b_key]["stale_leakage"] for s in seeds)
        aggregate_metrics[b_key] = b_agg

    py_version = sys.version.split()[0]
    report_identity_hash = compute_report_identity_hash(
        policy_version=CCPEngine.POLICY_VERSION,
        aggregate_source_sha256=source_manifest["aggregate_source_sha256"],
        aggregate_test_sha256=test_manifest["aggregate_test_sha256"],
        python_version=py_version,
        seeds=seeds,
        scenarios_per_seed=scenarios_per_seed,
        aggregate_metrics=aggregate_metrics,
    )

    report = {
        "report_title": "CCP Synthetic Seeded Robustness Evaluation Report",
        "evaluation_type": "synthetic_seeded_robustness_evaluation",
        "policy_version": CCPEngine.POLICY_VERSION,
        "python_version": py_version,
        "git_commit": git_head,
        "repository_head": git_head,
        "working_tree_dirty": working_tree_dirty,
        "report_identity_hash": report_identity_hash,
        "source_manifest": source_manifest,
        "test_manifest": test_manifest,
        "generated_at": now_iso,  # Audit metadata only
        "seeds": list(seeds),
        "scenario_count_per_seed": scenarios_per_seed,
        "total_scenarios_evaluated": len(seeds) * scenarios_per_seed,
        "per_seed_metrics": {str(s): bench_summary["per_seed_results"][s] for s in seeds},
        "aggregate_metrics": aggregate_metrics,
        "methodology_disclosures": {
            "evaluation_nature": "synthetic seeded robustness evaluation",
            "independent_status": "not held-out empirical validation",
            "limitation_statement": (
                "Current evaluation is synthetic and template-based. Metrics represent robustness under controlled perturbation rather than external empirical validation."
            ),
        },
        "limitations": [
            "Current evaluation is synthetic and template-based. Metrics represent robustness under controlled perturbation rather than external empirical validation.",
            "Synthetic scenarios are not real multi-agent team traces.",
            "Rule-based policy is not an empirical human adjudication model.",
            "In-memory SQLite does not model distributed consensus or network partitions.",
        ],
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CCP Synthetic Seeded Robustness Evaluation")
    parser.add_argument("--seeds", type=str, default="42,123,999", help="Comma-separated random seeds")
    parser.add_argument("--scenarios-per-seed", type=int, default=26, help="Scenario count per seed")
    parser.add_argument("--output", type=str, default=None, help="Optional output file path")
    args = parser.parse_args()

    seed_list = tuple(int(s.strip()) for s in args.seeds.split(",") if s.strip())
    report = generate_robustness_report(seeds=seed_list, scenarios_per_seed=args.scenarios_per_seed)

    formatted = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(formatted, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(formatted)


if __name__ == "__main__":
    main()
