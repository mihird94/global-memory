"""Typed records and domain models for the CCP Phase 0 experiment harness.

Strictly fictionalized, append-only, and temporally safe.
"""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


class ScopeTier(str, enum.Enum):
    PRIVATE = "private"
    TASK = "task"
    PROJECT = "project"
    TEAM = "team"
    ORGANIZATION = "organization"

    @property
    def rank(self) -> int:
        ranks = {
            ScopeTier.PRIVATE: 0,
            ScopeTier.TASK: 1,
            ScopeTier.PROJECT: 2,
            ScopeTier.TEAM: 3,
            ScopeTier.ORGANIZATION: 4,
        }
        return ranks[self]

    def __lt__(self, other: ScopeTier) -> bool:
        if not isinstance(other, ScopeTier):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: ScopeTier) -> bool:
        if not isinstance(other, ScopeTier):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: ScopeTier) -> bool:
        if not isinstance(other, ScopeTier):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: ScopeTier) -> bool:
        if not isinstance(other, ScopeTier):
            return NotImplemented
        return self.rank >= other.rank


class PromotionAction(str, enum.Enum):
    RETAIN_PRIVATE = "retain_private"
    SHARE_VERBATIM = "share_verbatim"
    SHARE_REDACTED = "share_redacted"
    SHARE_AGGREGATE = "share_aggregate"
    REQUEST_CORROBORATION = "request_corroboration"
    REJECT_PROMOTION = "reject_promotion"


class NodeType(str, enum.Enum):
    VERIFIED_SYSTEM = "verified_system"
    OWNER_INSTRUCTION = "owner_instruction"
    RAW_TOOL_EXEC = "raw_tool_exec"
    AGENT_OBSERVATION = "agent_observation"
    LLM_INFERENCE = "llm_inference"
    ARTIFACT_WRITE = "artifact_write"
    ARTIFACT_READ = "artifact_read"
    UNVERIFIABLE = "unverifiable"


class EdgeRelation(str, enum.Enum):
    SUPPORTS_CLAIM = "supports_claim"
    DERIVED_FROM = "derived_from"
    READ_FROM = "read_from"
    COPIED_FROM = "copied_from"
    PARAPHRASED_FROM = "paraphrased_from"
    CORROBORATES = "corroborates"
    CONTRADICTS = "contradicts"


@dataclass
class ArtifactIdentity:
    """Identity and provenance metadata for file/data artifacts."""
    artifact_id: str
    uri: str
    content_digest: str
    origin_author: str
    write_lineage_node_id: Optional[str] = None
    is_ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactIdentity:
        return cls(**data)


@dataclass
class EvidenceNode:
    """Node in the causal provenance DAG representing an event or claim generation."""
    node_id: str
    node_type: NodeType
    agent_id: str
    session_id: str
    statement: str
    source_ref: str
    payload_hash: str
    created_at: str
    is_authoritative: bool = False
    artifact: Optional[ArtifactIdentity] = None
    supported_claim_key: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["node_type"] = self.node_type.value
        d["artifact"] = self.artifact.to_dict() if self.artifact else None
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceNode:
        d = dict(data)
        d["node_type"] = NodeType(d["node_type"])
        if d.get("artifact"):
            d["artifact"] = ArtifactIdentity.from_dict(d["artifact"])
        return cls(**d)


@dataclass
class EvidenceEdge:
    """Directed dependency edge parent -> child."""
    edge_id: str
    parent_node_id: str
    child_node_id: str
    relation_type: EdgeRelation
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["relation_type"] = self.relation_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceEdge:
        d = dict(data)
        d["relation_type"] = EdgeRelation(d["relation_type"])
        return cls(**d)


@dataclass
class EvidenceRoot:
    """Normalized terminal root in the causal provenance graph."""
    root_id: str
    root_type: NodeType
    origin_agent_id: str
    source_ref: str
    payload_hash: str
    is_authoritative: bool = False
    is_tainted: bool = False
    taint_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["root_type"] = self.root_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceRoot:
        d = dict(data)
        d["root_type"] = NodeType(d["root_type"])
        return cls(**d)


