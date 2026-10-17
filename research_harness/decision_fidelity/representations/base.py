"""
base.py — Common Reader-Facing Representation Interface
========================================================
Defines the abstract interface for all four memory representations:
  - Arm A: Full Authoritative Source
  - Arm B: Extractive Source Excerpts
  - Arm C: Ordinary Structured LLM Memory
  - Arm D: Source-Bound Constraint Memory

All public representation arms consume PublicSourceInput (or AuthoritativeSource.to_public_input()).
Under no circumstances may public representations inspect hidden source.constraints or gold labels.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Union
from research_harness.decision_fidelity.models import AuthoritativeSource, DownstreamTask, PublicSourceInput


class BaseMemoryRepresentation(ABC):
    """Abstract base class for memory representations presented to the reader agent."""

    def __init__(self, arm_id: str, description: str, is_diagnostic_oracle: bool = False):
        self.arm_id = arm_id
        self.description = description
        self.is_diagnostic_oracle = is_diagnostic_oracle

    def _ensure_public_input(self, source: Union[AuthoritativeSource, PublicSourceInput]) -> PublicSourceInput:
        """Coerces any input source to a stripped PublicSourceInput without hidden annotations."""
        if isinstance(source, PublicSourceInput):
            return source
        if hasattr(source, "to_public_input"):
            return source.to_public_input()
        raise TypeError(f"Expected AuthoritativeSource or PublicSourceInput, got {type(source)}")

    @abstractmethod
    def build_reader_context(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> str:
        """
        Builds the memory payload text exposed in the reader prompt.
        Must NOT expose hidden labels, gold actions, or ungrounded metadata.
        """
        pass

    def admit_memory(
        self,
        source: Union[AuthoritativeSource, PublicSourceInput],
        task: Optional[DownstreamTask] = None,
    ) -> tuple[bool, str, list[str]]:
        """
        Admission gate for the representation.
        Returns:
            (admission_passed, admitted_payload, admission_errors)
        """
        # Default implementation: pass-through reader context
        payload = self.build_reader_context(source, task) if task else ""
        return True, payload, []

    @abstractmethod
    def estimate_token_cost(self, source: Union[AuthoritativeSource, PublicSourceInput], task: DownstreamTask) -> dict[str, int]:
        """
        Estimates the full pipeline token cost:
          - 'ingestion_tokens': tokens processed during writer/extraction phase
          - 'memory_carrier_tokens': size of the persisted representation passed to reader
          - 'reader_prompt_tokens': tokens from public task instructions and admitted context
        """
        pass
