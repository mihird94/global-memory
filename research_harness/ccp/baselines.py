"""Baseline implementations for comparative promotion evaluation.

Baselines:
- B0: Always share verbatim (unguarded naive promotion)
- B1: Static regex / DLP filter (lexical pattern matching only)
- B2: Distinct-agent-count corroboration (counts unique agent IDs without DAG ancestry)
- B3: Common-cause-aware CCP gate (full CCPEngine)
"""

from __future__ import annotations

import re
from typing import Any

from research_harness.ccp.engine import CCPEngine
from research_harness.ccp.models import (
    NodeType,
    PromotionAction,
    PromotionCandidate,
    PromotionReceipt,
    ScopeTier,
)


class BaselineB0AlwaysShare:
    """B0: Naive unconstrained baseline that shares every candidate verbatim."""

    def __init__(self, engine: CCPEngine):
        self.engine = engine

    def evaluate(self, candidate: PromotionCandidate) -> PromotionAction:
        return PromotionAction.SHARE_VERBATIM


class BaselineB1StaticRegexDLP:
    """B1: Lexical regex/DLP filter. Redacts or rejects based on patterns, blind to ancestry."""

    def __init__(self, engine: CCPEngine):
        self.engine = engine

    def evaluate(self, candidate: PromotionCandidate) -> PromotionAction:
        clean, was_redacted = self.engine.redact_statement(candidate.statement)
        if was_redacted:
            return PromotionAction.SHARE_REDACTED
        return PromotionAction.SHARE_VERBATIM


class BaselineB2DistinctAgentCount:
    """
    B2: Distinct-agent-count corroboration.
    Counts unique agent IDs among direct supporting nodes.
    Permits a single authoritative verified source to qualify alone.
    If >= 2 distinct agents assert, promotes verbatim (or redacted if regex hits).
    Vulnerable to echo-chamber paraphrases and source laundering because it checks
    only agent author counts without causal DAG root tracing.
    """

    def __init__(self, engine: CCPEngine):
        self.engine = engine

    def evaluate(self, candidate: PromotionCandidate) -> PromotionAction:
        agent_ids = set()
        has_authoritative = False
        for nid in candidate.evidence_node_ids:
            node = self.engine._get_node(nid)
            if node:
                agent_ids.add(node.agent_id)
                if node.is_authoritative or node.node_type in (
                    NodeType.VERIFIED_SYSTEM,
                    NodeType.OWNER_INSTRUCTION,
                ):
                    has_authoritative = True

        clean, was_redacted = self.engine.redact_statement(candidate.statement)

        # Single authoritative source qualifies alone; otherwise requires >= 2 distinct agents for team/org
        if candidate.target_scope >= ScopeTier.TEAM:
            if not has_authoritative and len(agent_ids) < 2:
                return PromotionAction.REQUEST_CORROBORATION

        if was_redacted:
            return PromotionAction.SHARE_REDACTED
        return PromotionAction.SHARE_VERBATIM


class BaselineB3CCPGate:
    """B3: Common-cause-aware CCP gate with causal DAG analysis and authoritative exceptions."""

    def __init__(self, engine: CCPEngine):
        self.engine = engine

    def evaluate(self, candidate: PromotionCandidate) -> PromotionAction:
        receipt = self.engine.evaluate_promotion(candidate)
        return receipt.decision_action
