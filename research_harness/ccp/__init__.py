"""Common-Cause-Aware Contestable Promotion (CCP) Research Harness.

Phase 0 shadow-mode research package for evaluating multi-tier memory gating,
causal provenance independence, and contestable projections.
"""

from research_harness.ccp.models import (
    PromotionCandidate,
    EvidenceNode,
    EvidenceEdge,
    EvidenceRoot,
    ScopeProjection,
    PromotionReceipt,
    ContestEvent,
    ReversalEvent,
    ProjectionValidityEvent,
    ScopeTier,
    PromotionAction,
)
from research_harness.ccp.engine import CCPEngine
from research_harness.ccp.schema import init_temporary_ccp_db
from research_harness.ccp.seeded_synthetic_robustness import (
    generate_synthetic_robustness_scenarios,
    run_multi_seed_robustness_benchmark,
)

__all__ = [
    "PromotionCandidate",
    "EvidenceNode",
    "EvidenceEdge",
    "EvidenceRoot",
    "ScopeProjection",
    "PromotionReceipt",
    "ContestEvent",
    "ReversalEvent",
    "ProjectionValidityEvent",
    "ScopeTier",
    "PromotionAction",
    "CCPEngine",
    "init_temporary_ccp_db",
    "generate_synthetic_robustness_scenarios",
    "run_multi_seed_robustness_benchmark",
]
