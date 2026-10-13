"""Comprehensive test suite for Common-Cause-Aware Contestable Promotion (CCP).

Covers all required specifications:
P0:
- Append-only temporal validity with 3-point queries (before, during, after contest).
- Multi-step derivation chain transitive invalidation (root -> task -> project -> team).
- Atomic rollback on mid-propagation failure.
P1:
- Append-only immutability (reject duplicate IDs).
- Receipt determinism (identical semantic hashes across re-evaluations).
- Cycle rejection in causal DAG edge ingestion.
- Lineage semantics:
  1. One authoritative source plus copied paraphrases
  2. Authoritative source contradicted by later authoritative evidence
  3. Two agents repeating the same source
  4. Two independently produced observations that do not actually support the same claim
  5. Ambiguous artifact origin
P2:
- Output transformations zero-leakage test (projection body, receipt, metadata, evidence links).
- Corpus privacy lint verifying zero forbidden usernames, local paths, hardware values, or hostnames.
- Held-out evaluation across multiple seeds (42, 123, 999) reporting per-seed metrics and mean/range.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
import pytest

from research_harness.ccp.evaluation_schema import (
    EvalCase,
    EvalDataset,
    EvalGroundTruth,
    bootstrap_confidence_interval,
    compute_binary_classification_metrics,
    compute_rate,
    validate_evaluation_dataset,
)
from research_harness.ccp.robustness_report import (
    compute_report_identity_hash,
    compute_source_manifest,
    compute_test_manifest,
)

from research_harness.ccp.baselines import (
    BaselineB0AlwaysShare,
    BaselineB1StaticRegexDLP,
    BaselineB2DistinctAgentCount,
    BaselineB3CCPGate,
)
from research_harness.ccp.benchmark import run_full_ccp_evaluation
from research_harness.ccp.corpus import populate_synthetic_fixtures
from research_harness.ccp.engine import CCPEngine
from research_harness.ccp.models import (
    ArtifactIdentity,
    EdgeRelation,
    EvidenceEdge,
    EvidenceNode,
    NodeType,
    ProjectionValidityEvent,
    PromotionAction,
    PromotionCandidate,
    ScopeTier,
)
from research_harness.ccp.robustness_report import generate_robustness_report
from research_harness.ccp.schema import init_temporary_ccp_db
from research_harness.ccp.seeded_synthetic_robustness import (
    generate_synthetic_robustness_scenarios,
    run_multi_seed_robustness_benchmark,
)


@pytest.fixture
def ccp_env():
    conn = init_temporary_ccp_db()
    engine = CCPEngine(conn)
    yield conn, engine
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# P0: Temporal Validity & Contest Propagation Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_temporal_validity_three_points(ccp_env):
    """
    Test append-only temporal validity at three specific points in time:
    a. before projection effective_at / creation -> not visible
    b. after creation but before contest -> VISIBLE
    c. after contest -> not visible
    """
    _, engine = ccp_env

    t_before = "2026-10-06T07:00:00Z"
    t_effective = "2026-10-06T08:00:00Z"
    t_between = "2026-10-06T08:30:00Z"
    t_contest = "2026-10-06T09:00:00Z"
    t_after = "2026-10-06T09:30:00Z"

    node = EvidenceNode(
        node_id="node_temporal_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_t",
        statement="App service timeout is 30s",
        source_ref="config_file",
        payload_hash="hash_timeout_30",
        created_at=t_effective,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="cand_temporal_01",
        memory_key="service.timeout",
        statement="App service timeout is 30s",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at=t_effective,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand, current_time=t_effective)
    proj = engine.apply_projection(cand, receipt, created_at=t_effective)
    assert proj is not None

    # a. Query before effective_at: must NOT be visible
    res_before = engine.query_active_projections(ScopeTier.TEAM, as_of=t_before)
    assert not any(p.projection_id == proj.projection_id for p in res_before)

    # b. Query between effective_at and contest: MUST be visible
    res_between = engine.query_active_projections(ScopeTier.TEAM, as_of=t_between)
    assert any(p.projection_id == proj.projection_id for p in res_between)

    # Contest the projection at t_contest
    engine.contest_projection(
        proj.projection_id,
        contested_by="synthetic_owner",
        rationale="Timeout changed to 60s",
        contested_at=t_contest,
    )

    # c. Query after contest: must NOT be visible
    res_after = engine.query_active_projections(ScopeTier.TEAM, as_of=t_after)
    assert not any(p.projection_id == proj.projection_id for p in res_after)

    # Historical query at t_between remains visible (append-only audit travel)
    res_historical = engine.query_active_projections(ScopeTier.TEAM, as_of=t_between)
    assert any(p.projection_id == proj.projection_id for p in res_historical)


def test_transitive_invalidation_chain_and_unrelated_active(ccp_env):
    """
    Test real transitive invalidation across derivation DAG:
    root -> task projection -> project aggregate -> team summary.
    Contesting root must invalidate every descendant atomically.
    Unrelated projection must remain active.
    """
    _, engine = ccp_env

    t0 = "2026-10-06T10:00:00Z"

    # Create root evidence
    node_root = EvidenceNode(
        node_id="node_chain_root",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_admin",
        session_id="sess_chain",
        statement="Database connection limit is 100",
        source_ref="sysctl_probe",
        payload_hash="hash_conn_100",
        created_at=t0,
        is_authoritative=True,
    )
    engine.record_evidence_node(node_root)

    # 1. Root Candidate & Projection (Task scope)
    c_root = PromotionCandidate(
        candidate_id="cand_chain_task",
        memory_key="infra.db.connections.task",
        statement="Database connection limit is 100",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TASK,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node_root.node_id],
    )
    engine.record_candidate(c_root)
    r_root = engine.evaluate_promotion(c_root, current_time=t0)
    p_task = engine.apply_projection(c_root, r_root, parent_projection_ids=[], created_at=t0)
    assert p_task is not None

    # 2. Project Aggregate (derived from p_task)
    c_proj = PromotionCandidate(
        candidate_id="cand_chain_project",
        memory_key="infra.db.connections.project",
        statement="Project database connection limit configured to 100",
        source_scope=ScopeTier.TASK,
        target_scope=ScopeTier.PROJECT,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node_root.node_id],
    )
    engine.record_candidate(c_proj)
    r_proj = engine.evaluate_promotion(c_proj, current_time=t0)
    p_project = engine.apply_projection(c_proj, r_proj, parent_projection_ids=[p_task.projection_id], created_at=t0)
    assert p_project is not None

    # 3. Team Summary (derived from p_project)
    c_team = PromotionCandidate(
        candidate_id="cand_chain_team",
        memory_key="infra.db.connections.team",
        statement="Team database connection pool policy set to 100",
        source_scope=ScopeTier.PROJECT,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node_root.node_id],
    )
    engine.record_candidate(c_team)
    r_team = engine.evaluate_promotion(c_team, current_time=t0)
    p_team = engine.apply_projection(c_team, r_team, parent_projection_ids=[p_project.projection_id], created_at=t0)
    assert p_team is not None

    # 4. Unrelated projection in TEAM scope
    node_unrelated = EvidenceNode(
        node_id="node_unrelated_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_unrelated",
        statement="Unrelated logging level is INFO",
        source_ref="log_cfg",
        payload_hash="hash_log_info",
        created_at=t0,
        is_authoritative=True,
    )
    engine.record_evidence_node(node_unrelated)
    c_unrelated = PromotionCandidate(
        candidate_id="cand_unrelated_01",
        memory_key="infra.logging.level",
        statement="Logging level is INFO",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node_unrelated.node_id],
    )
    engine.record_candidate(c_unrelated)
    r_unrelated = engine.evaluate_promotion(c_unrelated, current_time=t0)
    p_unrelated = engine.apply_projection(c_unrelated, r_unrelated, parent_projection_ids=[], created_at=t0)
    assert p_unrelated is not None

    # Verify all active before contest
    assert len(engine.query_active_projections(ScopeTier.TASK, as_of="2026-10-06T10:05:00Z")) == 1
    assert len(engine.query_active_projections(ScopeTier.PROJECT, as_of="2026-10-06T10:05:00Z")) == 1
    active_team = engine.query_active_projections(ScopeTier.TEAM, as_of="2026-10-06T10:05:00Z")
    assert len(active_team) == 2

    # Contest p_task (root of the derivation chain)
    t_contest = "2026-10-06T10:10:00Z"
    rev = engine.contest_projection(
        p_task.projection_id,
        contested_by="synthetic_owner",
        rationale="Connection limit of 100 caused exhaustion; invalidating chain",
        contested_at=t_contest,
    )

    # Invalidation verification
    assert p_task.projection_id in rev.invalidated_projection_ids
    assert p_project.projection_id in rev.invalidated_projection_ids
    assert p_team.projection_id in rev.invalidated_projection_ids
    assert p_unrelated.projection_id not in rev.invalidated_projection_ids

    t_after = "2026-10-06T10:15:00Z"
    assert len(engine.query_active_projections(ScopeTier.TASK, as_of=t_after)) == 0
    assert len(engine.query_active_projections(ScopeTier.PROJECT, as_of=t_after)) == 0

    team_after = engine.query_active_projections(ScopeTier.TEAM, as_of=t_after)
    assert len(team_after) == 1
    assert team_after[0].projection_id == p_unrelated.projection_id


def test_atomic_rollback_on_injected_propagation_failure(ccp_env):
    """Verify that an exception mid-propagation rolls back atomically with no partial invalidations."""
    _, engine = ccp_env
    t0 = "2026-10-06T11:00:00Z"

    node = EvidenceNode(
        node_id="node_atomic_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_admin",
        session_id="sess_atomic",
        statement="Setting atomic_test = 1",
        source_ref="probe",
        payload_hash="hash_atomic_1",
        created_at=t0,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    c1 = PromotionCandidate(
        candidate_id="cand_atomic_parent",
        memory_key="test.atomic.p",
        statement="Setting atomic_test = 1",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TASK,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(c1)
    r1 = engine.evaluate_promotion(c1, current_time=t0)
    p_parent = engine.apply_projection(c1, r1, created_at=t0)

    c2 = PromotionCandidate(
        candidate_id="cand_atomic_child",
        memory_key="test.atomic.c",
        statement="Setting atomic_test child = 1",
        source_scope=ScopeTier.TASK,
        target_scope=ScopeTier.PROJECT,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(c2)
    r2 = engine.evaluate_promotion(c2, current_time=t0)
    p_child = engine.apply_projection(c2, r2, parent_projection_ids=[p_parent.projection_id], created_at=t0)

    # Attempt contest with injected failure
    with pytest.raises(RuntimeError, match="Injected mid-propagation failure"):
        engine.contest_projection(
            p_parent.projection_id,
            contested_by="synthetic_owner",
            rationale="Test rollback",
            contested_at="2026-10-06T11:05:00Z",
            _inject_failure_mid_propagation=True,
        )

    # Verify that transaction rolled back: both parent and child remain ACTIVE
    t_check = "2026-10-06T11:10:00Z"
    active_parent = engine.query_active_projections(ScopeTier.TASK, as_of=t_check)
    active_child = engine.query_active_projections(ScopeTier.PROJECT, as_of=t_check)

    assert any(p.projection_id == p_parent.projection_id for p in active_parent)
    assert any(p.projection_id == p_child.projection_id for p in active_child)

    # Invariant: atomic rollback leaves ZERO contest events, ZERO reversal events, and ZERO invalidate events
    conn, _ = ccp_env
    contest_count = conn.execute("SELECT COUNT(*) as c FROM ccp_contest_events").fetchone()["c"]
    reversal_count = conn.execute("SELECT COUNT(*) as c FROM ccp_reversal_events").fetchone()["c"]
    inval_events = conn.execute("SELECT COUNT(*) as c FROM ccp_projection_validity_events WHERE event_type = 'invalidate'").fetchone()["c"]
    assert contest_count == 0
    assert reversal_count == 0
    assert inval_events == 0


def test_append_only_validity_events_creation_and_contest(ccp_env):
    """
    Test append-only validity events:
    1. apply_projection creates an 'activate' event in ccp_projection_validity_events.
    2. contest_projection creates an 'invalidate' event in ccp_projection_validity_events.
    3. ccp_scope_projections is never updated (invalidated_at is NULL in table).
    4. Active status is derived exclusively from the event stream.
    """
    conn, engine = ccp_env
    t_create = "2026-10-06T10:00:00Z"
    t_contest = "2026-10-06T12:00:00Z"

    node = EvidenceNode(
        node_id="node_app_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_admin",
        session_id="sess_app",
        statement="Append-only verification",
        source_ref="audit_log",
        payload_hash="hash_app_1",
        created_at=t_create,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="cand_app_01",
        memory_key="system.append_only",
        statement="Append-only verification",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at=t_create,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand)
    receipt = engine.evaluate_promotion(cand, current_time=t_create)
    proj = engine.apply_projection(cand, receipt, created_at=t_create)
    assert proj is not None

    # Check that ccp_projection_validity_events has 1 'activate' event
    events = engine.get_validity_events(proj.projection_id)
    assert len(events) == 1
    assert events[0].event_type == "activate"
    assert events[0].effective_at == t_create
    assert events[0].actor == "verified_system"

    # Check that in ccp_scope_projections table, invalidated_at is NULL
    row = conn.execute("SELECT invalidated_at, invalidation_reason FROM ccp_scope_projections WHERE projection_id = ?", (proj.projection_id,)).fetchone()
    assert row["invalidated_at"] is None
    assert row["invalidation_reason"] is None

    # Verify query_active_projections before, during, and after
    assert len(engine.query_active_projections(ScopeTier.TEAM, as_of="2026-10-06T09:59:59Z")) == 0
    assert len(engine.query_active_projections(ScopeTier.TEAM, as_of="2026-10-06T11:00:00Z")) == 1

    # Contest the projection
    engine.contest_projection(
        proj.projection_id,
        contested_by="synthetic_auditor",
        rationale="Policy superseded",
        contested_at=t_contest,
    )

    # Check validity events: now has 2 events (activate, invalidate)
    events_after = engine.get_validity_events(proj.projection_id)
    assert len(events_after) == 2
    assert events_after[0].event_type == "activate"
    assert events_after[1].event_type == "invalidate"
    assert events_after[1].effective_at == t_contest
    assert events_after[1].actor == "synthetic_auditor"

    # Crucially: ccp_scope_projections table was NOT updated (still NULL)
    row_after = conn.execute("SELECT invalidated_at, invalidation_reason FROM ccp_scope_projections WHERE projection_id = ?", (proj.projection_id,)).fetchone()
    assert row_after["invalidated_at"] is None
    assert row_after["invalidation_reason"] is None

    # After contest query: inactive as of t_contest + 1 hour
    assert len(engine.query_active_projections(ScopeTier.TEAM, as_of="2026-10-06T13:00:00Z")) == 0
    # Historical as_of before contest query still sees it active
    assert len(engine.query_active_projections(ScopeTier.TEAM, as_of="2026-10-06T11:00:00Z")) == 1


def test_equal_timestamp_boundary_handling(ccp_env):
    """
    Test deterministic boundary conditions when queries or events have equal timestamps.
    - Query at as_of == effective_at of activate -> projection IS active.
    - Query at as_of == effective_at of invalidate -> projection is NOT active (fail-closed).
    - If activate and invalidate have identical effective_at -> invalidate wins (fail-closed).
    """
    _, engine = ccp_env
    t_event = "2026-10-06T12:00:00Z"

    node = EvidenceNode(
        node_id="node_bound_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_admin",
        session_id="sess_b",
        statement="Boundary test",
        source_ref="ref",
        payload_hash="hash_b",
        created_at=t_event,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="cand_bound_01",
        memory_key="system.boundary",
        statement="Boundary test",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.PROJECT,
        authority="verified_system",
        effective_at=t_event,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand)
    receipt = engine.evaluate_promotion(cand, current_time=t_event)
    proj = engine.apply_projection(cand, receipt, created_at=t_event)

    # 1. Exact equal timestamp query at creation time: MUST BE ACTIVE
    active_at_boundary = engine.query_active_projections(ScopeTier.PROJECT, as_of=t_event)
    assert len(active_at_boundary) == 1
    assert active_at_boundary[0].projection_id == proj.projection_id

    # 2. Contest at t_contest
    t_contest = "2026-10-06T13:00:00Z"
    engine.contest_projection(
        proj.projection_id,
        contested_by="tester",
        rationale="Contest boundary",
        contested_at=t_contest,
    )

    # Query at exact equal timestamp of contest: MUST BE INACTIVE (fail-closed)
    active_at_contest_boundary = engine.query_active_projections(ScopeTier.PROJECT, as_of=t_contest)
    assert len(active_at_contest_boundary) == 0

    # 3. Simultaneous activate and invalidate at the EXACT SAME effective timestamp
    cand2 = PromotionCandidate(
        candidate_id="cand_bound_02",
        memory_key="system.boundary2",
        statement="Simultaneous event test",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.PROJECT,
        authority="verified_system",
        effective_at="2026-10-06T14:00:00Z",
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand2)
    receipt2 = engine.evaluate_promotion(cand2, current_time="2026-10-06T14:00:00Z")
    proj2 = engine.apply_projection(cand2, receipt2, created_at="2026-10-06T14:00:00Z")

    # Invalidate with exact same effective timestamp as activate
    engine.contest_projection(
        proj2.projection_id,
        contested_by="tester",
        rationale="Simultaneous contest",
        contested_at="2026-10-06T14:00:00Z",
    )
    # Query at 2026-10-06T14:00:00Z must be inactive (fail-closed)
    assert not engine.is_projection_active(proj2.projection_id, as_of="2026-10-06T14:00:00Z")
    assert len(engine.query_active_projections(ScopeTier.PROJECT, as_of="2026-10-06T14:00:00Z")) == 0


# ──────────────────────────────────────────────────────────────────────────────
# P1: Immutability, Determinism, & Lineage Semantics
# ──────────────────────────────────────────────────────────────────────────────

def test_immutability_duplicate_id_rejection(ccp_env):
    """Verify that duplicate IDs are rejected with ValueError rather than silently overwritten."""
    _, engine = ccp_env

    node = EvidenceNode(
        node_id="node_duplicate_id_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_dup",
        statement="Original statement",
        source_ref="ref1",
        payload_hash="hash_orig",
        created_at="2026-10-06T12:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    node_dup = EvidenceNode(
        node_id="node_duplicate_id_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_dup2",
        statement="Mutated statement attempt",
        source_ref="ref2",
        payload_hash="hash_mut",
        created_at="2026-10-06T12:01:00Z",
        is_authoritative=True,
    )
    with pytest.raises(ValueError, match="Cannot record duplicate evidence node"):
        engine.record_evidence_node(node_dup)


def test_cycle_detection_in_evidence_graph(ccp_env):
    """Verify that adding an edge that would create a directed cycle is rejected."""
    _, engine = ccp_env

    n1 = EvidenceNode(
        node_id="node_cycle_1",
        node_type=NodeType.RAW_TOOL_EXEC,
        agent_id="agent_1",
        session_id="sess_c",
        statement="Step 1",
        source_ref="ref1",
        payload_hash="hash_c1",
        created_at="2026-10-06T12:00:00Z",
    )
    n2 = EvidenceNode(
        node_id="node_cycle_2",
        node_type=NodeType.RAW_TOOL_EXEC,
        agent_id="agent_2",
        session_id="sess_c",
        statement="Step 2",
        source_ref="ref2",
        payload_hash="hash_c2",
        created_at="2026-10-06T12:01:00Z",
    )
    engine.record_evidence_node(n1)
    engine.record_evidence_node(n2)

    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="edge_1_to_2",
            parent_node_id=n1.node_id,
            child_node_id=n2.node_id,
            relation_type=EdgeRelation.DERIVED_FROM,
            created_at="2026-10-06T12:01:00Z",
        )
    )

    with pytest.raises(ValueError, match="Cycle detected"):
        engine.record_evidence_edge(
            EvidenceEdge(
                edge_id="edge_2_to_1_bad",
                parent_node_id=n2.node_id,
                child_node_id=n1.node_id,
                relation_type=EdgeRelation.DERIVED_FROM,
                created_at="2026-10-06T12:02:00Z",
            )
        )


def test_receipt_determinism_identical_hashes(ccp_env):
    """
    Verify decision receipts are reproducible:
    Evaluating identical candidate twice at different evaluation clock times yields
    identical semantic_decision_hash.
    """
    _, engine = ccp_env

    node = EvidenceNode(
        node_id="node_det_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_det",
        statement="Hardware model SyntheticHost-X1000",
        source_ref="sysctl:hw.synthetic_model",
        payload_hash="hash_hw",
        created_at="2026-10-06T12:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="cand_det_01",
        memory_key="infra.hw.model",
        statement="Hardware model SyntheticHost-X1000",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T12:00:00Z",
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand)

    receipt_1 = engine.evaluate_promotion(cand, current_time="2026-10-06T12:05:00Z")
    receipt_2 = engine.evaluate_promotion(cand, current_time="2026-10-06T15:30:00Z")

    assert receipt_1.semantic_decision_hash == receipt_2.semantic_decision_hash
    assert receipt_1.receipt_id == receipt_2.receipt_id
    assert receipt_1.decision_action == receipt_2.decision_action


# ──────────────────────────────────────────────────────────────────────────────
# P1: Lineage Semantics (5 Required Cases)
# ──────────────────────────────────────────────────────────────────────────────

def test_lineage_case_1_one_authoritative_source_plus_copied_paraphrases(ccp_env):
    """Case 1: One authoritative source plus copied paraphrases qualifies alone."""
    _, engine = ccp_env

    root = EvidenceNode(
        node_id="case1_root_auth",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_kernel",
        session_id="sess_c1",
        statement="Max concurrent file descriptors is 65536",
        source_ref="kernel_param",
        payload_hash="hash_fd_65536",
        created_at="2026-10-06T00:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(root)

    p1 = EvidenceNode(
        node_id="case1_paraphrase_1",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_copier_1",
        session_id="sess_c1_p1",
        statement="Agent 1 copied: max files is 65536",
        source_ref="agent_chat:1",
        payload_hash="hash_p1",
        created_at="2026-10-06T00:01:00Z",
    )
    p2 = EvidenceNode(
        node_id="case1_paraphrase_2",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_copier_2",
        session_id="sess_c1_p2",
        statement="Agent 2 paraphrased: descriptor ceiling is 65536",
        source_ref="agent_chat:2",
        payload_hash="hash_p2",
        created_at="2026-10-06T00:02:00Z",
    )
    engine.record_evidence_node(p1)
    engine.record_evidence_node(p2)

    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="case1_edge_1",
            parent_node_id=root.node_id,
            child_node_id=p1.node_id,
            relation_type=EdgeRelation.COPIED_FROM,
            created_at="2026-10-06T00:01:00Z",
        )
    )
    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="case1_edge_2",
            parent_node_id=p1.node_id,
            child_node_id=p2.node_id,
            relation_type=EdgeRelation.PARAPHRASED_FROM,
            created_at="2026-10-06T00:02:00Z",
        )
    )

    cand = PromotionCandidate(
        candidate_id="case1_cand_files",
        memory_key="infra.limits.maxfiles",
        statement="Max concurrent file descriptors is 65536",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T00:02:00Z",
        evidence_node_ids=[p2.node_id],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    # 1 root only
    assert len(receipt.evidence_roots) == 1
    assert receipt.evidence_roots[0].root_id == "case1_root_auth"
    assert receipt.is_authoritative_root is True
    # Qualifies alone via authoritative exception
    assert receipt.decision_action == PromotionAction.SHARE_VERBATIM
    assert "Authoritative verified source exception satisfied" in receipt.deterministic_rationale


def test_lineage_case_2_authoritative_contradicted_by_later_evidence(ccp_env):
    """Case 2: Authoritative source contradicted by later authoritative evidence triggers rejection."""
    _, engine = ccp_env

    auth_earlier = EvidenceNode(
        node_id="case2_earlier_truth",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_admin",
        session_id="sess_c2",
        statement="Default encryption algorithm is AES-128",
        source_ref="security_policy_2025",
        payload_hash="hash_aes128",
        created_at="2026-10-06T00:00:00Z",
        is_authoritative=True,
    )
    auth_later = EvidenceNode(
        node_id="case2_later_truth",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_ciso",
        session_id="sess_c2_ciso",
        statement="Mandatory encryption algorithm is strictly AES-256",
        source_ref="security_policy_2026",
        payload_hash="hash_aes256",
        created_at="2026-10-06T01:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(auth_earlier)
    engine.record_evidence_node(auth_later)
    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="case2_edge_contra",
            parent_node_id=auth_later.node_id,
            child_node_id=auth_earlier.node_id,
            relation_type=EdgeRelation.CONTRADICTS,
            created_at="2026-10-06T01:00:00Z",
        )
    )

    cand = PromotionCandidate(
        candidate_id="case2_cand_aes",
        memory_key="security.crypto.cipher",
        statement="Default encryption algorithm is AES-128 across all nodes.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.ORGANIZATION,
        authority="verified_system",
        effective_at="2026-10-06T01:00:00Z",
        evidence_node_ids=[auth_earlier.node_id],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    assert receipt.decision_action == PromotionAction.REJECT_PROMOTION
    assert "contradicted by authoritative verified evidence" in receipt.deterministic_rationale.lower()


def test_lineage_case_3_two_agents_repeating_same_source(ccp_env):
    """Case 3: Two agents repeating the same source resolve to 1 root and fail multi-source requirement."""
    _, engine = ccp_env

    raw_obs = EvidenceNode(
        node_id="case3_raw_obs",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_initial",
        session_id="sess_init",
        statement="Observed proxy latency 45ms",
        source_ref="latency_log",
        payload_hash="hash_lat_45",
        created_at="2026-10-06T02:00:00Z",
        is_authoritative=False,
    )
    rep_a = EvidenceNode(
        node_id="case3_rep_a",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_echo_a",
        session_id="sess_ea",
        statement="Agent A reports latency 45ms",
        source_ref="chat_a",
        payload_hash="hash_ea",
        created_at="2026-10-06T02:01:00Z",
    )
    rep_b = EvidenceNode(
        node_id="case3_rep_b",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_echo_b",
        session_id="sess_eb",
        statement="Agent B reports latency 45ms",
        source_ref="chat_b",
        payload_hash="hash_eb",
        created_at="2026-10-06T02:02:00Z",
    )
    engine.record_evidence_node(raw_obs)
    engine.record_evidence_node(rep_a)
    engine.record_evidence_node(rep_b)

    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="case3_edge_a",
            parent_node_id=raw_obs.node_id,
            child_node_id=rep_a.node_id,
            relation_type=EdgeRelation.COPIED_FROM,
            created_at="2026-10-06T02:01:00Z",
        )
    )
    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="case3_edge_b",
            parent_node_id=raw_obs.node_id,
            child_node_id=rep_b.node_id,
            relation_type=EdgeRelation.COPIED_FROM,
            created_at="2026-10-06T02:02:00Z",
        )
    )

    cand = PromotionCandidate(
        candidate_id="case3_cand_lat",
        memory_key="service.proxy.latency",
        statement="Proxy service latency is standard 45ms.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_observation",
        effective_at="2026-10-06T02:02:00Z",
        evidence_node_ids=[rep_a.node_id, rep_b.node_id],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    # Must resolve to 1 single evidentiary lineage, not 2
    assert len(receipt.evidence_roots) == 1
    assert receipt.independent_lineage_count == 1
    # Team scope requires 2 disjoint lineages for non-authoritative observations
    assert receipt.decision_action == PromotionAction.REQUEST_CORROBORATION
    assert "Insufficient independent evidence lineages" in receipt.deterministic_rationale


def test_lineage_case_4_two_independent_observations_not_supporting_same_claim(ccp_env):
    """Case 4: Two independent observations that do not support the same claim cannot satisfy corroboration."""
    _, engine = ccp_env

    # Observation 1: observes database port 5432
    obs_db = EvidenceNode(
        node_id="case4_obs_db",
        node_type=NodeType.RAW_TOOL_EXEC,
        agent_id="agent_db_scanner",
        session_id="sess_db",
        statement="Observed Postgres listening on 5432",
        source_ref="netstat_db",
        payload_hash="hash_db_5432",
        created_at="2026-10-06T03:00:00Z",
        supported_claim_key="infra.postgres.port",
    )
    # Observation 2: observes redis thread count 16 (completely different claim)
    obs_redis = EvidenceNode(
        node_id="case4_obs_redis",
        node_type=NodeType.RAW_TOOL_EXEC,
        agent_id="agent_redis_scanner",
        session_id="sess_redis",
        statement="Observed Redis configured with 16 threads",
        source_ref="redis_cli",
        payload_hash="hash_redis_16",
        created_at="2026-10-06T03:01:00Z",
        supported_claim_key="infra.redis.threads",  # Mismatch!
    )
    engine.record_evidence_node(obs_db)
    engine.record_evidence_node(obs_redis)

    # Candidate claims Postgres port 5432, citing both observations
    cand = PromotionCandidate(
        candidate_id="case4_cand_mismatch",
        memory_key="infra.postgres.port",
        statement="Postgres service port verified on 5432.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="independent_observation",
        effective_at="2026-10-06T03:01:00Z",
        evidence_node_ids=[obs_db.node_id, obs_redis.node_id],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    # The redis observation does not support the postgres claim; only 1 valid lineage supports it!
    assert receipt.independent_lineage_count == 1
    assert receipt.decision_action == PromotionAction.REQUEST_CORROBORATION
    assert "does not support candidate claim" in receipt.deterministic_rationale or "Insufficient independent evidence lineages" in receipt.deterministic_rationale


def test_lineage_case_5_ambiguous_artifact_origin(ccp_env):
    """Case 5: Ambiguous artifact origin without write lineage is tainted and rejected."""
    _, engine = ccp_env

    artifact_meta = ArtifactIdentity(
        artifact_id="art_ambig_01",
        uri="/tmp/orphan_config.ini",
        content_digest="digest_orphan",
        origin_author="unknown_agent",
        write_lineage_node_id=None,
        is_ambiguous=True,
    )
    read_ambig = EvidenceNode(
        node_id="node_read_ambig_01",
        node_type=NodeType.ARTIFACT_READ,
        agent_id="agent_reader",
        session_id="sess_r",
        statement="Read config from orphan file",
        source_ref="file_read",
        payload_hash="hash_orphan",
        created_at="2026-10-06T04:00:00Z",
        artifact=artifact_meta,
    )
    engine.record_evidence_node(read_ambig)

    cand = PromotionCandidate(
        candidate_id="cand_ambig_01",
        memory_key="infra.orphan.config",
        statement="Orphan config is active.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_observation",
        effective_at="2026-10-06T04:00:00Z",
        evidence_node_ids=[read_ambig.node_id],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    assert receipt.is_tainted is True
    assert receipt.decision_action == PromotionAction.REJECT_PROMOTION
    assert "Source-laundering attack detected" in receipt.deterministic_rationale


# ──────────────────────────────────────────────────────────────────────────────
# P2: Output Transformations Zero Leakage Test
# ──────────────────────────────────────────────────────────────────────────────

def test_output_transformations_zero_leakage_across_all_channels(ccp_env):
    """
    Verify real output transformations and zero leakage:
    1. SHARE_REDACTED: Secrets and local paths purged from projection body, receipt, metadata, and roots.
    2. SHARE_AGGREGATE: Raw operational trace fields purged from projection body and metadata.
    """
    _, engine = ccp_env

    raw_secret = "sk-livekey999888777666abcdef"
    raw_path = "/Users/synthetic_dev/workspace/secret.env"

    node_secret = EvidenceNode(
        node_id="node_leak_test_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_deployer",
        session_id="sess_leak_01",
        statement=f"Deployed bearer {raw_secret} at {raw_path}",
        source_ref=f"file:{raw_path}",
        payload_hash="hash_leak_1",
        created_at="2026-10-06T05:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(node_secret)

    cand_redact = PromotionCandidate(
        candidate_id="cand_leak_redact_01",
        memory_key="infra.service.auth",
        statement=f"Deployed bearer {raw_secret} at {raw_path}",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T05:00:00Z",
        evidence_node_ids=[node_secret.node_id],
        metadata={"auth_token": raw_secret, "env_file": raw_path},
    )
    engine.record_candidate(cand_redact)

    receipt_redact = engine.evaluate_promotion(cand_redact)
    assert receipt_redact.decision_action == PromotionAction.SHARE_REDACTED
    assert receipt_redact.disclosure_transform == "redacted"

    proj_redact = engine.apply_projection(cand_redact, receipt_redact)
    assert proj_redact is not None

    # Leakage check: projection body
    assert raw_secret not in proj_redact.projected_statement
    assert raw_path not in proj_redact.projected_statement
    assert "[REDACTED_SECRET]" in proj_redact.projected_statement
    assert "~/[path]" in proj_redact.projected_statement

    # Leakage check: metadata
    assert raw_secret not in json.dumps(proj_redact.metadata)
    assert raw_path not in json.dumps(proj_redact.metadata)
    assert "[REDACTED_SECRET]" in json.dumps(proj_redact.metadata)

    # Leakage check: receipt evidence roots
    for root in receipt_redact.evidence_roots:
        assert raw_path not in root.source_ref

    # 2. Test aggregate sharing
    cand_agg = PromotionCandidate(
        candidate_id="cand_leak_agg_01",
        memory_key="lesson.sqlite.concurrency",
        statement=f"User encountered locked database in {raw_path} after 15 concurrent loops; adding busy_timeout=5000 resolved contention.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T05:10:00Z",
        evidence_node_ids=[node_secret.node_id],
        metadata={"suggest_aggregate": True, "raw_trace": "OperationalError in session_99", "error_count": 15},
    )
    engine.record_candidate(cand_agg)

    receipt_agg = engine.evaluate_promotion(cand_agg)
    assert receipt_agg.decision_action == PromotionAction.SHARE_AGGREGATE
    assert receipt_agg.disclosure_transform == "aggregate"

    proj_agg = engine.apply_projection(cand_agg, receipt_agg)
    assert proj_agg is not None

    # Structured summary verification
    assert "[ARCHITECTURAL_POLICY:LESSON]" in proj_agg.projected_statement
    assert raw_path not in proj_agg.projected_statement
    # Raw operational fields purged from aggregate metadata
    assert "raw_trace" not in proj_agg.metadata
    assert "error_count" not in proj_agg.metadata
    assert proj_agg.metadata.get("policy_tier") == "aggregate"


# ──────────────────────────────────────────────────────────────────────────────
# P2: Privacy Lint & Held-Out Multi-Seed Evaluation
# ──────────────────────────────────────────────────────────────────────────────

def test_fixture_privacy_lint():
    """Verify that fixture corpus contains zero real personal usernames, paths, hardware values, or hostnames."""
    forbidden_tokens = [
        "mihir",
        "deshpande",
        "/Users/mihir",
        "Users/mihirdeshpande",
        "Darwin arm64",
        "Mac14",
        "global-memory",
        "alphaos",
        "ASML",
        "AMD",
        "ADI",
    ]

    conn = init_temporary_ccp_db()
    engine = CCPEngine(conn)
    scenarios = populate_synthetic_fixtures(engine)

    violations = []
    for sc in scenarios:
        cand = sc["candidate"]
        cand_str = f"{cand.candidate_id} {cand.memory_key} {cand.statement} {cand.metadata}"
        for tok in forbidden_tokens:
            if tok.lower() in cand_str.lower():
                violations.append((cand.candidate_id, tok))

    nodes = conn.execute("SELECT * FROM ccp_evidence_nodes").fetchall()
    for n in nodes:
        node_str = f"{n['node_id']} {n['agent_id']} {n['statement']} {n['source_ref']}"
        for tok in forbidden_tokens:
            if tok.lower() in node_str.lower():
                violations.append((n["node_id"], tok))

    conn.close()
    assert not violations, f"Found private personal or non-fictional tokens in fixtures: {violations}"


def test_synthetic_seeded_robustness_evaluation_schema_and_consistency():
    """
    Recompute reproducible robustness report and assert consistency with schema and invariant properties,
    without hard-coding expected precision/recall values.
    Confirms evaluation is labeled as 'synthetic seeded robustness evaluation', not independent held-out validation.
    """
    report = generate_robustness_report(seeds=(42, 123, 999), scenarios_per_seed=26)

    # Top-level schema assertions
    assert report["report_title"] == "CCP Synthetic Seeded Robustness Evaluation Report"
    assert report["evaluation_type"] == "synthetic_seeded_robustness_evaluation"
    assert report["policy_version"] == CCPEngine.POLICY_VERSION
    assert "git_commit" in report
    assert "python_version" in report
    assert "generated_at" in report
    assert report["seeds"] == [42, 123, 999]
    assert report["scenario_count_per_seed"] == 26
    assert report["total_scenarios_evaluated"] == 78
    assert len(report["limitations"]) == 4

    # Baseline invariants
    agg = report["aggregate_metrics"]
    assert "B0_AlwaysShare" in agg
    assert "B1_StaticRegexDLP" in agg
    assert "B2_DistinctAgentCount" in agg
    assert "B3_CCPGate" in agg

    b3 = agg["B3_CCPGate"]
    b0 = agg["B0_AlwaysShare"]
    b2 = agg["B2_DistinctAgentCount"]

    # Security & privacy invariants
    assert b3["privacy_violations_sum"] == 0
    assert b3["source_laundering_sum"] == 0
    assert b3["echo_parrot_sum"] == 0
    assert b3["stale_leakage_sum"] == 0

    # Comparative advantages over naive baselines
    assert b3["promotion_precision"]["mean"] > b0["promotion_precision"]["mean"]
    assert b3["privacy_violations_sum"] < b0["privacy_violations_sum"]
    assert b2["echo_parrot_sum"] > 0 or b2["source_laundering_sum"] > 0

    # Metric range sanity across all baselines
    for b_key, b_metrics in agg.items():
        assert 0.0 <= b_metrics["promotion_precision"]["mean"] <= 1.0
        assert 0.0 <= b_metrics["promotion_recall"]["mean"] <= 1.0
        assert 0.0 <= b_metrics["false_promotion_rate"]["mean"] <= 1.0
        assert 0.0 <= b_metrics["false_rejection_rate"]["mean"] <= 1.0


def test_synthetic_seeded_robustness_two_run_determinism():
    """
    Confirm that fixed seeds produce the exact same metric result across two executions,
    excluding timing and audit fields.
    """
    report1 = generate_robustness_report(seeds=(42, 123, 999), scenarios_per_seed=26)
    report2 = generate_robustness_report(seeds=(42, 123, 999), scenarios_per_seed=26)

    # Exclude wall-clock generated_at audit metadata
    report1.pop("generated_at", None)
    report2.pop("generated_at", None)

    # Remove per-baseline latency metrics (which vary based on machine load)
    for s in report1["per_seed_metrics"]:
        for b in report1["per_seed_metrics"][s]:
            report1["per_seed_metrics"][s][b].pop("latency_p50_ms", None)
            report1["per_seed_metrics"][s][b].pop("latency_p95_ms", None)
            report2["per_seed_metrics"][s][b].pop("latency_p50_ms", None)
            report2["per_seed_metrics"][s][b].pop("latency_p95_ms", None)

    assert report1 == report2


def test_full_benchmark_suite_execution():
    """Verify that benchmark runner executes all baselines B0-B3 and computes calibration metrics."""
    results = run_full_ccp_evaluation()
    assert "B0_AlwaysShare" in results
    assert "B1_StaticRegexDLP" in results
    assert "B2_DistinctAgentCount" in results
    assert "B3_CCPGate" in results

    b3 = results["B3_CCPGate"]
    assert b3["promotion_precision"] >= 0.95
    assert b3["privacy_violations"] == 0
    assert b3["source_laundering_attack_success"] == 0
    assert b3["echo_parrot_attack_success"] == 0
    assert b3["stale_leakage"] == 0
    assert b3["projection_invalidation_completeness"] == 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Core Adversarial Regression Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_adversarial_1_ten_agents_parroting_llm_hallucination(ccp_env):
    """10 agents repeating one LLM hallucination must count as one lineage and be held closed."""
    _, engine = ccp_env

    root = EvidenceNode(
        node_id="adv1_llm_root",
        node_type=NodeType.LLM_INFERENCE,
        agent_id="agent_source_hallucinator",
        session_id="sess_0",
        statement="Postgres default port is 9999",
        source_ref="prompt_guess",
        payload_hash="hash_p9999",
        created_at="2026-10-06T00:00:00Z",
    )
    engine.record_evidence_node(root)

    prev_node = root.node_id
    parrot_ids = []
    for i in range(1, 11):
        nid = f"adv1_parrot_{i}"
        node = EvidenceNode(
            node_id=nid,
            node_type=NodeType.AGENT_OBSERVATION,
            agent_id=f"agent_sub_{i}",
            session_id=f"sess_{i}",
            statement=f"Echo {i}: Postgres default port is 9999",
            source_ref=f"chat_{i}",
            payload_hash=f"hash_echo_{i}",
            created_at=f"2026-10-06T00:0{i:02d}:00Z",
        )
        engine.record_evidence_node(node)
        engine.record_evidence_edge(
            EvidenceEdge(
                edge_id=f"adv1_edge_{i}",
                parent_node_id=prev_node,
                child_node_id=nid,
                relation_type=EdgeRelation.PARAPHRASED_FROM,
                created_at=f"2026-10-06T00:0{i:02d}:00Z",
            )
        )
        parrot_ids.append(nid)
        prev_node = nid

    cand = PromotionCandidate(
        candidate_id="adv1_cand_postgres",
        memory_key="infra.postgres.port",
        statement="Postgres default port is 9999",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_observation",
        effective_at="2026-10-06T00:10:00Z",
        evidence_node_ids=parrot_ids,
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    assert len(receipt.evidence_roots) == 1
    assert receipt.evidence_roots[0].root_id == "adv1_llm_root"
    assert receipt.independent_lineage_count == 0
    assert receipt.is_tainted is True
    assert receipt.decision_action == PromotionAction.REQUEST_CORROBORATION
    assert "Correlated LLM inference echo loop" in receipt.deterministic_rationale


def test_adversarial_2_two_agents_reading_same_verified_artifact(ccp_env):
    """Two agents reading the same verified artifact count as one root, but artifact qualifies alone."""
    _, engine = ccp_env

    artifact_node = EvidenceNode(
        node_id="adv2_verified_config",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_daemon",
        session_id="sess_init",
        statement="bind_address=127.0.0.1 in /etc/daemon.conf",
        source_ref="fs:/etc/daemon.conf",
        payload_hash="hash_daemon_conf",
        created_at="2026-10-06T00:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(artifact_node)

    read_a = EvidenceNode(
        node_id="adv2_read_agent_a",
        node_type=NodeType.ARTIFACT_READ,
        agent_id="agent_alice",
        session_id="sess_alice",
        statement="Alice read bind_address=127.0.0.1",
        source_ref="fs:/etc/daemon.conf",
        payload_hash="hash_daemon_conf",
        created_at="2026-10-06T00:05:00Z",
    )
    read_b = EvidenceNode(
        node_id="adv2_read_agent_b",
        node_type=NodeType.ARTIFACT_READ,
        agent_id="agent_bob",
        session_id="sess_bob",
        statement="Bob read bind_address=127.0.0.1",
        source_ref="fs:/etc/daemon.conf",
        payload_hash="hash_daemon_conf",
        created_at="2026-10-06T00:06:00Z",
    )
    engine.record_evidence_node(read_a)
    engine.record_evidence_node(read_b)

    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="adv2_edge_a",
            parent_node_id="adv2_verified_config",
            child_node_id="adv2_read_agent_a",
            relation_type=EdgeRelation.READ_FROM,
            created_at="2026-10-06T00:05:00Z",
        )
    )
    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="adv2_edge_b",
            parent_node_id="adv2_verified_config",
            child_node_id="adv2_read_agent_b",
            relation_type=EdgeRelation.READ_FROM,
            created_at="2026-10-06T00:06:00Z",
        )
    )

    cand = PromotionCandidate(
        candidate_id="adv2_cand_bind",
        memory_key="infra.daemon.bind_address",
        statement="Daemon listens strictly on 127.0.0.1",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T00:06:00Z",
        evidence_node_ids=["adv2_read_agent_a", "adv2_read_agent_b"],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    assert len(receipt.evidence_roots) == 1
    assert receipt.evidence_roots[0].root_id == "adv2_verified_config"
    assert receipt.is_authoritative_root is True
    assert receipt.decision_action == PromotionAction.SHARE_VERBATIM
    assert "Authoritative verified source exception satisfied" in receipt.deterministic_rationale


def test_adversarial_3_source_laundering_through_agent_written_file(ccp_env):
    """An agent writes an inference to a file and another reads it; lineage remains tainted."""
    _, engine = ccp_env

    inf_node = EvidenceNode(
        node_id="adv3_inf_guess",
        node_type=NodeType.LLM_INFERENCE,
        agent_id="agent_sketchy_1",
        session_id="sess_s1",
        statement="Speculation: memory_limit is 128MB",
        source_ref="prompt_inference",
        payload_hash="hash_guess_128",
        created_at="2026-10-06T00:00:00Z",
    )
    write_node = EvidenceNode(
        node_id="adv3_write_file",
        node_type=NodeType.ARTIFACT_WRITE,
        agent_id="agent_sketchy_1",
        session_id="sess_s1",
        statement="echo memory_limit=128MB > /tmp/limits.env",
        source_ref="bash_exec:write",
        payload_hash="hash_file_128",
        created_at="2026-10-06T00:01:00Z",
    )
    engine.record_evidence_node(inf_node)
    engine.record_evidence_node(write_node)
    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="adv3_edge_inf_write",
            parent_node_id="adv3_inf_guess",
            child_node_id="adv3_write_file",
            relation_type=EdgeRelation.DERIVED_FROM,
            created_at="2026-10-06T00:01:00Z",
        )
    )

    read_node = EvidenceNode(
        node_id="adv3_read_file",
        node_type=NodeType.ARTIFACT_READ,
        agent_id="agent_innocent_2",
        session_id="sess_i2",
        statement="Read memory_limit=128MB from /tmp/limits.env",
        source_ref="file_read:/tmp/limits.env",
        payload_hash="hash_file_128",
        created_at="2026-10-06T00:02:00Z",
    )
    engine.record_evidence_node(read_node)
    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="adv3_edge_write_read",
            parent_node_id="adv3_write_file",
            child_node_id="adv3_read_file",
            relation_type=EdgeRelation.READ_FROM,
            created_at="2026-10-06T00:02:00Z",
        )
    )

    cand = PromotionCandidate(
        candidate_id="adv3_cand_limit",
        memory_key="infra.limits.memory",
        statement="Process memory limit is 128MB according to /tmp/limits.env",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_observation",
        effective_at="2026-10-06T00:02:00Z",
        evidence_node_ids=["adv3_read_file"],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    assert receipt.is_tainted is True
    assert receipt.decision_action == PromotionAction.REJECT_PROMOTION
    assert "Source-laundering attack detected" in receipt.deterministic_rationale


def test_adversarial_4_missing_parent_lineage_cannot_promote_beyond_task(ccp_env):
    """Missing parent lineage cannot promote beyond task scope."""
    _, engine = ccp_env

    cand_empty = PromotionCandidate(
        candidate_id="adv4_cand_no_lineage",
        memory_key="infra.dns.server",
        statement="DNS server is 1.1.1.1",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="unverifiable",
        effective_at="2026-10-06T00:00:00Z",
        evidence_node_ids=[],
    )
    engine.record_candidate(cand_empty)

    receipt = engine.evaluate_promotion(cand_empty)
    assert receipt.decision_action == PromotionAction.REQUEST_CORROBORATION
    assert "Missing or unverified evidence lineage" in receipt.deterministic_rationale


def test_adversarial_5_contest_invalidates_all_active_derived_projections(ccp_env):
    """Contest invalidates all active derived projections."""
    _, engine = ccp_env

    node = EvidenceNode(
        node_id="adv5_node_rule",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_admin",
        session_id="sess_1",
        statement="All builds must use node 16",
        source_ref="admin_directive",
        payload_hash="hash_node16",
        created_at="2026-10-06T00:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="adv5_cand_node16",
        memory_key="policy.node.version",
        statement="All builds must use node 16",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T00:00:00Z",
        evidence_node_ids=["adv5_node_rule"],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    proj = engine.apply_projection(cand, receipt)
    assert proj is not None

    active_before = engine.query_active_projections(ScopeTier.TEAM)
    assert any(p.projection_id == proj.projection_id for p in active_before)

    reversal = engine.contest_projection(
        projection_id=proj.projection_id,
        contested_by="synthetic_owner",
        rationale="Node 16 is deprecated; Node 22 is required",
    )
    assert proj.projection_id in reversal.invalidated_projection_ids

    active_after = engine.query_active_projections(ScopeTier.TEAM)
    assert not any(p.projection_id == proj.projection_id for p in active_after)


def test_adversarial_6_contest_never_erases_original_evidence_or_audit(ccp_env):
    """Contest never erases the original evidence or audit record."""
    conn, engine = ccp_env

    node = EvidenceNode(
        node_id="adv6_node_db",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_p",
        statement="Old DB host is db-legacy.synthetic.internal",
        source_ref="dns_probe",
        payload_hash="hash_db_old",
        created_at="2026-10-06T00:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="adv6_cand_db",
        memory_key="infra.db.host",
        statement="Old DB host is db-legacy.synthetic.internal",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T00:00:00Z",
        evidence_node_ids=["adv6_node_db"],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    proj = engine.apply_projection(cand, receipt)
    assert proj is not None

    engine.contest_projection(proj.projection_id, "synthetic_owner", "Host decommissioned")

    cur = conn.cursor()
    assert cur.execute("SELECT count(*) FROM ccp_evidence_nodes WHERE node_id = 'adv6_node_db'").fetchone()[0] == 1
    assert cur.execute("SELECT count(*) FROM ccp_promotion_candidates WHERE candidate_id = 'adv6_cand_db'").fetchone()[0] == 1
    assert cur.execute("SELECT count(*) FROM ccp_promotion_receipts WHERE candidate_id = 'adv6_cand_db'").fetchone()[0] == 1
    assert cur.execute("SELECT count(*) FROM ccp_contest_events WHERE projection_id = ?", (proj.projection_id,)).fetchone()[0] == 1
    assert cur.execute("SELECT count(*) FROM ccp_reversal_events WHERE primary_projection_id = ?", (proj.projection_id,)).fetchone()[0] == 1


def test_adversarial_7_redaction_removes_synthetic_secret_and_path(ccp_env):
    """Redaction removes synthetic secret/path material before wider projection."""
    _, engine = ccp_env

    node = EvidenceNode(
        node_id="adv7_node_secret",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="deploy_bot",
        session_id="sess_dep",
        statement="Exported token sk-ant-secret1234567890abcdef at /Users/synthetic_dev/secure/app.env",
        source_ref="deploy_env",
        payload_hash="hash_secret_env",
        created_at="2026-10-06T00:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="adv7_cand_secret",
        memory_key="infra.service.env",
        statement="Exported token sk-ant-secret1234567890abcdef at /Users/synthetic_dev/secure/app.env",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T00:00:00Z",
        evidence_node_ids=["adv7_node_secret"],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand)
    assert receipt.decision_action == PromotionAction.SHARE_REDACTED
    assert receipt.disclosure_transform == "redacted"

    proj = engine.apply_projection(cand, receipt)
    assert proj is not None
    assert "sk-ant" not in proj.projected_statement
    assert "/Users/synthetic_dev" not in proj.projected_statement
    assert "[REDACTED_SECRET]" in proj.projected_statement
    assert "~/[path]" in proj.projected_statement


def test_adversarial_8_historical_as_of_queries_do_not_surface_invalidated_projections(ccp_env):
    """Historical/as_of queries do not surface invalidated projections as current truth."""
    _, engine = ccp_env

    node = EvidenceNode(
        node_id="adv8_node_status",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_s",
        statement="Staging cluster running v1.0",
        source_ref="cluster_probe",
        payload_hash="hash_v1",
        created_at="2026-10-06T00:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="adv8_cand_status",
        memory_key="service.staging.version",
        statement="Staging cluster running v1.0",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T00:00:00Z",
        evidence_node_ids=["adv8_node_status"],
    )
    engine.record_candidate(cand)

    receipt = engine.evaluate_promotion(cand, current_time="2026-10-06T00:00:00Z")
    proj = engine.apply_projection(cand, receipt)
    assert proj is not None

    engine.contest_projection(
        proj.projection_id,
        "synthetic_owner",
        "Upgraded to v2.0",
        contested_at="2026-10-06T01:00:00Z",
    )

    current_active = engine.query_active_projections(ScopeTier.TEAM, as_of="2026-10-06T02:00:00Z")
    assert not any(p.projection_id == proj.projection_id for p in current_active)

    before_creation = engine.query_active_projections(ScopeTier.TEAM, as_of="2026-10-05T23:00:00Z")
    assert not any(p.projection_id == proj.projection_id for p in before_creation)

    between = engine.query_active_projections(ScopeTier.TEAM, as_of="2026-10-06T00:30:00Z")
    assert any(p.projection_id == proj.projection_id for p in between)


# ──────────────────────────────────────────────────────────────────────────────
# P1: Metamorphic Robustness Tests (Invariants A - E)
# ──────────────────────────────────────────────────────────────────────────────

def test_metamorphic_a_copied_echoes_do_not_increase_lineage_count_or_score(ccp_env):
    """
    Metamorphic Invariant A:
    Copying/echoing evidence from the same agent or common cause must not increase
    the independent lineage count or change the promotion decision.
    """
    _, engine = ccp_env
    t0 = "2026-10-06T10:00:00Z"

    # Base candidate: 1 ungrounded observation
    root = EvidenceNode(
        node_id="meta_a_root",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_alpha",
        session_id="sess_a1",
        statement="Service latency spike detected",
        source_ref="observation",
        payload_hash="hash_a_spike",
        created_at=t0,
        is_authoritative=False,
    )
    engine.record_evidence_node(root)

    cand_base = PromotionCandidate(
        candidate_id="cand_meta_a_base",
        memory_key="service.spike",
        statement="Service latency spike detected",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_alpha",
        effective_at=t0,
        evidence_node_ids=[root.node_id],
    )
    engine.record_candidate(cand_base)
    receipt_base = engine.evaluate_promotion(cand_base, current_time=t0)
    assert receipt_base.independent_lineage_count == 1
    assert receipt_base.decision_action == PromotionAction.REQUEST_CORROBORATION

    # Now add 5 copied / paraphrased echo nodes from other agents copying agent_alpha
    echo_ids = [root.node_id]
    for i in range(1, 6):
        echo_node = EvidenceNode(
            node_id=f"meta_a_echo_{i}",
            node_type=NodeType.LLM_INFERENCE,
            agent_id=f"agent_echo_{i}",
            session_id=f"sess_echo_{i}",
            statement="Service latency spike detected (echo)",
            source_ref=f"agent_alpha_chat_{i}",
            payload_hash=f"hash_a_echo_{i}",
            created_at=t0,
            is_authoritative=False,
        )
        engine.record_evidence_node(echo_node)
        engine.record_evidence_edge(
            EvidenceEdge(
                edge_id=f"edge_echo_{i}",
                parent_node_id=root.node_id,
                child_node_id=echo_node.node_id,
                relation_type=EdgeRelation.COPIED_FROM,
                created_at=t0,
            )
        )
        echo_ids.append(echo_node.node_id)

    cand_echoed = PromotionCandidate(
        candidate_id="cand_meta_a_echoed",
        memory_key="service.spike",
        statement="Service latency spike detected",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_alpha",
        effective_at=t0,
        evidence_node_ids=echo_ids,
    )
    engine.record_candidate(cand_echoed)
    receipt_echoed = engine.evaluate_promotion(cand_echoed, current_time=t0)

    # Invariant: independent lineage count MUST NOT increase despite 5 new agent claims!
    assert receipt_echoed.independent_lineage_count == 1
    assert receipt_echoed.decision_action == PromotionAction.REQUEST_CORROBORATION


def test_metamorphic_b_renaming_agents_does_not_change_decision(ccp_env):
    """
    Metamorphic Invariant B:
    Permuting or renaming agent identifiers must not change causal cluster assignment,
    lineage counts, or the promotion decision.
    """
    _, engine = ccp_env
    t0 = "2026-10-06T10:00:00Z"

    # Setup 2 independent sources with original agent names
    node1 = EvidenceNode(
        node_id="meta_b_src1",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="Agent_Alice",
        session_id="sess_alice",
        statement="Database connection timeout on port 5432",
        source_ref="postgres_log",
        payload_hash="hash_pg_timeout",
        created_at=t0,
        is_authoritative=False,
    )
    node2 = EvidenceNode(
        node_id="meta_b_src2",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="Agent_Bob",
        session_id="sess_bob",
        statement="Database connection timeout on port 5432 confirmed",
        source_ref="pg_stat_activity",
        payload_hash="hash_pg_stat",
        created_at=t0,
        is_authoritative=False,
    )
    engine.record_evidence_node(node1)
    engine.record_evidence_node(node2)

    c1 = PromotionCandidate(
        candidate_id="cand_meta_b1",
        memory_key="db.timeout",
        statement="Database connection timeout on port 5432",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="Agent_Alice",
        effective_at=t0,
        evidence_node_ids=[node1.node_id, node2.node_id],
    )
    engine.record_candidate(c1)
    r1 = engine.evaluate_promotion(c1, current_time=t0)

    # Now create an isomorphic structure where agents are renamed:
    # Agent_Alice -> Agent_Xavier, Agent_Bob -> Agent_Yolanda
    node1_renamed = EvidenceNode(
        node_id="meta_b_src1_renamed",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="Agent_Xavier",
        session_id="sess_xavier",
        statement="Database connection timeout on port 5432",
        source_ref="postgres_log",
        payload_hash="hash_pg_timeout",
        created_at=t0,
        is_authoritative=False,
    )
    node2_renamed = EvidenceNode(
        node_id="meta_b_src2_renamed",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="Agent_Yolanda",
        session_id="sess_yolanda",
        statement="Database connection timeout on port 5432 confirmed",
        source_ref="pg_stat_activity",
        payload_hash="hash_pg_stat",
        created_at=t0,
        is_authoritative=False,
    )
    engine.record_evidence_node(node1_renamed)
    engine.record_evidence_node(node2_renamed)

    c2 = PromotionCandidate(
        candidate_id="cand_meta_b2",
        memory_key="db.timeout",
        statement="Database connection timeout on port 5432",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="Agent_Xavier",
        effective_at=t0,
        evidence_node_ids=[node1_renamed.node_id, node2_renamed.node_id],
    )
    engine.record_candidate(c2)
    r2 = engine.evaluate_promotion(c2, current_time=t0)

    # Invariants:
    assert r1.decision_action == r2.decision_action == PromotionAction.SHARE_VERBATIM
    assert r1.independent_lineage_count == r2.independent_lineage_count == 2
    assert r1.disclosure_transform == r2.disclosure_transform == "verbatim"


def test_metamorphic_c_permuting_evidence_order_does_not_change_decision_hash(ccp_env):
    """
    Metamorphic Invariant C:
    Permuting the order in which identical evidence items are presented must not change
    the decision hash, rationale, or action.
    """
    _, engine = ccp_env
    t0 = "2026-10-06T10:00:00Z"

    e1 = EvidenceNode(
        node_id="meta_c_e1",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_1",
        session_id="sess_1",
        statement="Node 1 statement",
        source_ref="src_1",
        payload_hash="hash_1",
        created_at=t0,
        is_authoritative=False,
    )
    e2 = EvidenceNode(
        node_id="meta_c_e2",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_2",
        session_id="sess_2",
        statement="Node 2 statement",
        source_ref="src_2",
        payload_hash="hash_2",
        created_at=t0,
        is_authoritative=False,
    )
    e3 = EvidenceNode(
        node_id="meta_c_e3",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_3",
        session_id="sess_3",
        statement="Node 3 statement",
        source_ref="src_3",
        payload_hash="hash_3",
        created_at=t0,
        is_authoritative=False,
    )
    for e in [e1, e2, e3]:
        engine.record_evidence_node(e)

    # Candidate 1 with order [e1, e2, e3]
    c1 = PromotionCandidate(
        candidate_id="cand_meta_c_fixed",
        memory_key="test.order",
        statement="Multi-evidence claim",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_1",
        effective_at=t0,
        evidence_node_ids=[e1.node_id, e2.node_id, e3.node_id],
    )
    engine.record_candidate(c1)
    r1 = engine.evaluate_promotion(c1, current_time=t0)

    # Candidate 2 with permuted order [e3, e1, e2]
    c2 = PromotionCandidate(
        candidate_id="cand_meta_c_fixed",  # same canonical candidate ID for semantic hash comparison
        memory_key="test.order",
        statement="Multi-evidence claim",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_1",
        effective_at=t0,
        evidence_node_ids=[e3.node_id, e1.node_id, e2.node_id],
    )
    r2 = engine.evaluate_promotion(c2, current_time=t0)

    assert r1.evidence_graph_digest == r2.evidence_graph_digest
    assert r1.semantic_decision_hash == r2.semantic_decision_hash
    assert r1.decision_action == r2.decision_action
    assert r1.deterministic_rationale == r2.deterministic_rationale


def test_metamorphic_d_later_contest_does_not_change_pre_contest_as_of_queries(ccp_env):
    """
    Metamorphic Invariant D:
    Contesting an ancestor at t_contest must not alter query_active_projections results
    for as_of < t_contest.
    """
    _, engine = ccp_env
    t_create = "2026-10-06T10:00:00Z"
    t_pre_query = "2026-10-06T11:00:00Z"
    t_contest = "2026-10-06T12:00:00Z"

    node = EvidenceNode(
        node_id="meta_d_node",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_admin",
        session_id="sess_d",
        statement="Valid system invariant",
        source_ref="kernel_probe",
        payload_hash="hash_inv",
        created_at=t_create,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="cand_meta_d",
        memory_key="system.inv",
        statement="Valid system invariant",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at=t_create,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand)
    receipt = engine.evaluate_promotion(cand, current_time=t_create)
    proj = engine.apply_projection(cand, receipt, created_at=t_create)

    # Pre-contest query result
    active_before_contest = engine.query_active_projections(ScopeTier.TEAM, as_of=t_pre_query)
    assert len(active_before_contest) == 1
    assert active_before_contest[0].projection_id == proj.projection_id

    # Contest the projection later at t_contest
    engine.contest_projection(
        proj.projection_id,
        contested_by="tester",
        rationale="Invalidated later",
        contested_at=t_contest,
    )

    # Invariant: querying as_of < t_contest MUST return the exact same result as before!
    active_after_contest_pre_query = engine.query_active_projections(ScopeTier.TEAM, as_of=t_pre_query)
    assert len(active_after_contest_pre_query) == 1
    assert active_after_contest_pre_query[0].projection_id == proj.projection_id


def test_metamorphic_e_adding_unrelated_candidate_does_not_change_decisions(ccp_env):
    """
    Metamorphic Invariant E:
    Adding an unrelated candidate and evidence items to the store must not alter
    promotion decisions for existing candidates.
    """
    _, engine = ccp_env
    t0 = "2026-10-06T10:00:00Z"

    n1 = EvidenceNode(
        node_id="meta_e_n1",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_1",
        session_id="sess_e1",
        statement="Target claim evidence",
        source_ref="ref_1",
        payload_hash="hash_e1",
        created_at=t0,
        is_authoritative=True,
    )
    engine.record_evidence_node(n1)

    cand1 = PromotionCandidate(
        candidate_id="cand_meta_e1",
        memory_key="target.claim",
        statement="Target claim evidence",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[n1.node_id],
    )
    engine.record_candidate(cand1)
    receipt1_before = engine.evaluate_promotion(cand1, current_time=t0)

    # Inject 10 unrelated evidence nodes and an unrelated candidate
    for i in range(10):
        unrelated_node = EvidenceNode(
            node_id=f"unrelated_node_{i}",
            node_type=NodeType.AGENT_OBSERVATION,
            agent_id=f"other_agent_{i}",
            session_id=f"other_sess_{i}",
            statement=f"Unrelated statement {i}",
            source_ref=f"unrelated_ref_{i}",
            payload_hash=f"unrelated_hash_{i}",
            created_at=t0,
            is_authoritative=False,
        )
        engine.record_evidence_node(unrelated_node)

    cand_unrelated = PromotionCandidate(
        candidate_id="cand_unrelated_x",
        memory_key="unrelated.claim",
        statement="Completely unrelated claim",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TASK,
        authority="other_agent_0",
        effective_at=t0,
        evidence_node_ids=["unrelated_node_0"],
    )
    engine.record_candidate(cand_unrelated)

    # Re-evaluate cand1
    receipt1_after = engine.evaluate_promotion(cand1, current_time=t0)

    # Invariants:
    assert receipt1_before.decision_action == receipt1_after.decision_action
    assert receipt1_before.semantic_decision_hash == receipt1_after.semantic_decision_hash
    assert receipt1_before.evidence_graph_digest == receipt1_after.evidence_graph_digest
    assert receipt1_before.independent_lineage_count == receipt1_after.independent_lineage_count
    assert receipt1_before.deterministic_rationale == receipt1_after.deterministic_rationale


# ──────────────────────────────────────────────────────────────────────────────
# Phase A: Database-Enforced Immutability Triggers & Concurrency
# ──────────────────────────────────────────────────────────────────────────────

def test_audit_triggers_reject_updates_and_deletes(ccp_env):
    """Phase A1: Verify SQLite triggers abort with IntegrityError on UPDATE or DELETE across all audit tables."""
    conn, engine = ccp_env

    t0 = "2026-10-06T10:00:00Z"
    node = EvidenceNode(
        node_id="trg_node_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_trg",
        statement="Node for trigger test",
        source_ref="ref_trg",
        payload_hash="hash_trg",
        created_at=t0,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="trg_cand_01",
        memory_key="sys.test.key",
        statement="Candidate statement",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TASK,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand)
    receipt = engine.evaluate_promotion(cand, current_time=t0)
    proj = engine.apply_projection(cand, receipt, created_at=t0)
    assert proj is not None

    cand2 = PromotionCandidate(
        candidate_id="trg_cand_02",
        memory_key="sys.test.key2",
        statement="Child projection statement",
        source_scope=ScopeTier.TASK,
        target_scope=ScopeTier.PROJECT,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand2)
    receipt2 = engine.evaluate_promotion(cand2, current_time=t0)
    proj2 = engine.apply_projection(cand2, receipt2, parent_projection_ids=[proj.projection_id], created_at=t0)
    assert proj2 is not None

    engine.contest_projection(proj.projection_id, contested_by="auditor", rationale="Trigger test")

    # A1.1: ccp_projection_validity_events
    with pytest.raises(sqlite3.IntegrityError, match="ccp_projection_validity_events is append-only"):
        conn.execute("UPDATE ccp_projection_validity_events SET rationale = 'mutated' WHERE projection_id = ?", (proj.projection_id,))
    with pytest.raises(sqlite3.IntegrityError, match="ccp_projection_validity_events is append-only"):
        conn.execute("DELETE FROM ccp_projection_validity_events WHERE projection_id = ?", (proj.projection_id,))

    # A1.2: ccp_contest_events
    with pytest.raises(sqlite3.IntegrityError, match="ccp_contest_events is append-only"):
        conn.execute("UPDATE ccp_contest_events SET rationale = 'mutated'")
    with pytest.raises(sqlite3.IntegrityError, match="ccp_contest_events is append-only"):
        conn.execute("DELETE FROM ccp_contest_events")

    # A1.3: ccp_reversal_events
    with pytest.raises(sqlite3.IntegrityError, match="ccp_reversal_events is append-only"):
        conn.execute("UPDATE ccp_reversal_events SET audit_trail_preserved = 0")
    with pytest.raises(sqlite3.IntegrityError, match="ccp_reversal_events is append-only"):
        conn.execute("DELETE FROM ccp_reversal_events")

    # A1.4: ccp_promotion_receipts
    with pytest.raises(sqlite3.IntegrityError, match="ccp_promotion_receipts is append-only"):
        conn.execute("UPDATE ccp_promotion_receipts SET deterministic_rationale = 'tampered'")
    with pytest.raises(sqlite3.IntegrityError, match="ccp_promotion_receipts is append-only"):
        conn.execute("DELETE FROM ccp_promotion_receipts")

    # A1.5: ccp_scope_projections
    with pytest.raises(sqlite3.IntegrityError, match="ccp_scope_projections is immutable"):
        conn.execute("UPDATE ccp_scope_projections SET projected_statement = 'tampered'")
    with pytest.raises(sqlite3.IntegrityError, match="ccp_scope_projections is immutable"):
        conn.execute("DELETE FROM ccp_scope_projections")

    # A1.6: ccp_projection_derivations
    with pytest.raises(sqlite3.IntegrityError, match="ccp_projection_derivations is append-only"):
        conn.execute("UPDATE ccp_projection_derivations SET derivation_type = 'tampered'")
    with pytest.raises(sqlite3.IntegrityError, match="ccp_projection_derivations is append-only"):
        conn.execute("DELETE FROM ccp_projection_derivations")


def test_concurrency_begin_immediate_prevents_derivation_races(tmp_path):
    """Phase A2: Verify BEGIN IMMEDIATE locking blocks concurrent child derivation insertions during contest cascade."""
    db_file = tmp_path / "race_test.db"
    conn_setup = init_temporary_ccp_db(db_file, timeout=5.0)
    engine_setup = CCPEngine(conn_setup)

    t0 = "2026-10-06T10:00:00Z"
    node = EvidenceNode(
        node_id="conc_node_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_conc",
        statement="Concurrency base node",
        source_ref="ref_conc",
        payload_hash="hash_conc",
        created_at=t0,
        is_authoritative=True,
    )
    engine_setup.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="conc_cand_01",
        memory_key="conc.base.key",
        statement="Concurrency statement",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TASK,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node.node_id],
    )
    engine_setup.record_candidate(cand)
    receipt = engine_setup.evaluate_promotion(cand, current_time=t0)
    proj = engine_setup.apply_projection(cand, receipt, created_at=t0)
    assert proj is not None
    conn_setup.close()

    barrier_entered = threading.Event()
    barrier_release = threading.Event()
    thread_error: list[Exception] = []
    conn2_locked_out = threading.Event()

    def run_contest():
        try:
            conn1 = init_temporary_ccp_db(db_file, timeout=0.1)
            engine1 = CCPEngine(conn1)

            def barrier():
                barrier_entered.set()
                if not barrier_release.wait(timeout=3.0):
                    raise TimeoutError("Barrier wait timed out")

            engine1.contest_projection(
                proj.projection_id,
                contested_by="thread_contestor",
                rationale="Testing race condition",
                _before_traversal_barrier=barrier,
            )
            conn1.close()
        except Exception as e:
            thread_error.append(e)

    t = threading.Thread(target=run_contest)
    t.start()

    assert barrier_entered.wait(timeout=2.0)

    # Attempt to write on conn2 while conn1 holds BEGIN IMMEDIATE lock
    conn2 = init_temporary_ccp_db(db_file, timeout=0.1)
    try:
        conn2.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower() or "busy" in str(e).lower():
            conn2_locked_out.set()
    finally:
        barrier_release.set()
        t.join(timeout=3.0)
        conn2.close()

    assert not thread_error, f"Contest thread encountered error: {thread_error}"
    assert conn2_locked_out.is_set(), "Concurrent connection was not locked out by BEGIN IMMEDIATE"


def test_derivation_graph_integrity_validations(ccp_env):
    """Phase A3: Verify derivation integrity constraints: self-edge, duplicates, ghost parent, inactive parent, cycle, and scope demotion."""
    _, engine = ccp_env
    t0 = "2026-10-06T10:00:00Z"
    t1 = "2026-10-06T11:00:00Z"

    node = EvidenceNode(
        node_id="deriv_node_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_deriv",
        statement="Node statement",
        source_ref="ref_deriv",
        payload_hash="hash_deriv",
        created_at=t0,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand_parent = PromotionCandidate(
        candidate_id="cand_deriv_parent",
        memory_key="parent.key",
        statement="Parent statement",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TASK,
        authority="verified_system",
        effective_at=t1,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand_parent)
    rcpt_parent = engine.evaluate_promotion(cand_parent, current_time=t1)
    proj_parent = engine.apply_projection(cand_parent, rcpt_parent, created_at=t1)
    assert proj_parent is not None

    cand_child = PromotionCandidate(
        candidate_id="cand_deriv_child",
        memory_key="child.key",
        statement="Child statement",
        source_scope=ScopeTier.TASK,
        target_scope=ScopeTier.PROJECT,
        authority="verified_system",
        effective_at=t1,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand_child)
    rcpt_child = engine.evaluate_promotion(cand_child, current_time=t1)

    # 1. Duplicate parent ID in derivation list
    with pytest.raises(ValueError, match="Duplicate parent projection IDs"):
        engine.apply_projection(
            cand_child, rcpt_child, parent_projection_ids=[proj_parent.projection_id, proj_parent.projection_id]
        )

    # 2. Non-existent parent projection
    with pytest.raises(ValueError, match="Parent projection proj_nonexistent does not exist"):
        engine.apply_projection(cand_child, rcpt_child, parent_projection_ids=["proj_nonexistent"])

    # 3. Parent not active at child effective_at (child effective_at is before parent activation t1)
    cand_early_child = PromotionCandidate(
        candidate_id="cand_early_child",
        memory_key="early.child.key",
        statement="Early child statement",
        source_scope=ScopeTier.TASK,
        target_scope=ScopeTier.PROJECT,
        authority="verified_system",
        effective_at=t0,  # Before t1!
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand_early_child)
    rcpt_early = engine.evaluate_promotion(cand_early_child, current_time=t0)
    with pytest.raises(ValueError, match="is not active at child effective_at"):
        engine.apply_projection(cand_early_child, rcpt_early, parent_projection_ids=[proj_parent.projection_id])

    # 4. Derivation scope violation: Child target scope cannot be lower than parent target scope
    cand_team_parent = PromotionCandidate(
        candidate_id="cand_team_parent",
        memory_key="team.parent.key",
        statement="Team parent statement",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at=t1,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand_team_parent)
    rcpt_team = engine.evaluate_promotion(cand_team_parent, current_time=t1)
    proj_team = engine.apply_projection(cand_team_parent, rcpt_team, created_at=t1)
    assert proj_team is not None

    cand_demoted_child = PromotionCandidate(
        candidate_id="cand_demoted_child",
        memory_key="demoted.child.key",
        statement="Demoted child statement",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TASK,  # Lower than TEAM!
        authority="verified_system",
        effective_at=t1,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand_demoted_child)
    rcpt_demoted = engine.evaluate_promotion(cand_demoted_child, current_time=t1)
    with pytest.raises(ValueError, match="Derivation scope violation"):
        engine.apply_projection(cand_demoted_child, rcpt_demoted, parent_projection_ids=[proj_team.projection_id])


# ──────────────────────────────────────────────────────────────────────────────
# Phase D: Scope Monotonicity & Privacy Non-Interference Matrix
# ──────────────────────────────────────────────────────────────────────────────

def test_scope_monotonicity_enforcement(ccp_env):
    """Phase D1: Verify that candidates cannot promote laterally or downward across scopes."""
    _, engine = ccp_env
    t0 = "2026-10-06T10:00:00Z"

    node = EvidenceNode(
        node_id="mono_node_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_mono",
        statement="Scope monotonicity test node",
        source_ref="ref_mono",
        payload_hash="hash_mono",
        created_at=t0,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    # 1. Downward promotion: TEAM -> TASK
    cand_downward = PromotionCandidate(
        candidate_id="cand_downward_01",
        memory_key="sys.downward",
        statement="Downward promotion attempt",
        source_scope=ScopeTier.TEAM,
        target_scope=ScopeTier.TASK,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand_downward)
    receipt_down = engine.evaluate_promotion(cand_downward, current_time=t0)
    assert receipt_down.decision_action == PromotionAction.REJECT_PROMOTION
    assert "Scope monotonicity violation" in receipt_down.deterministic_rationale

    # Direct apply_projection attempt must raise ValueError
    with pytest.raises(ValueError, match="Scope monotonicity violation"):
        engine.apply_projection(cand_downward, receipt_down)

    # 2. Lateral/same scope: PROJECT -> PROJECT
    cand_lateral = PromotionCandidate(
        candidate_id="cand_lateral_01",
        memory_key="sys.lateral",
        statement="Lateral promotion attempt",
        source_scope=ScopeTier.PROJECT,
        target_scope=ScopeTier.PROJECT,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node.node_id],
    )
    engine.record_candidate(cand_lateral)
    receipt_lat = engine.evaluate_promotion(cand_lateral, current_time=t0)
    assert receipt_lat.decision_action == PromotionAction.REJECT_PROMOTION
    assert "Scope monotonicity violation" in receipt_lat.deterministic_rationale


def test_privacy_non_interference_all_eight_channels(ccp_env):
    """Phase D2: Privacy Non-Interference Matrix across all 8 projection and audit channels."""
    conn, engine = ccp_env
    t0 = "2026-10-06T10:00:00Z"
    raw_secret = "sk-antigravity-999-super-secret"
    raw_path = "/Users/mihirdeshpande/confidential/keys.pem"

    node = EvidenceNode(
        node_id="priv_node_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_priv",
        statement=f"Database credentials stored with token {raw_secret} at path {raw_path}",
        source_ref=f"audit_log:{raw_path}",
        payload_hash="hash_priv",
        created_at=t0,
        is_authoritative=True,
    )
    engine.record_evidence_node(node)

    cand = PromotionCandidate(
        candidate_id="cand_priv_matrix",
        memory_key="sec.creds.vault",
        statement=f"Service auth key is {raw_secret} located at {raw_path}",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at=t0,
        evidence_node_ids=[node.node_id],
        metadata={
            "nested_list": [{"token": raw_secret, "file": raw_path}],
            "auth_path": raw_path,
        },
    )
    engine.record_candidate(cand)
    receipt = engine.evaluate_promotion(cand, current_time=t0)
    assert receipt.decision_action == PromotionAction.SHARE_REDACTED

    proj = engine.apply_projection(cand, receipt, created_at=t0)
    assert proj is not None

    rev = engine.contest_projection(proj.projection_id, contested_by="privacy_officer", rationale=f"Contesting {raw_path}")

    # Channel 1: ccp_scope_projections.projected_statement
    row_proj = conn.execute("SELECT * FROM ccp_scope_projections WHERE projection_id = ?", (proj.projection_id,)).fetchone()
    assert raw_secret not in row_proj["projected_statement"]
    assert raw_path not in row_proj["projected_statement"]

    # Channel 2: ccp_scope_projections.metadata_json
    assert raw_secret not in row_proj["metadata_json"]
    assert raw_path not in row_proj["metadata_json"]

    # Channel 3: ccp_promotion_receipts.deterministic_rationale
    row_rcpt = conn.execute("SELECT * FROM ccp_promotion_receipts WHERE receipt_id = ?", (receipt.receipt_id,)).fetchone()
    assert raw_secret not in row_rcpt["deterministic_rationale"]
    assert raw_path not in row_rcpt["deterministic_rationale"]

    # Channel 4: ccp_promotion_receipts.evidence_roots_json (source_refs sanitized)
    assert raw_secret not in row_rcpt["evidence_roots_json"]
    assert raw_path not in row_rcpt["evidence_roots_json"]

    # Channel 5: ccp_projection_validity_events.rationale
    rows_val = conn.execute("SELECT * FROM ccp_projection_validity_events WHERE projection_id = ?", (proj.projection_id,)).fetchall()
    for v in rows_val:
        assert raw_secret not in v["rationale"]

    # Channel 6: ccp_contest_events.rationale
    row_cntst = conn.execute("SELECT * FROM ccp_contest_events WHERE contest_id = ?", (rev.contest_id,)).fetchone()
    assert raw_secret not in row_cntst["rationale"]

    # Channel 7: ccp_reversal_events
    row_rev = conn.execute("SELECT * FROM ccp_reversal_events WHERE reversal_id = ?", (rev.reversal_id,)).fetchone()
    assert raw_secret not in json.dumps(dict(row_rev))

    # Channel 8: evidence_graph_digest & semantic_decision_hash (must be deterministic digests, not raw secret)
    assert raw_secret not in receipt.evidence_graph_digest
    assert raw_secret not in receipt.semantic_decision_hash
    assert len(receipt.evidence_graph_digest) == 64


# ──────────────────────────────────────────────────────────────────────────────
# Phase C & Phase B: Evaluation Framework & Reproducibility Invariants
# ──────────────────────────────────────────────────────────────────────────────

def test_evaluation_schema_validation_and_metric_calculators():
    """Phase C: Verify evaluation schema fixture, validation rules, rate metrics, and bootstrap CI."""
    schema_path = Path(__file__).resolve().parents[1] / "ccp/fixtures/independent_eval_schema.json"
    assert schema_path.exists()
    schema_json = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema_json["title"] == "CCP Independent Evaluation Dataset Schema"

    # 1. Valid dataset validation
    valid_data = {
        "dataset_id": "eval_dataset_01",
        "version": "1.0.0",
        "description": "Independent held-out evaluation dataset",
        "author_id": "external_evaluator_01",
        "created_at": "2026-10-06T10:00:00Z",
        "frozen_hash": "a" * 64,
        "adjudication_protocol": {
            "blinded": True,
            "adjudicator_count": 2,
            "arbitration_rule": "consensus_or_expert_tiebreaker",
            "inter_rater_agreement_cohen_kappa": 0.88,
        },
        "cases": [
            {
                "case_id": "case_eval_01",
                "description": "Test case description",
                "memory_key": "test.eval.key",
                "statement": "Statement to promote",
                "source_scope": "private",
                "target_scope": "team",
                "authority": "verified_system",
                "effective_at": "2026-10-06T10:00:00Z",
                "expires_at": None,
                "metadata": {},
                "evidence_nodes": [
                    {
                        "node_id": "node_ev_01",
                        "node_type": "verified_system_fact",
                        "agent_id": "agent_01",
                        "session_id": "sess_01",
                        "statement": "Observation",
                        "source_ref": "ref_01",
                        "payload_hash": "hash_01",
                        "created_at": "2026-10-06T10:00:00Z",
                        "is_authoritative": True,
                    }
                ],
                "evidence_edges": [],
                "ground_truth": {
                    "expected_action": "share_verbatim",
                    "expected_transform": "verbatim",
                    "authoritative_verdict": True,
                    "taint_expected": False,
                    "rationale": "Authoritative fact qualifies for team verbatim",
                },
            }
        ],
    }
    errs = validate_evaluation_dataset(valid_data)
    assert errs == [], f"Validation errors on valid data: {errs}"

    # 2. Invalid dataset validation (invalid scope and bad hash)
    invalid_data = dict(valid_data)
    invalid_data["frozen_hash"] = "short_hash"
    invalid_data["cases"] = [dict(valid_data["cases"][0], target_scope="galaxy_scope")]
    errs_invalid = validate_evaluation_dataset(invalid_data)
    assert any("frozen_hash" in e for e in errs_invalid)
    assert any("invalid target_scope" in e for e in errs_invalid)

    # 3. Metric calculators with numerator / denominator
    rate_res = compute_rate(17, 20)
    assert rate_res == {"numerator": 17, "denominator": 20, "rate": 0.85}

    y_true = [True, True, False, False, True]
    y_pred = [True, False, False, True, True]
    clf = compute_binary_classification_metrics(y_true, y_pred)
    assert clf["true_positives"] == 2
    assert clf["false_positives"] == 1
    assert clf["false_negatives"] == 1
    assert clf["true_negatives"] == 1
    assert clf["precision"]["numerator"] == 2
    assert clf["precision"]["denominator"] == 3
    assert clf["recall"]["numerator"] == 2
    assert clf["recall"]["denominator"] == 3

    # 4. Bootstrap CI
    ci_low, ci_high = bootstrap_confidence_interval([0.8, 0.85, 0.9, 0.95], n_bootstrap=500, ci=0.95, seed=42)
    assert 0.8 <= ci_low <= ci_high <= 0.95


def test_report_identity_hash_determinism_and_tamper_sensitivity():
    """Phase B: Verify deterministic report_identity_hash and sensitivity to source tampering."""
    report1 = generate_robustness_report(seeds=(42, 123, 999), scenarios_per_seed=26)
    report2 = generate_robustness_report(seeds=(42, 123, 999), scenarios_per_seed=26)

    # Identity invariant
    assert report1["report_identity_hash"] == report2["report_identity_hash"]
    assert "source_manifest" in report1
    assert "test_manifest" in report1
    assert "repository_head" in report1
    assert "working_tree_dirty" in report1
    assert report1["source_manifest"]["aggregate_source_sha256"] == report2["source_manifest"]["aggregate_source_sha256"]
    assert report1["test_manifest"]["aggregate_test_sha256"] == report2["test_manifest"]["aggregate_test_sha256"]

    # Methodology disclosure assertions
    assert report1["methodology_disclosures"]["evaluation_nature"] == "synthetic seeded robustness evaluation"
    assert report1["methodology_disclosures"]["independent_status"] == "not held-out empirical validation"
    assert "controlled perturbation" in report1["methodology_disclosures"]["limitation_statement"]

    # Tamper sensitivity: mutating source digest changes report identity hash
    tampered_hash = compute_report_identity_hash(
        policy_version=report1["policy_version"],
        aggregate_source_sha256="0" * 64,  # Altered source digest
        aggregate_test_sha256=report1["test_manifest"]["aggregate_test_sha256"],
        python_version=report1["python_version"],
        seeds=tuple(report1["seeds"]),
        scenarios_per_seed=report1["scenario_count_per_seed"],
        aggregate_metrics=report1["aggregate_metrics"],
    )
    assert tampered_hash != report1["report_identity_hash"]
