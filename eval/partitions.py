"""LongMemEval case partitioning for training, dev, and holdout evaluation.

Enforces strict zero-leakage partitioning:
- Train: 6 canonicals (30 total cases with variants)
- Dev: 3 canonicals (15 total cases with variants)
- Holdout: 3 canonicals (15 total cases with variants)
Variants belong exclusively to their canonical parent's partition and never cross boundaries.
"""
from __future__ import annotations

from typing import Any

from eval.datasets.longmemeval import LONGMEMEVAL_CASES, LongMemEvalTestCase

PARTITION_CANONICAL_IDS: dict[str, tuple[str, ...]] = {
    "train": (
        "lme_fact_1_sqlite_concurrency",
        "lme_fact_2_dream_cycle_schedule",
        "lme_multi_1_agent_trust_retirement",
        "lme_temp_1_historical_context",
        "lme_update_1_alphaos_plugin_version",
        "lme_abstain_1_unknown_cryptocurrency",
    ),
    "dev": (
        "lme_fact_3_tailscale_ip",
        "lme_temp_2_pass3_milestone",
        "lme_abstain_2_unrecorded_flight_number",
    ),
    "holdout": (
        "lme_multi_2_alphaos_sizing",
        "lme_update_2_dream_cycle_schedule_update",
        "lme_abstain_3_opaque_status_actionability",
    ),
}


def get_partition_for_case_id(case_id: str) -> str:
    """Returns the partition ('train', 'dev', 'holdout') for a given case or variant ID."""
    base_id = case_id
    if "_variant_" in case_id:
        base_id = case_id.split("_variant_")[0]

    for part, ids in PARTITION_CANONICAL_IDS.items():
        if base_id in ids:
            return part
    raise KeyError(f"Case ID '{case_id}' (base: '{base_id}') not found in any partition.")


def get_partition_cases(partition: str, include_variants: bool = True) -> list[LongMemEvalTestCase]:
    """Retrieves all test cases for a given partition."""
    part = partition.lower().strip()
    if part not in PARTITION_CANONICAL_IDS:
        raise ValueError(f"Unknown partition '{partition}'. Must be one of: 'train', 'dev', 'holdout'.")
    canonical_ids = set(PARTITION_CANONICAL_IDS[part])

    selected = []
    for c in LONGMEMEVAL_CASES:
        base_id = c.variant_of if c.variant_of is not None else c.id
        if base_id in canonical_ids:
            if c.variant_of is None or include_variants:
                selected.append(c)
    return selected


def verify_partition_isolation() -> dict[str, Any]:
    """Strictly validates zero-leakage partition boundaries across canonicals and variants."""
    train_canon = set(PARTITION_CANONICAL_IDS["train"])
    dev_canon = set(PARTITION_CANONICAL_IDS["dev"])
    holdout_canon = set(PARTITION_CANONICAL_IDS["holdout"])

    # 1. Check pairwise disjointness of canonical IDs
    overlap_td = train_canon & dev_canon
    overlap_th = train_canon & holdout_canon
    overlap_dh = dev_canon & holdout_canon
    if overlap_td or overlap_th or overlap_dh:
        raise AssertionError(f"Partition canonical overlap detected: td={overlap_td}, th={overlap_th}, dh={overlap_dh}")

    # 2. Check that all 12 canonicals from LONGMEMEVAL_CASES are covered
    all_canon = {c.id for c in LONGMEMEVAL_CASES if c.variant_of is None}
    partitioned_canon = train_canon | dev_canon | holdout_canon
    if all_canon != partitioned_canon:
        diff = all_canon ^ partitioned_canon
        raise AssertionError(f"Partition canonicals do not match LONGMEMEVAL_CASES canonicals. Diff: {diff}")

    # 3. Check variant assignment invariance
    counts = {"train": 0, "dev": 0, "holdout": 0}
    for c in LONGMEMEVAL_CASES:
        p = get_partition_for_case_id(c.id)
        counts[p] += 1
        if c.variant_of is not None:
            parent_p = get_partition_for_case_id(c.variant_of)
            if p != parent_p:
                raise AssertionError(f"Variant {c.id} partition {p} != parent {c.variant_of} partition {parent_p}")

    return {
        "isolated": True,
        "canonical_counts": {k: len(v) for k, v in PARTITION_CANONICAL_IDS.items()},
        "total_case_counts": counts,
    }
