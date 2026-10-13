"""DEPRECATED: Use research_harness.ccp.seeded_synthetic_robustness instead.

This module is retained for backward compatibility with existing callers.
Claims of held-out validation are deprecated: these scenarios represent
synthetic seeded robustness evaluations, not empirical held-out data.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "research_harness.ccp.held_out is deprecated; import from research_harness.ccp.seeded_synthetic_robustness instead.",
    DeprecationWarning,
    stacklevel=2,
)

from research_harness.ccp.seeded_synthetic_robustness import (
    generate_held_out_scenarios,
    generate_synthetic_robustness_scenarios,
    run_multi_seed_held_out_benchmark,
    run_multi_seed_robustness_benchmark,
)

__all__ = [
    "generate_held_out_scenarios",
    "generate_synthetic_robustness_scenarios",
    "run_multi_seed_held_out_benchmark",
    "run_multi_seed_robustness_benchmark",
]
