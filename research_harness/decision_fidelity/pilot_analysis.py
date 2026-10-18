#!/usr/bin/env python3
"""Analyze COMPLETE frozen Decision Fidelity development-pilot runs.

Unit of inference is independent SOURCE FAMILY (six clusters), not two
related source variants or the 72 Ollama calls. No confirmatory claims.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ARMS = (
    "Arm_A_Full_Source", "Arm_B_Extractive_Excerpts",
    "Arm_C_Ordinary_Structured", "Arm_D_Source_Bound",
)


def paired_family_deltas(rows: list[dict], treatment: str, baseline: str) -> dict[str, float]:
    by_cell = {}
    for row in rows:
        if row.get("stage") != "reader":
            continue
        if row.get("status") != "COMPLETED" or not isinstance(row.get("correct"), bool):
            raise ValueError("Incomplete/invalid reader row")
        key = (row["family_id"], row["variant_id"], row["arm_id"])
        if key in by_cell:
            raise ValueError("Duplicate reader cell")
        by_cell[key] = int(row["correct"])
    families = sorted({key[0] for key in by_cell})
    result = {}
    for family in families:
        deltas = []
        for variant in ("canonical", "minimal_pair"):
            t = (family, variant, treatment)
            b = (family, variant, baseline)
            if t not in by_cell or b not in by_cell:
                raise ValueError(f"Missing matched comparison {family}/{variant}")
            deltas.append(by_cell[t] - by_cell[b])
        result[family] = sum(deltas) / 2
    return result


def exact_sign_flip(values: list[float], alternative: str = "greater") -> float:
    if not values or alternative not in ("greater", "two-sided"):
        raise ValueError("Invalid exact sign-flip inputs")
    observed = sum(values)
    null = [sum(a * b for a, b in zip(values, signs))
            for signs in itertools.product((-1, 1), repeat=len(values))]
    if alternative == "greater":
        extreme = sum(x >= observed - 1e-12 for x in null)
    else:
        extreme = sum(abs(x) >= abs(observed) - 1e-12 for x in null)
    return extreme / len(null)


def cluster_bootstrap_ci(values: list[float], *, iterations: int = 5000, seed: int = 1742):
    if not values:
        raise ValueError("Empty bootstrap")
    rng = random.Random(seed)
    n = len(values)
    estimates = sorted(sum(rng.choice(values) for _ in range(n)) / n
                       for _ in range(iterations))
    return [estimates[int(0.025 * (iterations - 1))],
            estimates[int(0.975 * (iterations - 1))]]


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    items = sorted(p_values.items(), key=lambda x: x[1])
    count = len(items)
    corrected = {}
    running = 0.0
    for i, (name, value) in enumerate(items):
        running = max(running, min(1.0, value * (count - i)))
        corrected[name] = running
    return corrected


def analyze(run_dir: Path) -> dict:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if (summary.get("status") != "COMPLETED" or
            summary.get("completed_calls") != 72 or
            summary.get("completed_reader_calls") != 48):
        raise ValueError("Incomplete/failed pilot: no paired efficacy statistics")
    rows = [json.loads(line) for line in
            (run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if len(rows) != 72 or sorted(r.get("call_index") for r in rows) != list(range(1, 73)):
        raise ValueError("Missing, duplicated or unexpected frozen call indices")
    if any(r.get("status") != "COMPLETED" for r in rows):
        raise ValueError("Partially completed trace")
    readers = [row for row in rows if row.get("stage") == "reader"]
    if len(readers) != 48:
        raise ValueError("Expected 48 readers")
    seen = set()
    for row in readers:
        cell = (row["family_id"], row["variant_id"], row["arm_id"])
        if cell in seen or row["arm_id"] not in ARMS:
            raise ValueError("Duplicate or unknown reader cell")
        seen.add(cell)
    descriptives = {}
    for arm in ARMS:
        arm_rows = [r for r in readers if r["arm_id"] == arm]
        if len(arm_rows) != 12 or any(not isinstance(r.get("correct"), bool) for r in arm_rows):
            raise ValueError("Incomplete/unscored arm")
        prompt_tokens = sum(r.get("prompt_eval_count") or 0 for r in rows if r["arm_id"] == arm)
        completion_tokens = sum(r.get("eval_count") or 0 for r in rows if r["arm_id"] == arm)
        correct = sum(r["correct"] for r in arm_rows)
        descriptives[arm] = {
            "n": 12, "correct": correct, "accuracy": correct / 12,
            "outcomes": dict(Counter(r["outcome"] for r in arm_rows)),
            "writer_plus_reader_prompt_tokens": prompt_tokens,
            "writer_plus_reader_completion_tokens": completion_tokens,
        }
    comparisons = {
        "D_vs_C": (ARMS[3], ARMS[2]),
        "D_vs_A": (ARMS[3], ARMS[0]),
        "D_vs_B": (ARMS[3], ARMS[1]),
    }
    estimates, raw_p = {}, {}
    for label, (t, b) in comparisons.items():
        deltas = paired_family_deltas(readers, t, b)
        if len(deltas) != 6:
            raise ValueError("Expected exactly six independent family clusters")
        vals = list(deltas.values())
        raw_p[label] = exact_sign_flip(vals, "greater")
        estimates[label] = {
            "difference_treatment_minus_baseline": sum(vals) / 6,
            "cluster_count": 6, "per_family_delta": deltas,
            "exploratory_bootstrap_ci95": cluster_bootstrap_ci(vals),
            "exploratory_one_sided_exact_p": raw_p[label],
            "exploratory_two_sided_exact_p": exact_sign_flip(vals, "two-sided"),
        }
    adjusted = holm_adjust(raw_p)
    for key in estimates:
        estimates[key]["exploratory_holm_adjusted_p"] = adjusted[key]
    return {
        "status": "DESCRIPTIVE_DEVELOPMENT_PILOT_ONLY",
        "warnings": [
            "No paper-level claims from six authored source families.",
            "Correlated minimal pairs are NOT independent samples.",
            "Exact sign-flip and cluster bootstrap are exploratory.",
            "A five-percentage-point non-inferiority/equivalence claim is NOT tested.",
            "Potential paired-family exchangeability assumptions have not been established.",
            "Actual local-model behavior may vary between machines and seeds.",
        ],
        "descriptives": descriptives, "paired_comparisons": estimates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Complete local model-pilot run directory")
    args = parser.parse_args()
    try:
        report = analyze(args.run_dir)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Analysis blocked: {exc}\n")
    (args.run_dir / "pilot_analysis.json").write_text(
        json.dumps(report, sort_keys=True, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
