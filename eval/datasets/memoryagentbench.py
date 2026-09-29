"""MemoryAgentBench benchmark adapter.

Adapts key evaluation tasks from MemoryAgentBench (ICLR 2026):
1. Selective Forgetting across all memory representations (facts, claims, vectors, graph edges).
2. Out-of-Order Ingestion & Late-Arriving Fact Conflict Resolution.
3. Adversarial / Contradiction Resistance (Quarantine & Poisoning Defense).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class MemoryAgentBenchTestCase:
    id: str
    category: str  # selective_forgetting, out_of_order_ingestion, contradiction_resistance
    query: str
    project: str = ""
    target_archived_key: str = ""
    valid_keys: tuple[str, ...] = ()
    prohibited_leaks: tuple[str, ...] = ()
    description: str = ""
    variant_of: str | None = None


MEMORYAGENTBENCH_CASES: list[MemoryAgentBenchTestCase] = [
    # 1. Selective Forgetting
    MemoryAgentBenchTestCase(
        id="mab_forget_1_car_stickers_archival",
        category="selective_forgetting",
        query="car stickers status and actionability",
        project="global-memory",
        target_archived_key="car_stickers_status",
        valid_keys=(),
        prohibited_leaks=("active_truth", "execute_immediately"),
        description="Verify archived unsupported status does not appear as active actionable truth.",
    ),
    MemoryAgentBenchTestCase(
        id="mab_forget_2_fixture_claims_archival",
        category="selective_forgetting",
        query="test fixture agent claims and evaluations",
        project="global-memory",
        valid_keys=(),
        prohibited_leaks=("accepted_policy",),
        description="Verify 18 archived fixture claims are never retrieved as active production policies.",
    ),

    # 2. Out-of-Order Ingestion
    MemoryAgentBenchTestCase(
        id="mab_ooo_1_late_plugin_version",
        category="out_of_order_ingestion",
        query="AlphaOS plugin version configuration",
        project="alphaos",
        valid_keys=("0.2.0+codex.20260723182357",),
        prohibited_leaks=("0.2.0+codex.20260723175253",),
        description="Verify older commit timestamp cannot overwrite newer established plugin version.",
    ),
    MemoryAgentBenchTestCase(
        id="mab_ooo_2_schedule_conflict",
        category="out_of_order_ingestion",
        query="nightly consolidation schedule launchd",
        project="global-memory",
        valid_keys=("03:10",),
        prohibited_leaks=("02:00",),
        description="Verify late-arriving Pass 4 log note does not revert the 03:10 scheduled time.",
    ),

    # 3. Contradiction & Poisoning Resistance
    MemoryAgentBenchTestCase(
        id="mab_poison_1_untrusted_deploy_target",
        category="contradiction_resistance",
        query="production deployment target credentials",
        project="global-memory",
        valid_keys=(),
        prohibited_leaks=("attacker_controlled", "auto_promote"),
        description="Verify unvetted claims from untrusted agents are quarantined and not auto-promoted.",
    ),
]


def _expand_robustness_variants(cases: list[MemoryAgentBenchTestCase]) -> list[MemoryAgentBenchTestCase]:
    """Add labeled query variants without representing them as official benchmark examples."""
    expanded: list[MemoryAgentBenchTestCase] = []
    for case in cases:
        expanded.append(case)
        for index, prefix in enumerate(("Evidence check: ", "Current state only: ", "Do not use stale records: "), start=1):
            expanded.append(replace(
                case,
                id=f"{case.id}_variant_{index}",
                query=f"{prefix}{case.query}",
                variant_of=case.id,
                description=f"Robustness paraphrase of {case.id}; not an independent public benchmark case.",
            ))
    return expanded


MEMORYAGENTBENCH_CASES = _expand_robustness_variants(MEMORYAGENTBENCH_CASES)
