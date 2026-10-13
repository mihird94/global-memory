"""Temporary SQLite schema definition for the CCP experiment harness.

This schema is strictly isolated from production GMS tables. It runs
in-memory or in ephemeral temp directories for experiments.
Enforces database-level append-only audit immutability and derivation integrity.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from research_harness.isolation import reject_live_memory_path


CCP_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ccp_evidence_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_authoritative INTEGER NOT NULL DEFAULT 0,
    artifact_json TEXT,
    supported_claim_key TEXT
);

CREATE TABLE IF NOT EXISTS ccp_evidence_edges (
    edge_id TEXT PRIMARY KEY,
    parent_node_id TEXT NOT NULL,
    child_node_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (parent_node_id) REFERENCES ccp_evidence_nodes(node_id),
    FOREIGN KEY (child_node_id) REFERENCES ccp_evidence_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS ccp_promotion_candidates (
    candidate_id TEXT PRIMARY KEY,
    memory_key TEXT NOT NULL,
    statement TEXT NOT NULL,
    source_scope TEXT NOT NULL CHECK (source_scope IN ('private', 'task', 'project', 'team', 'organization')),
    target_scope TEXT NOT NULL CHECK (target_scope IN ('private', 'task', 'project', 'team', 'organization')),
    authority TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    expires_at TEXT,
    content_hash TEXT NOT NULL,
    evidence_node_ids TEXT NOT NULL, -- JSON list of node_ids
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ccp_scope_projections (
    projection_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    projected_statement TEXT NOT NULL,
    source_scope TEXT NOT NULL CHECK (source_scope IN ('private', 'task', 'project', 'team', 'organization')),
    target_scope TEXT NOT NULL CHECK (target_scope IN ('private', 'task', 'project', 'team', 'organization')),
    action TEXT NOT NULL CHECK (action IN ('retain_private', 'share_verbatim', 'share_redacted', 'share_aggregate', 'request_corroboration', 'reject_promotion')),
    transform_used TEXT NOT NULL,
    evidence_root_ids TEXT NOT NULL, -- JSON list of root node_ids
    effective_at TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    invalidated_at TEXT,
    expires_at TEXT,
    content_hash TEXT NOT NULL,
    revision_hash TEXT NOT NULL,
    invalidation_reason TEXT,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (candidate_id) REFERENCES ccp_promotion_candidates(candidate_id)
);

CREATE TABLE IF NOT EXISTS ccp_projection_validity_events (
    event_id TEXT PRIMARY KEY,
    projection_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('activate', 'invalidate')),
    effective_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    rationale TEXT NOT NULL,
    contest_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (projection_id) REFERENCES ccp_scope_projections(projection_id)
);

CREATE TABLE IF NOT EXISTS ccp_projection_derivations (
    derivation_id TEXT PRIMARY KEY,
    parent_projection_id TEXT NOT NULL,
    child_projection_id TEXT NOT NULL,
    derivation_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (parent_projection_id != child_projection_id),
    UNIQUE (parent_projection_id, child_projection_id),
    FOREIGN KEY (parent_projection_id) REFERENCES ccp_scope_projections(projection_id),
    FOREIGN KEY (child_projection_id) REFERENCES ccp_scope_projections(projection_id)
);

CREATE TABLE IF NOT EXISTS ccp_promotion_receipts (
    receipt_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    source_scope TEXT NOT NULL CHECK (source_scope IN ('private', 'task', 'project', 'team', 'organization')),
    target_scope TEXT NOT NULL CHECK (target_scope IN ('private', 'task', 'project', 'team', 'organization')),
    decision_action TEXT NOT NULL CHECK (decision_action IN ('retain_private', 'share_verbatim', 'share_redacted', 'share_aggregate', 'request_corroboration', 'reject_promotion')),
    deterministic_rationale TEXT NOT NULL,
    disclosure_transform TEXT NOT NULL,
    evidence_roots_json TEXT NOT NULL,
    independent_lineage_count INTEGER NOT NULL,
    is_authoritative_root INTEGER NOT NULL,
    is_tainted INTEGER NOT NULL,
    evidence_graph_digest TEXT NOT NULL,
    semantic_decision_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES ccp_promotion_candidates(candidate_id)
);

CREATE TABLE IF NOT EXISTS ccp_contest_events (
    contest_id TEXT PRIMARY KEY,
    projection_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    contested_by TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (projection_id) REFERENCES ccp_scope_projections(projection_id),
    FOREIGN KEY (candidate_id) REFERENCES ccp_promotion_candidates(candidate_id)
);

CREATE TABLE IF NOT EXISTS ccp_reversal_events (
    reversal_id TEXT PRIMARY KEY,
    contest_id TEXT NOT NULL,
    primary_projection_id TEXT NOT NULL,
    invalidated_projection_ids TEXT NOT NULL, -- JSON list
    reverted_at TEXT NOT NULL,
    audit_trail_preserved INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (contest_id) REFERENCES ccp_contest_events(contest_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Database-Enforced Immutability Triggers (Append-Only Enforcement)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TRIGGER IF NOT EXISTS trg_val_events_no_update
BEFORE UPDATE ON ccp_projection_validity_events
BEGIN
    SELECT RAISE(ABORT, 'ccp_projection_validity_events is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_val_events_no_delete
BEFORE DELETE ON ccp_projection_validity_events
BEGIN
    SELECT RAISE(ABORT, 'ccp_projection_validity_events is append-only: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_contest_events_no_update
BEFORE UPDATE ON ccp_contest_events
BEGIN
    SELECT RAISE(ABORT, 'ccp_contest_events is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_contest_events_no_delete
BEFORE DELETE ON ccp_contest_events
BEGIN
    SELECT RAISE(ABORT, 'ccp_contest_events is append-only: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_reversal_events_no_update
BEFORE UPDATE ON ccp_reversal_events
BEGIN
    SELECT RAISE(ABORT, 'ccp_reversal_events is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_reversal_events_no_delete
BEFORE DELETE ON ccp_reversal_events
BEGIN
    SELECT RAISE(ABORT, 'ccp_reversal_events is append-only: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_receipts_no_update
BEFORE UPDATE ON ccp_promotion_receipts
BEGIN
    SELECT RAISE(ABORT, 'ccp_promotion_receipts is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_receipts_no_delete
BEFORE DELETE ON ccp_promotion_receipts
BEGIN
    SELECT RAISE(ABORT, 'ccp_promotion_receipts is append-only: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_projections_no_update
BEFORE UPDATE ON ccp_scope_projections
BEGIN
    SELECT RAISE(ABORT, 'ccp_scope_projections is immutable: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_projections_no_delete
BEFORE DELETE ON ccp_scope_projections
BEGIN
    SELECT RAISE(ABORT, 'ccp_scope_projections is immutable: DELETE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_derivations_no_update
BEFORE UPDATE ON ccp_projection_derivations
BEGIN
    SELECT RAISE(ABORT, 'ccp_projection_derivations is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_derivations_no_delete
BEFORE DELETE ON ccp_projection_derivations
BEGIN
    SELECT RAISE(ABORT, 'ccp_projection_derivations is append-only: DELETE forbidden');
END;

-- ─────────────────────────────────────────────────────────────────────────────
-- Indices for fast traversal, lineage, and temporal validity lookups
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_edges_child ON ccp_evidence_edges(child_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_parent ON ccp_evidence_edges(parent_node_id);
CREATE INDEX IF NOT EXISTS idx_projections_temporal ON ccp_scope_projections(target_scope, valid_from);
CREATE INDEX IF NOT EXISTS idx_projections_cand ON ccp_scope_projections(candidate_id);
CREATE INDEX IF NOT EXISTS idx_val_events_proj_eff ON ccp_projection_validity_events(projection_id, effective_at);
CREATE INDEX IF NOT EXISTS idx_val_events_contest ON ccp_projection_validity_events(contest_id);
CREATE INDEX IF NOT EXISTS idx_deriv_parent ON ccp_projection_derivations(parent_projection_id);
CREATE INDEX IF NOT EXISTS idx_deriv_child ON ccp_projection_derivations(child_projection_id);
"""


def init_temporary_ccp_db(
    db_path: Optional[str | Path] = None, timeout: float = 5.0
) -> sqlite3.Connection:
    """Initialize an isolated, temporary SQLite database for the CCP experiment harness."""
    target = ":memory:" if db_path is None else str(db_path)
    if target != ":memory:":
        reject_live_memory_path(Path(target))
    conn = sqlite3.connect(target, timeout=timeout)
    conn.isolation_level = None  # Autocommit mode: explicit BEGIN IMMEDIATE / COMMIT
    conn.row_factory = sqlite3.Row
    conn.executescript(CCP_SCHEMA_SQL)
    return conn
