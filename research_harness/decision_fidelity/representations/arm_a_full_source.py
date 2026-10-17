"""
arm_a_full_source.py — Arm A: Full Authoritative Source Baseline
================================================================
Presents the entire authoritative source document directly to the reader agent.
Acts as the uncompressed reference baseline.
"""

from __future__ import annotations

from typing import Union
from research_harness.decision_fidelity.models import AuthoritativeSource, DownstreamTask, PublicSourceInput
from research_harness.decision_fidelity.representations.base import BaseMemoryRepresentation


class ArmAFullSource(BaseMemoryRepresentation):
    """Arm A: Presents the complete, unmodified source text."""

    def __init__(self):
        super().__init__(
            arm_id="Arm_A_Full_Source",
            description="Complete uncompressed authoritative source document",
        )

    def build_reader_context(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> str:
        pub = self._ensure_public_input(source)
        return (
            f"=== AUTHORITATIVE SOURCE DOCUMENT (ID: {pub.source_id}) ===\n"
            f"{pub.content.strip()}\n"
            f"============================================================"
        )

    def estimate_token_cost(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> dict[str, int]:
        pub = self._ensure_public_input(source)
        content_tokens = max(1, len(pub.content) // 4)
        task_tokens = max(1, len(task.prompt) // 4)
        return {
            "ingestion_tokens": 0,  # Zero offline extraction step
            "memory_carrier_tokens": content_tokens,
            "reader_prompt_tokens": content_tokens + task_tokens,
        }