@dataclass
class PromotionCandidate:
    """Incoming memory candidate proposed for scope promotion."""
    candidate_id: str
    memory_key: str
    statement: str
    source_scope: ScopeTier
    target_scope: ScopeTier
    authority: str
    effective_at: str
    evidence_node_ids: list[str]
    expires_at: Optional[str] = None
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.content_hash:
            raw = f"{self.memory_key}:{self.statement}:{self.effective_at}"
            self.content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_scope"] = self.source_scope.value
        d["target_scope"] = self.target_scope.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromotionCandidate:
        d = dict(data)
        d["source_scope"] = ScopeTier(d["source_scope"])
        d["target_scope"] = ScopeTier(d["target_scope"])
        return cls(**d)


@dataclass
class ProjectionDerivation:
    """Explicit projection derivation edge parent_projection -> child_projection."""
    derivation_id: str
    parent_projection_id: str
    child_projection_id: str
    derivation_type: str  # e.g., "summary", "aggregate", "scope_escalation"
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectionDerivation:
        return cls(**data)


@dataclass
class ScopeProjection:
    """
    Projected, versioned view of a memory in a target scope.
    Uses append-only temporal validity: active when valid_from <= as_of and
    (invalidated_at is None or invalidated_at > as_of).
    """
    projection_id: str
    candidate_id: str
    memory_key: str
    projected_statement: str
    source_scope: ScopeTier
    target_scope: ScopeTier
    action: PromotionAction
    transform_used: str  # "verbatim", "redacted", "aggregate", "none"
    evidence_root_ids: list[str]
    effective_at: str
    valid_from: str
    content_hash: str
    revision_hash: str
    created_at: str  # Audit metadata
    invalidated_at: Optional[str] = None
    expires_at: Optional[str] = None
    invalidation_reason: Optional[str] = None
    parent_projection_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.invalidated_at is None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_scope"] = self.source_scope.value
        d["target_scope"] = self.target_scope.value
        d["action"] = self.action.value
        d["is_active"] = self.is_active
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScopeProjection:
        d = dict(data)
        d.pop("is_active", None)
        d["source_scope"] = ScopeTier(d["source_scope"])
        d["target_scope"] = ScopeTier(d["target_scope"])
        d["action"] = PromotionAction(d["action"])
        return cls(**d)


@dataclass
class PromotionReceipt:
    """
    Deterministic audit receipt for a promotion evaluation.
    semantic_decision_hash excludes observation wall-clock time and covers:
    canonical candidate, policy version, target scope, evidence graph digest, and decision output.
    """
    receipt_id: str
    candidate_id: str
    memory_key: str
    policy_version: str
    source_scope: ScopeTier
    target_scope: ScopeTier
    decision_action: PromotionAction
    deterministic_rationale: str
    disclosure_transform: str
    evidence_roots: list[EvidenceRoot]
    independent_lineage_count: int
    is_authoritative_root: bool
    is_tainted: bool
    evidence_graph_digest: str
    semantic_decision_hash: str
    created_at: str  # Audit timestamp only

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_scope"] = self.source_scope.value
        d["target_scope"] = self.target_scope.value
        d["decision_action"] = self.decision_action.value
        d["evidence_roots"] = [r.to_dict() for r in self.evidence_roots]
        return d


@dataclass
class ContestEvent:
    """Append-only audit record of a user or agent contesting a projection."""
    contest_id: str
    projection_id: str
    candidate_id: str
    contested_by: str
    rationale: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReversalEvent:
    """Append-only audit record of atomic rollback / invalidation."""
    reversal_id: str
    contest_id: str
    primary_projection_id: str
    invalidated_projection_ids: list[str]
    reverted_at: str
    audit_trail_preserved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectionValidityEvent:
    """
    Append-only temporal validity event for a ScopeProjection.
    Projections are never mutated; validity is derived from the event stream as of query time.
    """
    event_id: str
    projection_id: str
    event_type: str  # "activate" | "invalidate"
    effective_at: str
    actor: str
    rationale: str
    contest_id: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectionValidityEvent:
        return cls(**data)
