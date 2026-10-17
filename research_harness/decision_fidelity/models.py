"""
models.py — Data contracts and schemas for Decision Fidelity Evaluation
========================================================================
Defines the data models for authoritative sources, source spans, constraint
taxonomies, reader tasks, simulator action contracts, and evaluation outcomes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ConstraintType(str, Enum):
    """The six core constraint categories evaluated in the decision fidelity study."""
    APPLICABILITY_SCOPE = "applicability_scope"
    EXCEPTIONS_AND_NEGATION = "exceptions_and_negation"
    QUANTITIES_AND_UNITS = "quantities_and_units"
    ORDERING_AND_PROCEDURES = "ordering_and_procedures"
    PREREQUISITES_REQUIRED_VS_OPTIONAL = "prerequisites_required_vs_optional"
    RATIONALE_ATTRIBUTION = "rationale_attribution"


class ActionOutcome(str, Enum):
    """Executable action evaluation outcomes classified by the domain simulator."""
    CORRECT_ACTION = "CORRECT_ACTION"
    WRONG_ACTION = "WRONG_ACTION"
    OMITTED_ACTION = "OMITTED_ACTION"
    EXCESSIVE_REFUSAL = "EXCESSIVE_REFUSAL"
    LEGITIMATE_ABSTENTION = "LEGITIMATE_ABSTENTION"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    SIMULATOR_ERROR = "SIMULATOR_ERROR"


@dataclass(frozen=True)
class SourceSpan:
    """An exact, immutable span within an authoritative source text."""
    span_id: str
    start_char: int
    end_char: int
    text: str


@dataclass(frozen=True)
class AuthoritativeConstraint:
    """An authoritative constraint rule extracted from the source text."""
    constraint_id: str
    constraint_type: ConstraintType
    statement: str
    support_span_ids: list[str]
    scope_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PublicSourceInput:
    """
    The public, unannotated input provided to writer agents and memory representations.
    Contains ONLY public metadata and raw source text.
    Contains ZERO hidden constraints, ZERO gold spans, and ZERO test answers.
    """
    source_id: str
    family_id: str
    variant_id: str
    content: str
    sha256: str


@dataclass(frozen=True)
class AuthoritativeSource:
    """An immutable authoritative source document."""
    source_id: str
    family_id: str
    variant_id: str  # e.g., 'canonical' or 'minimal_pair'
    content: str
    spans: dict[str, SourceSpan] = field(default_factory=dict)
    constraints: list[AuthoritativeConstraint] = field(default_factory=list)
    sha256: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "sha256", hashlib.sha256(self.content.encode("utf-8")).hexdigest())

    def to_public_input(self) -> PublicSourceInput:
        """Strips all hidden span annotations and constraint labels, returning only public source data."""
        return PublicSourceInput(
            source_id=self.source_id,
            family_id=self.family_id,
            variant_id=self.variant_id,
            content=self.content,
            sha256=self.sha256,
        )


@dataclass(frozen=True)
class DownstreamTask:
    """The public task presented to the reader agent."""
    task_id: str
    family_id: str
    variant_id: str
    prompt: str
    allowed_tool: str
    environment_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationResult:
    """The outcome of executing an agent action in a domain simulator."""
    outcome: ActionOutcome
    details: str
    state_before_hash: str
    state_after_hash: str
    executed_effects: dict[str, Any] = field(default_factory=dict)
    matched_alternative: Optional[str] = None


@dataclass
class EvaluationRecord:
    """Full provenance chain for a single evaluation trial."""
    family_id: str
    variant_id: str
    constraint_type: ConstraintType
    representation_arm: str
    source_id: str
    source_sha256: str
    task_id: str
    raw_memory_payload: str
    admitted_memory_payload: str
    admission_passed: bool
    admission_errors: list[str] = field(default_factory=list)
    raw_writer_response: Optional[str] = None
    raw_reader_output: str = ""
    parsed_action: Optional[dict[str, Any]] = None
    simulation_result: Optional[SimulationResult] = None
    constraint_failure_tags: list[str] = field(default_factory=list)
    unsupported_additions: list[str] = field(default_factory=list)
    omitted_constraints: list[str] = field(default_factory=list)
    is_diagnostic_oracle: bool = False
    estimated_prompt_tokens: int = 0
    estimated_completion_tokens: int = 0
