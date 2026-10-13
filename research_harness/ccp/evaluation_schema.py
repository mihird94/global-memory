"""Evaluation schema, validation routines, and statistical metric calculators for CCP.

Provides standardized data models and validation functions for independent held-out evaluation datasets,
along with numerator/denominator rate calculations and empirical bootstrap confidence intervals.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from research_harness.ccp.models import NodeType, PromotionAction, ScopeTier


@dataclass(frozen=True)
class EvalGroundTruth:
    expected_action: PromotionAction
    expected_transform: str
    authoritative_verdict: bool
    taint_expected: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_action": self.expected_action.value,
            "expected_transform": self.expected_transform,
            "authoritative_verdict": self.authoritative_verdict,
            "taint_expected": self.taint_expected,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    description: str
    memory_key: str
    statement: str
    source_scope: ScopeTier
    target_scope: ScopeTier
    authority: str
    effective_at: str
    expires_at: Optional[str]
    metadata: dict[str, Any]
    evidence_nodes: list[dict[str, Any]]
    evidence_edges: list[dict[str, Any]]
    ground_truth: EvalGroundTruth

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "description": self.description,
            "memory_key": self.memory_key,
            "statement": self.statement,
            "source_scope": self.source_scope.value,
            "target_scope": self.target_scope.value,
            "authority": self.authority,
            "effective_at": self.effective_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
            "evidence_nodes": self.evidence_nodes,
            "evidence_edges": self.evidence_edges,
            "ground_truth": self.ground_truth.to_dict(),
        }


@dataclass(frozen=True)
class EvalDataset:
    dataset_id: str
    version: str
    description: str
    author_id: str
    created_at: str
    frozen_hash: str
    adjudication_protocol: dict[str, Any]
    cases: list[EvalCase]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "description": self.description,
            "author_id": self.author_id,
            "created_at": self.created_at,
            "frozen_hash": self.frozen_hash,
            "adjudication_protocol": self.adjudication_protocol,
            "cases": [c.to_dict() for c in self.cases],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Schema Validation
# ──────────────────────────────────────────────────────────────────────────────

VALID_SCOPES = {"private", "task", "project", "team", "organization"}
VALID_ACTIONS = {
    "retain_private",
    "share_verbatim",
    "share_redacted",
    "share_aggregate",
    "request_corroboration",
    "reject_promotion",
}
VALID_TRANSFORMS = {"none", "verbatim", "redacted", "aggregate"}
VALID_NODE_TYPES = {
    "raw_tool_execution",
    "verified_system_fact",
    "agent_observation",
    "synthetic_generation",
    "external_web_fetch",
    "artifact_read",
    "unverified_rumor",
}
VALID_EDGE_RELATIONS = {
    "derived_from",
    "copied_from",
    "paraphrased_from",
    "summarizes",
    "contradicts",
    "corroborates",
}


def validate_evaluation_dataset(data: dict[str, Any]) -> list[str]:
    """
    Validates an evaluation dataset dictionary against structural and domain rules.
    Returns a list of validation error messages. Returns empty list if completely valid.
    """
    errors: list[str] = []

    # Required top-level keys
    required_top = [
        "dataset_id",
        "version",
        "description",
        "author_id",
        "created_at",
        "frozen_hash",
        "adjudication_protocol",
        "cases",
    ]
    for key in required_top:
        if key not in data:
            errors.append(f"Missing top-level required field: '{key}'")

    if errors:
        return errors

    # Top-level field types
    if not isinstance(data["dataset_id"], str) or not data["dataset_id"]:
        errors.append("Field 'dataset_id' must be a non-empty string")
    if not isinstance(data["frozen_hash"], str) or len(data["frozen_hash"]) != 64:
        errors.append("Field 'frozen_hash' must be a 64-character SHA-256 hex string")

    adj = data.get("adjudication_protocol", {})
    if not isinstance(adj, dict):
        errors.append("Field 'adjudication_protocol' must be an object")
    else:
        for adj_req in ["blinded", "adjudicator_count", "arbitration_rule"]:
            if adj_req not in adj:
                errors.append(f"Field 'adjudication_protocol' missing required key: '{adj_req}'")

    cases = data.get("cases", [])
    if not isinstance(cases, list) or len(cases) == 0:
        errors.append("Field 'cases' must be a non-empty list of evaluation cases")
        return errors

    seen_case_ids = set()
    for idx, c in enumerate(cases):
        prefix = f"cases[{idx}]"
        if not isinstance(c, dict):
            errors.append(f"{prefix} must be an object")
            continue

        cid = c.get("case_id")
        if not cid or not isinstance(cid, str):
            errors.append(f"{prefix} missing or invalid 'case_id'")
        elif cid in seen_case_ids:
            errors.append(f"{prefix} duplicate case_id '{cid}'")
        else:
            seen_case_ids.add(cid)

        # Scope validation
        ss = c.get("source_scope")
        ts = c.get("target_scope")
        if ss not in VALID_SCOPES:
            errors.append(f"{prefix} invalid source_scope '{ss}'")
        if ts not in VALID_SCOPES:
            errors.append(f"{prefix} invalid target_scope '{ts}'")

        # Ground truth validation
        gt = c.get("ground_truth")
        if not isinstance(gt, dict):
            errors.append(f"{prefix} missing or invalid 'ground_truth' object")
        else:
            ea = gt.get("expected_action")
            et = gt.get("expected_transform")
            if ea not in VALID_ACTIONS:
                errors.append(f"{prefix}.ground_truth invalid expected_action '{ea}'")
            if et not in VALID_TRANSFORMS:
                errors.append(f"{prefix}.ground_truth invalid expected_transform '{et}'")
            if "authoritative_verdict" not in gt or not isinstance(gt["authoritative_verdict"], bool):
                errors.append(f"{prefix}.ground_truth missing boolean 'authoritative_verdict'")
            if "taint_expected" not in gt or not isinstance(gt["taint_expected"], bool):
                errors.append(f"{prefix}.ground_truth missing boolean 'taint_expected'")

        # Evidence nodes validation
        enodes = c.get("evidence_nodes", [])
        if not isinstance(enodes, list) or len(enodes) == 0:
            errors.append(f"{prefix} evidence_nodes must be a non-empty list")
        else:
            for n_idx, node in enumerate(enodes):
                if not isinstance(node, dict):
                    errors.append(f"{prefix}.evidence_nodes[{n_idx}] must be an object")
                    continue
                nt = node.get("node_type")
                if nt not in VALID_NODE_TYPES:
                    errors.append(f"{prefix}.evidence_nodes[{n_idx}] invalid node_type '{nt}'")

        # Evidence edges validation
        eedges = c.get("evidence_edges", [])
        if isinstance(eedges, list):
            for e_idx, edge in enumerate(eedges):
                if not isinstance(edge, dict):
                    errors.append(f"{prefix}.evidence_edges[{e_idx}] must be an object")
                    continue
                rt = edge.get("relation_type")
                if rt not in VALID_EDGE_RELATIONS:
                    errors.append(f"{prefix}.evidence_edges[{e_idx}] invalid relation_type '{rt}'")

    return errors


# ──────────────────────────────────────────────────────────────────────────────
# Metric Calculations with Numerator / Denominator Reporting
# ──────────────────────────────────────────────────────────────────────────────

def compute_rate(numerator: int, denominator: int) -> dict[str, Any]:
    """
    Format a metric as a structured rate object with explicit numerator and denominator.
    Guarantees deterministic rounding and clean zero-denominator behavior.
    """
    rate = round(numerator / denominator, 4) if denominator > 0 else 0.0
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": rate,
    }


def compute_binary_classification_metrics(
    y_true: list[bool], y_pred: list[bool]
) -> dict[str, Any]:
    """
    Computes precision, recall, f1, false positive rate (FPR), and false negative rate (FNR)
    with explicit numerator and denominator reporting.
    """
    if len(y_true) != len(y_pred):
        raise ValueError(f"Length mismatch: y_true ({len(y_true)}) != y_pred ({len(y_pred)})")

    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt and yp)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if not yt and yp)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt and not yp)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if not yt and not yp)

    precision_info = compute_rate(tp, tp + fp)
    recall_info = compute_rate(tp, tp + fn)
    fpr_info = compute_rate(fp, fp + tn)
    fnr_info = compute_rate(fn, fn + tp)

    prec_val = precision_info["rate"]
    rec_val = recall_info["rate"]
    f1_val = round((2 * prec_val * rec_val) / (prec_val + rec_val), 4) if (prec_val + rec_val) > 0 else 0.0

    return {
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": precision_info,
        "recall": recall_info,
        "f1_score": f1_val,
        "false_positive_rate": fpr_info,
        "false_negative_rate": fnr_info,
    }


def bootstrap_confidence_interval(
    data: list[float],
    n_bootstrap: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """
    Calculates an empirical non-parametric bootstrap confidence interval for the sample mean.
    """
    if not data:
        return (0.0, 0.0)
    if len(data) == 1:
        val = round(float(data[0]), 4)
        return (val, val)

    rng = random.Random(seed)
    n = len(data)
    boot_means: list[float] = []

    for _ in range(n_bootstrap):
        sample = [rng.choice(data) for _ in range(n)]
        boot_means.append(sum(sample) / n)

    boot_means.sort()
    lower_pct = (1.0 - ci) / 2.0
    upper_pct = 1.0 - lower_pct

    lower_idx = int(lower_pct * n_bootstrap)
    upper_idx = min(int(upper_pct * n_bootstrap), n_bootstrap - 1)

    return (round(boot_means[lower_idx], 4), round(boot_means[upper_idx], 4))
