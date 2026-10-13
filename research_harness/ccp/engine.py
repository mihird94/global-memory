"""Core decision engine for Common-Cause-Aware Contestable Promotion (CCP).

Evaluates candidate promotion across scope tiers, traverses causal provenance
DAGs to detect common-cause echoes and source laundering, enforces authoritative
exceptions, generates sanitized projections with zero-leakage transforms, and manages
contest rollbacks with atomic transitive derivation invalidation and append-only temporal validity.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from research_harness.ccp.models import (
    ArtifactIdentity,
    ContestEvent,
    EdgeRelation,
    EvidenceEdge,
    EvidenceNode,
    EvidenceRoot,
    NodeType,
    ProjectionDerivation,
    ProjectionValidityEvent,
    PromotionAction,
    PromotionCandidate,
    PromotionReceipt,
    ReversalEvent,
    ScopeProjection,
    ScopeTier,
)


class CCPEngine:
    """Hermetic decision engine for CCP Phase 0."""

    POLICY_VERSION = "ccp-p0-v1"

    # Regex patterns for synthetic tokens and sensitive material
    SECRET_REGEX = re.compile(
        r"(?:sk-[a-zA-Z0-9_\-\.]{12,}|token:[a-zA-Z0-9_\-\.]{8,}|bearer\s+[a-zA-Z0-9_\-\.]{12,}|password\s*=\s*['\"][^'\"]+['\"])",
        re.IGNORECASE,
    )
    LOCAL_PATH_REGEX = re.compile(
        r"/(?:Users|home)/[a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\./]+",
    )

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ──────────────────────────────────────────────────────────────────────────
    # Ingestion & Graph Management (Append-Only, Cycle-Safe)
    # ──────────────────────────────────────────────────────────────────────────

    def record_evidence_node(self, node: EvidenceNode) -> None:
        """Insert an evidence node in the causal graph. Fails on duplicate ID."""
        artifact_json = json.dumps(node.artifact.to_dict()) if node.artifact else None
        try:
            self.conn.execute(
                """
                INSERT INTO ccp_evidence_nodes
                (node_id, node_type, agent_id, session_id, statement, source_ref, payload_hash, created_at, is_authoritative, artifact_json, supported_claim_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.node_id,
                    node.node_type.value,
                    node.agent_id,
                    node.session_id,
                    node.statement,
                    node.source_ref,
                    node.payload_hash,
                    node.created_at,
                    1 if node.is_authoritative else 0,
                    artifact_json,
                    node.supported_claim_key,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Cannot record duplicate evidence node: {node.node_id}") from e

    def _path_exists(self, start_id: str, target_id: str, visited: Optional[set[str]] = None) -> bool:
        """Check if a directed path exists from start_id to target_id."""
        if start_id == target_id:
            return True
        if visited is None:
            visited = set()
        visited.add(start_id)

        rows = self.conn.execute(
            "SELECT child_node_id FROM ccp_evidence_edges WHERE parent_node_id = ?",
            (start_id,),
        ).fetchall()
        for r in rows:
            nxt = r["child_node_id"]
            if nxt not in visited:
                if self._path_exists(nxt, target_id, visited):
                    return True
        return False

    def _path_exists_in_derivations(
        self, start_id: str, target_id: str, visited: Optional[set[str]] = None, cursor: Optional[sqlite3.Cursor] = None
    ) -> bool:
        """Check if a directed derivation path exists from start_id to target_id."""
        if start_id == target_id:
            return True
        if visited is None:
            visited = set()
        visited.add(start_id)

        cur = cursor or self.conn
        rows = cur.execute(
            "SELECT child_projection_id FROM ccp_projection_derivations WHERE parent_projection_id = ?",
            (start_id,),
        ).fetchall()
        for r in rows:
            nxt = r["child_projection_id"]
            if nxt not in visited:
                if self._path_exists_in_derivations(nxt, target_id, visited, cursor=cursor):
                    return True
        return False

    def record_evidence_edge(self, edge: EvidenceEdge) -> None:
        """Insert a causal dependency edge parent -> child. Enforces cycle prevention."""
        if edge.parent_node_id == edge.child_node_id:
            raise ValueError(f"Cycle detected: self-loop on node {edge.parent_node_id}")

        # If a path already exists from child to parent, adding parent -> child creates a cycle
        if self._path_exists(edge.child_node_id, edge.parent_node_id):
            raise ValueError(
                f"Cycle detected in evidence graph: path already exists from {edge.child_node_id} to {edge.parent_node_id}"
            )

        try:
            self.conn.execute(
                """
                INSERT INTO ccp_evidence_edges
                (edge_id, parent_node_id, child_node_id, relation_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    edge.edge_id,
                    edge.parent_node_id,
                    edge.child_node_id,
                    edge.relation_type.value,
                    edge.created_at,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Cannot record duplicate evidence edge: {edge.edge_id}") from e

    def record_candidate(self, candidate: PromotionCandidate) -> None:
        """Store an incoming candidate for scope promotion. Fails on duplicate ID."""
        try:
            self.conn.execute(
                """
                INSERT INTO ccp_promotion_candidates
                (candidate_id, memory_key, statement, source_scope, target_scope, authority, effective_at, expires_at, content_hash, evidence_node_ids, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.memory_key,
                    candidate.statement,
                    candidate.source_scope.value,
                    candidate.target_scope.value,
                    candidate.authority,
                    candidate.effective_at,
                    candidate.expires_at,
                    candidate.content_hash,
                    json.dumps(candidate.evidence_node_ids),
                    json.dumps(candidate.metadata),
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Cannot record duplicate candidate: {candidate.candidate_id}") from e

    # ──────────────────────────────────────────────────────────────────────────
    # Provenance Graph Traversal & Lineage Analysis
    # ──────────────────────────────────────────────────────────────────────────

    def _get_node(self, node_id: str) -> Optional[EvidenceNode]:
        row = self.conn.execute(
            "SELECT * FROM ccp_evidence_nodes WHERE node_id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        artifact = None
        if "artifact_json" in row.keys() and row["artifact_json"]:
            artifact = ArtifactIdentity.from_dict(json.loads(row["artifact_json"]))
        supp_key = row["supported_claim_key"] if "supported_claim_key" in row.keys() else None
        return EvidenceNode(
            node_id=row["node_id"],
            node_type=NodeType(row["node_type"]),
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            statement=row["statement"],
            source_ref=row["source_ref"],
            payload_hash=row["payload_hash"],
            created_at=row["created_at"],
            is_authoritative=bool(row["is_authoritative"]),
            artifact=artifact,
            supported_claim_key=supp_key,
        )

    def _get_parent_edges(self, child_node_id: str) -> list[EvidenceEdge]:
        rows = self.conn.execute(
            "SELECT * FROM ccp_evidence_edges WHERE child_node_id = ?",
            (child_node_id,),
        ).fetchall()
        return [
            EvidenceEdge(
                edge_id=r["edge_id"],
                parent_node_id=r["parent_node_id"],
                child_node_id=r["child_node_id"],
                relation_type=EdgeRelation(r["relation_type"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def trace_lineage(
        self, start_node_ids: list[str], target_candidate: Optional[PromotionCandidate] = None
    ) -> dict[str, Any]:
        """
        Traverse the DAG backwards from start_node_ids to extract roots and
        detect common-cause correlations, echo chains, source laundering, contradictions,
        and unsupported claim mismatches.
        """
        visited_nodes: set[str] = set()
        ancestor_nodes: list[EvidenceNode] = []
        roots_map: dict[str, EvidenceRoot] = {}

        has_llm_inference_echo = False
        has_echo_chain = False
        has_laundered_artifact = False
        is_missing_lineage = False
        has_authoritative_contradiction = False
        unsupported_claim_nodes: list[str] = []

        if not start_node_ids:
            return {
                "roots": [],
                "ancestors": [],
                "is_authoritative": False,
                "independent_lineage_count": 0,
                "is_tainted": True,
                "taint_reasons": ["No supporting evidence nodes provided (missing lineage)"],
                "is_missing_lineage": True,
                "has_llm_echo": False,
                "has_laundered": False,
                "has_contradiction": False,
            }

        # Check start nodes against target candidate claim
        valid_start_nodes: list[str] = []
        for s_id in start_node_ids:
            s_node = self._get_node(s_id)
            if s_node is None:
                is_missing_lineage = True
                continue
            if target_candidate and s_node.supported_claim_key and s_node.supported_claim_key != target_candidate.memory_key:
                unsupported_claim_nodes.append(s_id)
            else:
                valid_start_nodes.append(s_id)

        queue = list(valid_start_nodes)
        while queue:
            curr_id = queue.pop(0)
            if curr_id in visited_nodes:
                continue
            visited_nodes.add(curr_id)

            node = self._get_node(curr_id)
            if node is None:
                is_missing_lineage = True
                continue

            ancestor_nodes.append(node)
            parent_edges = self._get_parent_edges(curr_id)

            # Check for contradiction edge
            for pe in parent_edges:
                if pe.relation_type == EdgeRelation.CONTRADICTS:
                    p_node = self._get_node(pe.parent_node_id)
                    if p_node and (p_node.is_authoritative or p_node.node_type in (NodeType.VERIFIED_SYSTEM, NodeType.OWNER_INSTRUCTION)):
                        has_authoritative_contradiction = True

            # Check for source laundering on artifact read
            if node.node_type == NodeType.ARTIFACT_READ:
                if node.artifact and (node.artifact.is_ambiguous or not node.artifact.write_lineage_node_id):
                    has_laundered_artifact = True
                elif not parent_edges:
                    has_laundered_artifact = True
                else:
                    for pe in parent_edges:
                        p_node = self._get_node(pe.parent_node_id)
                        if p_node and p_node.node_type in (NodeType.LLM_INFERENCE, NodeType.UNVERIFIABLE):
                            has_laundered_artifact = True

            # If node has no parents, it is an evidentiary root
            if not parent_edges:
                is_auth = node.is_authoritative or node.node_type in (
                    NodeType.VERIFIED_SYSTEM,
                    NodeType.OWNER_INSTRUCTION,
                )
                is_tainted_root = node.node_type in (NodeType.LLM_INFERENCE, NodeType.UNVERIFIABLE)
                taint_msg = "Root is ungrounded LLM inference" if is_tainted_root else None

                if is_tainted_root and has_echo_chain:
                    has_llm_inference_echo = True

                roots_map[node.node_id] = EvidenceRoot(
                    root_id=node.node_id,
                    root_type=node.node_type,
                    origin_agent_id=node.agent_id,
                    source_ref=node.source_ref,
                    payload_hash=node.payload_hash,
                    is_authoritative=is_auth,
                    is_tainted=is_tainted_root,
                    taint_reason=taint_msg,
                )
            else:
                for pe in parent_edges:
                    if pe.relation_type in (EdgeRelation.COPIED_FROM, EdgeRelation.PARAPHRASED_FROM):
                        has_echo_chain = True
                    queue.append(pe.parent_node_id)

        all_roots = sorted(roots_map.values(), key=lambda r: r.root_id)
        authoritative_roots = [r for r in all_roots if r.is_authoritative]
        is_authoritative = len(authoritative_roots) > 0

        distinct_lineage_keys = {
            f"{r.source_ref}:{r.payload_hash}"
            for r in all_roots
            if not r.is_tainted and r.root_type != NodeType.LLM_INFERENCE
        }
        independent_lineage_count = len(distinct_lineage_keys)

        has_artifact_read = any(n.node_type == NodeType.ARTIFACT_READ for n in ancestor_nodes)
        has_llm_root = any(r.root_type in (NodeType.LLM_INFERENCE, NodeType.UNVERIFIABLE) for r in all_roots)
        has_llm_inference_echo = (has_echo_chain and has_llm_root) or (has_llm_root and len(ancestor_nodes) > 1)

        if has_artifact_read and has_llm_root:
            has_laundered_artifact = True

        for n in ancestor_nodes:
            if n.node_type == NodeType.ARTIFACT_READ:
                p_edges = self._get_parent_edges(n.node_id)
                if not p_edges:
                    has_laundered_artifact = True

        taint_reasons = []
        if has_authoritative_contradiction:
            taint_reasons.append("Contradicted by authoritative verified source")
        if has_llm_inference_echo:
            taint_reasons.append("Ancestry contains ungrounded LLM inference echo/paraphrase chain")
        if has_laundered_artifact:
            taint_reasons.append("Detected agent-written artifact source laundering without verified write lineage")
        if is_missing_lineage:
            taint_reasons.append("Missing or unresolvable ancestor evidence nodes")
        if unsupported_claim_nodes:
            target_key = target_candidate.memory_key if target_candidate else "target"
            taint_reasons.append(
                f"Evidence nodes {unsupported_claim_nodes} do not support candidate claim '{target_key}'"
            )

        is_tainted = bool(taint_reasons)

        return {
            "roots": all_roots,
            "ancestors": ancestor_nodes,
            "is_authoritative": is_authoritative,
            "independent_lineage_count": independent_lineage_count,
            "is_tainted": is_tainted,
            "taint_reasons": taint_reasons,
            "is_missing_lineage": is_missing_lineage,
            "has_llm_echo": has_llm_inference_echo,
            "has_laundered": has_laundered_artifact,
            "has_contradiction": has_authoritative_contradiction,
            "unsupported_claim_nodes": unsupported_claim_nodes,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Sanitization & Disclosure Transforms (Zero-Leakage)
    # ──────────────────────────────────────────────────────────────────────────

    def redact_statement(self, text: str) -> tuple[str, bool]:
        """Redact synthetic secrets and local paths, returning (clean_text, was_redacted)."""
        was_redacted = False
        clean = text

        if self.SECRET_REGEX.search(clean):
            clean = self.SECRET_REGEX.sub("[REDACTED_SECRET]", clean)
            was_redacted = True

        if self.LOCAL_PATH_REGEX.search(clean):
            clean = self.LOCAL_PATH_REGEX.sub("~/[path]", clean)
            was_redacted = True

        return clean, was_redacted

    def _redact_value(self, val: Any) -> Any:
        if isinstance(val, str):
            clean_v, _ = self.redact_statement(val)
            return clean_v
        elif isinstance(val, dict):
            return self.redact_metadata(val)
        elif isinstance(val, list):
            return [self._redact_value(item) for item in val]
        return val

    def redact_metadata(self, meta: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact secrets and local paths across dictionary/list metadata."""
        sanitized = {}
        for k, v in meta.items():
            sanitized[k] = self._redact_value(v)
        return sanitized

    def aggregate_statement(self, text: str, memory_key: str) -> str:
        """
        Abstract individual operational traces into general structured rule.
        Strips local paths, specific usernames, transient session IDs, and raw counts.
        """
        clean, _ = self.redact_statement(text)
        clean = re.sub(r"\b(?:sess|session|task|agent|node)_[a-zA-Z0-9_\-]+", "[session]", clean)
        clean = re.sub(r"/\S+", "[path]", clean)
        domain = memory_key.split(".")[0].upper()
        return f"[ARCHITECTURAL_POLICY:{domain}] Standard Rule ({memory_key}): {clean}"

    # ──────────────────────────────────────────────────────────────────────────
    # Promotion Decision Engine
    # ──────────────────────────────────────────────────────────────────────────

    def evaluate_promotion(
        self, candidate: PromotionCandidate, current_time: Optional[str] = None
    ) -> PromotionReceipt:
        """
        Evaluate candidate against scope boundaries, common-cause taint,
        and authoritative exceptions to produce a deterministic PromotionReceipt.
        """
        now_iso = current_time or datetime.now(timezone.utc).isoformat()
        lineage = self.trace_lineage(candidate.evidence_node_ids, target_candidate=candidate)

        roots = lineage["roots"]
        is_auth = lineage["is_authoritative"]
        indep_count = lineage["independent_lineage_count"]
        is_tainted = lineage["is_tainted"]
        taint_reasons = lineage["taint_reasons"]
        is_missing_lineage = lineage["is_missing_lineage"]
        has_contradiction = lineage.get("has_contradiction", False)

        # Rule 0: Scope monotonicity: Promotion must be strictly upward (fail closed on lateral/downward)
        if candidate.target_scope <= candidate.source_scope:
            action = PromotionAction.REJECT_PROMOTION
            rationale = (
                f"Scope monotonicity violation: candidate target scope '{candidate.target_scope.value}' "
                f"must be strictly greater than source scope '{candidate.source_scope.value}'. Lateral or downward promotion rejected."
            )
            transform = "none"
            return self._build_receipt(candidate, action, rationale, transform, roots, indep_count, is_auth, is_tainted, now_iso)

        # Check temporal staleness against evaluation time
        if candidate.expires_at and candidate.expires_at < now_iso:
            action = PromotionAction.RETAIN_PRIVATE
            rationale = f"Candidate expired at {candidate.expires_at} (current: {now_iso}); retained in private scope."
            transform = "none"
            return self._build_receipt(candidate, action, rationale, transform, roots, indep_count, is_auth, is_tainted, now_iso)

        # Check authoritative contradiction
        if has_contradiction:
            action = PromotionAction.REJECT_PROMOTION
            rationale = "Rejected: Candidate directly contradicted by authoritative verified evidence."
            transform = "none"
            return self._build_receipt(candidate, action, rationale, transform, roots, indep_count, is_auth, is_tainted, now_iso)

        target = candidate.target_scope

        # Rule 1: Missing or unverifiable lineage cannot promote beyond TASK scope
        if is_missing_lineage and target > ScopeTier.TASK:
            action = PromotionAction.REQUEST_CORROBORATION
            rationale = "Missing or unverified evidence lineage; promotion beyond task scope held closed for corroboration."
            transform = "none"
            return self._build_receipt(candidate, action, rationale, transform, roots, indep_count, is_auth, is_tainted, now_iso)

        # Rule 2: Source laundering or LLM inference echo chains
        if lineage.get("has_laundered") and target > ScopeTier.TASK:
            action = PromotionAction.REJECT_PROMOTION
            rationale = f"Source-laundering attack detected: {'; '.join(taint_reasons)}. Rejected for collaborative scope."
            transform = "none"
            return self._build_receipt(candidate, action, rationale, transform, roots, indep_count, is_auth, is_tainted, now_iso)

        if lineage.get("has_llm_echo") and target > ScopeTier.TASK:
            action = PromotionAction.REQUEST_CORROBORATION
            rationale = "Correlated LLM inference echo loop detected; multiple agent repetitions share ungrounded root. Requires independent empirical corroboration."
            transform = "none"
            return self._build_receipt(candidate, action, rationale, transform, roots, indep_count, is_auth, is_tainted, now_iso)

        # Rule 3: Authoritative source exception
        qualifies_for_wider_scope = False
        if is_auth:
            qualifies_for_wider_scope = True
            lineage_note = "Authoritative verified source exception satisfied."
        elif indep_count >= 2:
            qualifies_for_wider_scope = True
            lineage_note = f"Independent corroboration verified ({indep_count} disjoint observational lineages)."
        elif target <= ScopeTier.PROJECT and indep_count >= 1 and not is_tainted:
            qualifies_for_wider_scope = True
            lineage_note = "Single verified local observation permitted for project-level scope."
        else:
            qualifies_for_wider_scope = False
            lineage_note = f"Insufficient independent evidence lineages ({indep_count} found, 2 required for team/org)."

        if not qualifies_for_wider_scope and target > ScopeTier.TASK:
            action = PromotionAction.REQUEST_CORROBORATION
            rationale = f"Cannot promote to {target.value}: {lineage_note}"
            transform = "none"
            return self._build_receipt(candidate, action, rationale, transform, roots, indep_count, is_auth, is_tainted, now_iso)

        # Rule 4: Disclosure transform (Redaction vs Aggregation vs Verbatim)
        clean_text, was_redacted = self.redact_statement(candidate.statement)
        is_aggregate_candidate = candidate.metadata.get("suggest_aggregate", False) or "lesson" in candidate.memory_key.lower()

        if is_aggregate_candidate and target >= ScopeTier.TEAM:
            action = PromotionAction.SHARE_AGGREGATE
            transform = "aggregate"
            rationale = f"{lineage_note} Abstracted to reusable aggregate rule for {target.value} scope."
        elif was_redacted:
            action = PromotionAction.SHARE_REDACTED
            transform = "redacted"
            rationale = f"{lineage_note} Sensitive synthetic secrets or local paths redacted before promotion to {target.value}."
        else:
            action = PromotionAction.SHARE_VERBATIM
            transform = "verbatim"
            rationale = f"{lineage_note} Memory verified and clean; projected verbatim to {target.value}."

        return self._build_receipt(
            candidate, action, rationale, transform, roots, indep_count, is_auth, is_tainted, now_iso
        )

    def _compute_evidence_digest(self, roots: list[EvidenceRoot]) -> str:
        """Compute a deterministic SHA-256 digest over the normalized root graph."""
        sorted_roots = sorted(roots, key=lambda r: r.root_id)
        tokens = [
            f"{r.root_id}:{r.root_type.value}:{r.origin_agent_id}:{r.source_ref}:{r.payload_hash}:{r.is_authoritative}:{r.is_tainted}"
            for r in sorted_roots
        ]
        raw = "|".join(tokens)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _compute_semantic_decision_hash(
        self,
        candidate: PromotionCandidate,
        policy_version: str,
        action: PromotionAction,
        transform: str,
        evidence_digest: str,
    ) -> str:
        """
        Compute reproducible semantic decision hash covering canonical candidate,
        policy version, target scope, evidence graph digest, and decision output.
        Explicitly excludes observation wall-clock time.
        """
        raw = (
            f"CANONICAL_CANDIDATE={candidate.candidate_id}:{candidate.memory_key}:{candidate.content_hash}:{candidate.source_scope.value}:{candidate.target_scope.value}:"
            f"POLICY={policy_version}:"
            f"DIGEST={evidence_digest}:"
            f"ACTION={action.value}:"
            f"TRANSFORM={transform}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _build_receipt(
        self,
        candidate: PromotionCandidate,
        action: PromotionAction,
        rationale: str,
        transform: str,
        roots: list[EvidenceRoot],
        indep_count: int,
        is_auth: bool,
        is_tainted: bool,
        timestamp: str,
    ) -> PromotionReceipt:
        # Sanitize root source_refs if redacted/aggregate
        sanitized_roots = []
        for r in roots:
            clean_ref, _ = self.redact_statement(r.source_ref) if transform in ("redacted", "aggregate") else (r.source_ref, False)
            sanitized_roots.append(
                EvidenceRoot(
                    root_id=r.root_id,
                    root_type=r.root_type,
                    origin_agent_id=r.origin_agent_id,
                    source_ref=clean_ref,
                    payload_hash=r.payload_hash,
                    is_authoritative=r.is_authoritative,
                    is_tainted=r.is_tainted,
                    taint_reason=r.taint_reason,
                )
            )

        evidence_digest = self._compute_evidence_digest(sanitized_roots)
        semantic_decision_hash = self._compute_semantic_decision_hash(
            candidate=candidate,
            policy_version=self.POLICY_VERSION,
            action=action,
            transform=transform,
            evidence_digest=evidence_digest,
        )
        receipt_id = f"rcpt_{candidate.candidate_id}_{action.value}_{semantic_decision_hash[:12]}"

        receipt = PromotionReceipt(
            receipt_id=receipt_id,
            candidate_id=candidate.candidate_id,
            memory_key=candidate.memory_key,
            policy_version=self.POLICY_VERSION,
            source_scope=candidate.source_scope,
            target_scope=candidate.target_scope,
            decision_action=action,
            deterministic_rationale=rationale,
            disclosure_transform=transform,
            evidence_roots=sanitized_roots,
            independent_lineage_count=indep_count,
            is_authoritative_root=is_auth,
            is_tainted=is_tainted,
            evidence_graph_digest=evidence_digest,
            semantic_decision_hash=semantic_decision_hash,
            created_at=timestamp,
        )

        try:
            self.conn.execute(
                """
                INSERT INTO ccp_promotion_receipts
                (receipt_id, candidate_id, memory_key, policy_version, source_scope, target_scope, decision_action, deterministic_rationale, disclosure_transform, evidence_roots_json, independent_lineage_count, is_authoritative_root, is_tainted, evidence_graph_digest, semantic_decision_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.candidate_id,
                    receipt.memory_key,
                    receipt.policy_version,
                    receipt.source_scope.value,
                    receipt.target_scope.value,
                    receipt.decision_action.value,
                    receipt.deterministic_rationale,
                    receipt.disclosure_transform,
                    json.dumps([r.to_dict() for r in receipt.evidence_roots]),
                    receipt.independent_lineage_count,
                    1 if receipt.is_authoritative_root else 0,
                    1 if receipt.is_tainted else 0,
                    receipt.evidence_graph_digest,
                    receipt.semantic_decision_hash,
                    receipt.created_at,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass
        return receipt

    # ──────────────────────────────────────────────────────────────────────────
    # Projection Creation & Commit (Append-Only, Temporal Validity, Zero-Leakage)
    # ──────────────────────────────────────────────────────────────────────────

    def apply_projection(
        self,
        candidate: PromotionCandidate,
        receipt: PromotionReceipt,
        parent_projection_ids: Optional[list[str]] = None,
        created_at: Optional[str] = None,
    ) -> Optional[ScopeProjection]:
        """
        Creates a versioned ScopeProjection if the receipt decision permits sharing.
        effective_at governs semantic validity (valid_from); created_at is audit metadata.
        Zero-leakage: sanitizes statements and metadata appropriately.
        Explicit parent_projection_ids are recorded as derivations.
        Never modifies the source candidate or evidence nodes.
        """
        if candidate.target_scope <= candidate.source_scope:
            raise ValueError(
                f"Scope monotonicity violation: candidate target scope '{candidate.target_scope.value}' "
                f"must be strictly greater than source scope '{candidate.source_scope.value}'"
            )

        if receipt.decision_action not in (
            PromotionAction.SHARE_VERBATIM,
            PromotionAction.SHARE_REDACTED,
            PromotionAction.SHARE_AGGREGATE,
        ):
            return None

        if receipt.disclosure_transform == "redacted":
            proj_text, _ = self.redact_statement(candidate.statement)
            proj_meta = self.redact_metadata(candidate.metadata)
        elif receipt.disclosure_transform == "aggregate":
            proj_text = self.aggregate_statement(candidate.statement, candidate.memory_key)
            # Exclude raw operational fields from aggregate metadata
            proj_meta = {
                k: v for k, v in candidate.metadata.items()
                if not any(ident in k.lower() for ident in ["path", "user", "session", "trace", "raw", "secret", "token", "agent", "error", "count", "debug", "loop"])
            }
            proj_meta["policy_tier"] = "aggregate"
        else:
            proj_text = candidate.statement
            proj_meta = dict(candidate.metadata)

        p_hash = hashlib.sha256(proj_text.encode("utf-8")).hexdigest()
        root_ids = [r.root_id for r in receipt.evidence_roots]
        proj_id = f"proj_{candidate.candidate_id}_{receipt.target_scope.value}_{receipt.semantic_decision_hash[:12]}"
        now_audit = created_at or datetime.now(timezone.utc).isoformat()
        parents = parent_projection_ids or []

        projection = ScopeProjection(
            projection_id=proj_id,
            candidate_id=candidate.candidate_id,
            memory_key=candidate.memory_key,
            projected_statement=proj_text,
            source_scope=candidate.source_scope,
            target_scope=candidate.target_scope,
            action=receipt.decision_action,
            transform_used=receipt.disclosure_transform,
            evidence_root_ids=root_ids,
            effective_at=candidate.effective_at,
            valid_from=candidate.effective_at,
            invalidated_at=None,
            expires_at=candidate.expires_at,
            content_hash=p_hash,
            revision_hash=receipt.semantic_decision_hash,
            invalidation_reason=None,
            created_at=now_audit,
            parent_projection_ids=parents,
            metadata=proj_meta,
        )

        if len(parents) != len(set(parents)):
            raise ValueError(f"Duplicate parent projection IDs found in derivation list: {parents}")

        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")

            # Validate derivation parents
            for parent_id in parents:
                if parent_id == proj_id:
                    raise ValueError(f"Self-derivation forbidden: parent {parent_id} cannot be identical to child {proj_id}")

                parent_row = cursor.execute(
                    "SELECT * FROM ccp_scope_projections WHERE projection_id = ?",
                    (parent_id,),
                ).fetchone()
                if not parent_row:
                    raise ValueError(f"Parent projection {parent_id} does not exist in scope projections")

                if not self.is_projection_active(parent_id, as_of=candidate.effective_at, cursor=cursor):
                    raise ValueError(
                        f"Parent projection {parent_id} is not active at child effective_at {candidate.effective_at}"
                    )

                parent_scope = ScopeTier(parent_row["target_scope"])
                if parent_scope > candidate.target_scope:
                    raise ValueError(
                        f"Derivation scope violation: child target scope '{candidate.target_scope.value}' "
                        f"cannot be lower than parent target scope '{parent_scope.value}'"
                    )

                if self._path_exists_in_derivations(proj_id, parent_id, cursor=cursor):
                    raise ValueError(
                        f"Cycle detected in derivation graph: path already exists from {proj_id} to {parent_id}"
                    )

                # Privacy monotonicity check
                if parent_row["action"] in ("share_redacted", "share_aggregate"):
                    if receipt.decision_action == PromotionAction.SHARE_VERBATIM:
                        if self.SECRET_REGEX.search(proj_text) or self.LOCAL_PATH_REGEX.search(proj_text):
                            raise ValueError(
                                f"Privacy monotonicity violation: parent {parent_id} was redacted/aggregate; "
                                f"child cannot re-expose unredacted secrets or paths in verbatim projection."
                            )

            cursor.execute(
                """
                INSERT INTO ccp_scope_projections
                (projection_id, candidate_id, memory_key, projected_statement, source_scope, target_scope, action, transform_used, evidence_root_ids, effective_at, valid_from, invalidated_at, expires_at, content_hash, revision_hash, invalidation_reason, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    projection.projection_id,
                    projection.candidate_id,
                    projection.memory_key,
                    projection.projected_statement,
                    projection.source_scope.value,
                    projection.target_scope.value,
                    projection.action.value,
                    projection.transform_used,
                    json.dumps(projection.evidence_root_ids),
                    projection.effective_at,
                    projection.valid_from,
                    projection.invalidated_at,
                    projection.expires_at,
                    projection.content_hash,
                    projection.revision_hash,
                    projection.invalidation_reason,
                    projection.created_at,
                    json.dumps(projection.metadata),
                ),
            )

            # Record derivation edges
            for parent_id in parents:
                deriv_id = f"deriv_{uuid.uuid4().hex}"
                cursor.execute(
                    """
                    INSERT INTO ccp_projection_derivations
                    (derivation_id, parent_projection_id, child_projection_id, derivation_type, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (deriv_id, parent_id, projection.projection_id, "projection_derivation", now_audit),
                )

            # Record append-only activate event in ccp_projection_validity_events
            act_event_id = f"val_act_{projection.projection_id}_{uuid.uuid4().hex[:8]}"
            cursor.execute(
                """
                INSERT INTO ccp_projection_validity_events
                (event_id, projection_id, event_type, effective_at, actor, rationale, contest_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    act_event_id,
                    projection.projection_id,
                    "activate",
                    projection.effective_at,
                    candidate.authority,
                    f"Activated projection for {receipt.target_scope.value} scope via {receipt.decision_action.value}",
                    None,
                    now_audit,
                ),
            )

            cursor.execute("COMMIT")
        except sqlite3.IntegrityError as e:
            try:
                cursor.execute("ROLLBACK")
            except Exception:
                pass
            raise ValueError(f"Cannot record duplicate projection: {proj_id}") from e
        except Exception:
            try:
                cursor.execute("ROLLBACK")
            except Exception:
                pass
            raise

        return projection

    # ──────────────────────────────────────────────────────────────────────────
    # Contest & Transitive Invalidation
    # ──────────────────────────────────────────────────────────────────────────

    def contest_projection(
        self,
        projection_id: str,
        contested_by: str,
        rationale: str,
        contested_at: Optional[str] = None,
        _inject_failure_mid_propagation: bool = False,
        _before_traversal_barrier: Optional[Any] = None,
    ) -> ReversalEvent:
        """
        Record a contest event and atomically reverse/invalidate the projection
        and every active descendant projection in the derivation DAG.
        Transactional: if an error occurs mid-propagation, rolls back completely.
        Preserves the immutable append-only audit trail.
        Acquires BEGIN IMMEDIATE at the start to eliminate races with concurrent child derivations.
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            if _before_traversal_barrier:
                _before_traversal_barrier()

            row = cursor.execute(
                "SELECT * FROM ccp_scope_projections WHERE projection_id = ?",
                (projection_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Projection {projection_id} not found")

            cand_id = row["candidate_id"]
            now_iso = contested_at or datetime.now(timezone.utc).isoformat()
            contest_id = f"cntst_{uuid.uuid4().hex}"

            # Collect transitive descendant projection IDs via ccp_projection_derivations
            invalidated_ids: list[str] = []
            queue = [projection_id]
            visited: set[str] = set()

            while queue:
                curr = queue.pop(0)
                if curr in visited:
                    continue
                visited.add(curr)
                invalidated_ids.append(curr)

                children = cursor.execute(
                    "SELECT child_projection_id FROM ccp_projection_derivations WHERE parent_projection_id = ?",
                    (curr,),
                ).fetchall()
                for ch in children:
                    queue.append(ch["child_projection_id"])

            cursor.execute(
                """
                INSERT INTO ccp_contest_events
                (contest_id, projection_id, candidate_id, contested_by, rationale, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (contest_id, projection_id, cand_id, contested_by, rationale, now_iso),
            )

            for idx, p_id in enumerate(invalidated_ids):
                if _inject_failure_mid_propagation and idx == len(invalidated_ids) - 1:
                    raise RuntimeError("Injected mid-propagation failure for atomic rollback verification")

                inval_msg = (
                    f"Contested by {contested_by}: {rationale}"
                    if p_id == projection_id
                    else f"Transitive invalidation from ancestor {projection_id}"
                )
                inv_event_id = f"val_inv_{p_id}_{uuid.uuid4().hex[:8]}"
                cursor.execute(
                    """
                    INSERT INTO ccp_projection_validity_events
                    (event_id, projection_id, event_type, effective_at, actor, rationale, contest_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (inv_event_id, p_id, "invalidate", now_iso, contested_by, inval_msg, contest_id, now_iso),
                )

            reversal_id = f"rev_{uuid.uuid4().hex}"
            rev_event = ReversalEvent(
                reversal_id=reversal_id,
                contest_id=contest_id,
                primary_projection_id=projection_id,
                invalidated_projection_ids=invalidated_ids,
                reverted_at=now_iso,
                audit_trail_preserved=True,
            )

            cursor.execute(
                """
                INSERT INTO ccp_reversal_events
                (reversal_id, contest_id, primary_projection_id, invalidated_projection_ids, reverted_at, audit_trail_preserved)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rev_event.reversal_id,
                    rev_event.contest_id,
                    rev_event.primary_projection_id,
                    json.dumps(rev_event.invalidated_projection_ids),
                    rev_event.reverted_at,
                    1 if rev_event.audit_trail_preserved else 0,
                ),
            )

            cursor.execute("COMMIT")
            return rev_event
        except Exception:
            try:
                cursor.execute("ROLLBACK")
            except Exception:
                pass
            raise

    # ──────────────────────────────────────────────────────────────────────────
    # Active Scope Query with Append-Only Validity Events
    # ──────────────────────────────────────────────────────────────────────────

    def query_active_projections(
        self, target_scope: ScopeTier, as_of: Optional[str] = None
    ) -> list[ScopeProjection]:
        """
        Query projections visible in target_scope as of a given timestamp.
        Derives active status exclusively from append-only ccp_projection_validity_events:
        A projection is active at as_of iff:
        1. The most recent event with effective_at <= as_of is 'activate'
           (with 'invalidate' taking precedence on equal effective_at timestamps).
        2. expires_at IS NULL OR expires_at >= as_of.
        effective_at governs semantic validity; created_at is audit metadata.
        Never reads or mutates ccp_scope_projections.invalidated_at.
        """
        query_time = as_of or datetime.now(timezone.utc).isoformat()
        query = """
            WITH ranked_events AS (
                SELECT
                    projection_id,
                    event_type,
                    effective_at,
                    created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY projection_id
                        ORDER BY
                            effective_at DESC,
                            CASE event_type WHEN 'invalidate' THEN 2 WHEN 'activate' THEN 1 ELSE 0 END DESC,
                            created_at DESC
                    ) as rank_num
                FROM ccp_projection_validity_events
                WHERE effective_at <= ?
            )
            SELECT p.*
            FROM ccp_scope_projections p
            JOIN ranked_events r ON p.projection_id = r.projection_id
            WHERE r.rank_num = 1
              AND r.event_type = 'activate'
              AND p.target_scope = ?
              AND (p.expires_at IS NULL OR p.expires_at >= ?)
            ORDER BY p.effective_at ASC
        """
        rows = self.conn.execute(
            query, (query_time, target_scope.value, query_time)
        ).fetchall()

        results = []
        for r in rows:
            deriv_rows = self.conn.execute(
                "SELECT parent_projection_id FROM ccp_projection_derivations WHERE child_projection_id = ?",
                (r["projection_id"],),
            ).fetchall()
            parent_ids = [dr["parent_projection_id"] for dr in deriv_rows]

            results.append(
                ScopeProjection(
                    projection_id=r["projection_id"],
                    candidate_id=r["candidate_id"],
                    memory_key=r["memory_key"],
                    projected_statement=r["projected_statement"],
                    source_scope=ScopeTier(r["source_scope"]),
                    target_scope=ScopeTier(r["target_scope"]),
                    action=PromotionAction(r["action"]),
                    transform_used=r["transform_used"],
                    evidence_root_ids=json.loads(r["evidence_root_ids"]),
                    effective_at=r["effective_at"],
                    valid_from=r["valid_from"],
                    invalidated_at=None,
                    expires_at=r["expires_at"],
                    content_hash=r["content_hash"],
                    revision_hash=r["revision_hash"],
                    invalidation_reason=None,
                    created_at=r["created_at"],
                    parent_projection_ids=parent_ids,
                    metadata=json.loads(r["metadata_json"]),
                )
            )
        return results

    def get_validity_events(self, projection_id: Optional[str] = None) -> list[ProjectionValidityEvent]:
        """Query append-only validity events, optionally filtered by projection_id."""
        if projection_id:
            query = """
                SELECT * FROM ccp_projection_validity_events
                WHERE projection_id = ?
                ORDER BY effective_at ASC, created_at ASC
            """
            rows = self.conn.execute(query, (projection_id,)).fetchall()
        else:
            query = """
                SELECT * FROM ccp_projection_validity_events
                ORDER BY effective_at ASC, created_at ASC
            """
            rows = self.conn.execute(query).fetchall()

        return [
            ProjectionValidityEvent(
                event_id=r["event_id"],
                projection_id=r["projection_id"],
                event_type=r["event_type"],
                effective_at=r["effective_at"],
                actor=r["actor"],
                rationale=r["rationale"],
                contest_id=r["contest_id"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def is_projection_active(
        self, projection_id: str, as_of: Optional[str] = None, cursor: Optional[sqlite3.Cursor] = None
    ) -> bool:
        """Check if a projection is active as of a given timestamp based on validity events."""
        query_time = as_of or datetime.now(timezone.utc).isoformat()
        cur = cursor or self.conn
        query = """
            SELECT event_type
            FROM ccp_projection_validity_events
            WHERE projection_id = ? AND effective_at <= ?
            ORDER BY
                effective_at DESC,
                CASE event_type WHEN 'invalidate' THEN 2 WHEN 'activate' THEN 1 ELSE 0 END DESC,
                created_at DESC
            LIMIT 1
        """
        row = cur.execute(query, (projection_id, query_time)).fetchone()
        if not row:
            return False
        if row["event_type"] != "activate":
            return False

        # Check expiration if projection exists
        p_row = cur.execute(
            "SELECT expires_at FROM ccp_scope_projections WHERE projection_id = ?",
            (projection_id,),
        ).fetchone()
        if p_row and p_row["expires_at"] and p_row["expires_at"] < query_time:
            return False
        return True
