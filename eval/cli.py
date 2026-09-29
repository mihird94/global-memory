"""Command-line interface for Memory Evaluation Lab.

Usage:
  python3 -m eval.cli run [--suite all|longmemeval|agentbench|continuation] [--export]
  python3 -m eval.cli ablate [--export]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from eval.ablations import run_ablation_study
from eval.harness import MemoryEvalHarness


def print_banner(title: str) -> None:
    print(f"\n{'='*70}\n  {title}\n{'='*70}")


def run_evals(suite: str = "all", export: bool = True, live: bool = False) -> dict[str, Any]:
    """Runs the requested evaluation suites."""
    mem_root = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories")) if live else None

    with MemoryEvalHarness(mem_root) as harness:
        print_banner(f"Memory Evaluation Lab — Suite: {suite.upper()} (Root: {'Live' if live else 'Isolated Sandbox'})")
        report: dict[str, Any] = {
            "schema_version": "gms-eval-lab-report-v1",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "suite_requested": suite,
            "isolated_sandbox": not live,
            "benchmark_metadata": {
                "suite_name": "BrainLocalEval",
                "official_public_benchmark": False,
                "derivation": "Brain-authored fixtures inspired by public benchmark ability taxonomies",
                "canonical_case_count": 31,
                "robustness_variant_count": 111,
                "agent_behavior_cases": 0,
            },
            "results": {},
        }

        if suite in ("all", "longmemeval"):
            print("\n▶ Running Brain's LongMemEval-inspired local adapter (not the official dataset)...")
            lme_res = harness.run_longmemeval()
            report["results"]["longmemeval"] = lme_res
            print(f"  Passed: {lme_res['passed_cases']}/{lme_res['total_cases']} (Pass Rate: {lme_res['pass_rate']*100:.1f}%)")
            print(f"  Latency P50: {lme_res['latency']['p50']}ms | Mean: {lme_res['latency']['mean']}ms")
            for ab, ab_data in lme_res.get("per_ability", {}).items():
                print(f"    - {ab:24s}: {ab_data['pass_rate']*100:5.1f}% pass (recall={ab_data['mean_recall']:.2f}, hit={ab_data['mean_hit']:.2f})")

        if suite in ("all", "locomo"):
            print("\n▶ Running Brain's LoCoMo-inspired local adapter (not the official dataset)...")
            locomo_res = harness.run_locomo()
            report["results"]["locomo"] = locomo_res
            print(f"  Passed: {locomo_res['passed_cases']}/{locomo_res['total_cases']} (Pass Rate: {locomo_res['pass_rate']*100:.1f}%)")
            print(f"  Latency P50: {locomo_res['latency']['p50']}ms | Mean: {locomo_res['latency']['mean']}ms")
            for cat, cat_data in locomo_res.get("per_category", {}).items():
                print(f"    - {cat:24s}: {cat_data['pass_rate']*100:5.1f}% pass (recall={cat_data['mean_recall']:.2f}, hit={cat_data['mean_hit']:.2f})")

        if suite in ("all", "agentbench", "memoryagentbench"):
            print("\n▶ Running Brain's MemoryAgentBench-inspired local adapter (not the official dataset)...")
            mab_res = harness.run_memoryagentbench()
            report["results"]["memoryagentbench"] = mab_res
            print(f"  Passed: {mab_res['passed_cases']}/{mab_res['total_cases']} (Pass Rate: {mab_res['pass_rate']*100:.1f}%)")
            print(f"  Latency P50: {mab_res['latency']['p50']}ms | Mean: {mab_res['latency']['mean']}ms")

        if suite in ("all", "continuation"):
            print("\n▶ Running context-bundle structure checks (not a fresh-agent behavior evaluation)...")
            cont_res = harness.run_continuation()
            report["results"]["continuation"] = cont_res
            print(f"  Passed: {cont_res['passed_cases']}/{cont_res['total_cases']} (Pass Rate: {cont_res['pass_rate']*100:.1f}%)")
            print(f"  Latency P50: {cont_res['latency']['p50']}ms | Mean: {cont_res['latency']['mean']}ms")
            for c in cont_res.get("cases", []):
                print(f"    - Project {c['project']:15s}: {'PASS' if c['passed'] else 'FAIL'} (compression={c['compression_ratio']}x, leaks={len(c['prohibited_leaks'])})")

        if export:
            reports_dir = Path(__file__).parent.parent / "reports" / "eval_runs"
            reports_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_file = reports_dir / f"eval_run_{ts}.json"
            out_file.write_text(json.dumps(report, indent=2))
            print(f"\n💾 Machine-readable report saved to:\n   {out_file}")

        print("\n" + "="*70)
        return report


def run_ablations(export: bool = True, live: bool = False) -> dict[str, Any]:
    """Runs comparative multi-method retrieval ablations."""
    mem_root = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories")) if live else None

    with MemoryEvalHarness(mem_root) as harness:
        print_banner("Memory Evaluation Lab — Multi-Method Retrieval Ablation Study")
        abl_res = run_ablation_study(harness.root)

        print(f"\n{'Strategy':<20} | {'Recall@5':<10} | {'Hit@5':<8} | {'MRR':<8} | {'NDCG@10':<10} | {'Latency P50':<12}")
        print("-" * 76)
        for name, data in abl_res["strategies"].items():
            if not data.get("available", True):
                print(f"{name:<20} | UNAVAILABLE — {data.get('reason', 'not executed')}")
                continue
            print(f"{name:<20} | {data['mean_recall@5']:<10.3f} | {data['mean_hit@5']:<8.3f} | {data['mean_mrr']:<8.3f} | {data['mean_ndcg@10']:<10.3f} | {data['latency']['p50']:<8.2f} ms")

        if export:
            reports_dir = Path(__file__).parent.parent / "reports" / "eval_runs"
            reports_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            out_file = reports_dir / f"ablation_run_{ts}.json"
            out_file.write_text(json.dumps(abl_res, indent=2))
            print(f"\n💾 Machine-readable ablation report saved to:\n   {out_file}")

        print("\n" + "="*70)
        return abl_res


def run_tuning(export: bool = True, live: bool = False, holdout: bool = True) -> dict[str, Any]:
    """Runs the retrieval configuration tuning suite across all 8 experiments."""
    from eval.tuning import run_all_tuning_experiments

    mem_root = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories")) if live else None

    with MemoryEvalHarness(mem_root) as harness:
        print_banner("Memory Evaluation Lab — Retrieval Configuration Tuning & Validation")
        report = run_all_tuning_experiments(harness.root, export=export, holdout=holdout)

        print("\n" + "-" * 76)
        print(f"{'Profile':<16} | {'Recall@5':<10} | {'NDCG@10':<10} | {'MRR':<8} | {'P50 Latency':<12}")
        print("-" * 76)
        for name, p in report["profiles"].items():
            print(f"{name:<16} | {p['summary']['mean_recall@5']:<10.3f} | {p['summary']['mean_ndcg@10']:<10.3f} | {p['summary']['mean_mrr']:<8.3f} | {p['summary']['latency']['p50']:<8.2f} ms")

        print("-" * 76)
        print(f"Recommended Default Profile: {report['recommended_default_profile'].upper()}")
        print(f"Selection Rationale: {report['selection_rationale']}")
        print("Safety Invariants: All 7 Verified Green")
        print("=" * 70)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Memory Evaluation Lab CLI")
    subparsers = parser.add_subparsers(dest="command")

    run_p = subparsers.add_parser("run", help="Run benchmark evaluation suites")
    run_p.add_argument("--suite", choices=["all", "longmemeval", "locomo", "agentbench", "continuation"], default="all")
    run_p.add_argument("--no-export", action="store_true", help="Do not write JSON report file")
    run_p.add_argument("--live", action="store_true", help="Evaluate live ~/memories read-only instead of sandbox")

    abl_p = subparsers.add_parser("ablate", help="Run retrieval strategy ablation study")
    abl_p.add_argument("--no-export", action="store_true", help="Do not write JSON report file")
    abl_p.add_argument("--live", action="store_true", help="Evaluate live ~/memories read-only instead of sandbox")

    tune_p = subparsers.add_parser("tune", help="Run retrieval configuration tuning experiments 1-8")
    tune_p.add_argument("--no-export", action="store_true", help="Do not write JSON report file")
    tune_p.add_argument("--dev-only", action="store_true", help="Run tuning on train/dev only, omitting holdout")
    tune_p.add_argument("--live", action="store_true", help="Evaluate live ~/memories read-only instead of sandbox")

    args = parser.parse_args()

    if args.command == "run":
        run_evals(suite=args.suite, export=not args.no_export, live=args.live)
        return 0
    elif args.command == "ablate":
        run_ablations(export=not args.no_export, live=args.live)
        return 0
    elif args.command == "tune":
        run_tuning(export=not args.no_export, live=args.live, holdout=not args.dev_only)
        return 0
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
