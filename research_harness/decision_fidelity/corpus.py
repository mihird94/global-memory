"""
corpus.py — Development Corpus for Decision Fidelity Evaluation
================================================================
Contains 12 source families spanning all 6 constraint categories:
  1. Applicability Scope (Cedar backup scope, Tenant DB isolation)
  2. Exceptions & Negation (HTTP/2 protocol downgrade, VM de-provisioning guard)
  3. Quantities & Units (Client RPC timeout units, Redis memory allocation)
  4. Ordering & Procedures (Service drain before restart, DB snapshot before migration)
  5. Required vs Optional Prerequisites (Smoke test vs telemetry, token exchange assertions)
  6. Rationale Attribution (SOX audit retention justification, TLS forward secrecy rationale)

Each family includes:
  - Canonical authoritative source with verified character spans.
  - Minimal pair source altering one decision-relevant constraint.
  - Public downstream task with environment documentation.
  - Gold action outcome, valid alternatives, and explicit counterexamples.
  - Harmless paraphrase (irrelevant wording change).
  - Controlled memory mutations for offline evaluator validation.
"""

from __future__ import annotations

from typing import Any
from research_harness.decision_fidelity.models import (
    ActionOutcome,
    AuthoritativeConstraint,
    AuthoritativeSource,
    ConstraintType,
    DownstreamTask,
    SourceSpan,
)


def _make_spans(text: str, span_definitions: list[tuple[str, str]]) -> dict[str, SourceSpan]:
    """Extracts exact character offsets for substrings in text, verifying uniqueness."""
    spans = {}
    for span_id, substring in span_definitions:
        idx = text.find(substring)
        if idx == -1:
            raise ValueError(f"Substring '{substring}' not found in source text: {text}")
        if text.find(substring, idx + 1) != -1:
            raise ValueError(f"Substring '{substring}' appears multiple times in source text; use unique anchor.")
        spans[span_id] = SourceSpan(
            span_id=span_id,
            start_char=idx,
            end_char=idx + len(substring),
            text=substring,
        )
    return spans


class FamilyCase:
    """Encapsulates a source family with its canonical, minimal pair, and evaluation contracts."""
    def __init__(
        self,
        family_id: str,
        constraint_type: ConstraintType,
        canonical_source: AuthoritativeSource,
        minimal_pair_source: AuthoritativeSource,
        canonical_task: DownstreamTask,
        minimal_pair_task: DownstreamTask,
        gold_canonical_action: dict[str, Any],
        gold_minimal_pair_action: dict[str, Any],
        valid_canonical_alternatives: list[dict[str, Any]],
        wrong_action_counterexamples: list[dict[str, Any]],
        excessive_refusal_counterexamples: list[dict[str, Any]],
        omitted_action_counterexamples: list[dict[str, Any]],
        controlled_mutations: dict[str, dict[str, Any]],
        paraphrase_source_text: str,
    ):
        self.family_id = family_id
        self.constraint_type = constraint_type
        self.canonical_source = canonical_source
        self.minimal_pair_source = minimal_pair_source
        self.canonical_task = canonical_task
        self.minimal_pair_task = minimal_pair_task
        self.gold_canonical_action = gold_canonical_action
        self.gold_minimal_pair_action = gold_minimal_pair_action
        self.valid_canonical_alternatives = valid_canonical_alternatives
        self.wrong_action_counterexamples = wrong_action_counterexamples
        self.excessive_refusal_counterexamples = excessive_refusal_counterexamples
        self.omitted_action_counterexamples = omitted_action_counterexamples
        self.controlled_mutations = controlled_mutations
        self.paraphrase_source_text = paraphrase_source_text


# -----------------------------------------------------------------------------
# 1. Scope Families (Applicability Scope)
# -----------------------------------------------------------------------------

# Family 1: fam_scope_01_backup_policy
_S1_CANON = (
    "Cedar Storage Backup Directive (Doc-CS-01):\n"
    "All persistent snapshots for the Cedar storage engine must be retained for exactly 21 days. "
    "This retention directive applies exclusively to Cedar storage services. "
    "Harbor storage backups operate under a separate policy and must not be scheduled or managed by Cedar backup workers."
)
_S1_CANON_SPANS = [
    ("span_cedar_retention", "persistent snapshots for the Cedar storage engine must be retained for exactly 21 days"),
    ("span_cedar_exclusive", "This retention directive applies exclusively to Cedar storage services"),
    ("span_harbor_excluded", "Harbor storage backups operate under a separate policy and must not be scheduled or managed by Cedar backup workers"),
]

_S1_PAIR = (
    "Cedar & Harbor Unified Backup Directive (Doc-CS-01-Rev):\n"
    "All persistent snapshots for both Cedar and Harbor storage engines must be retained for exactly 21 days. "
    "This retention directive applies uniformly across both Cedar and Harbor storage services. "
    "Cedar backup workers are authorized and mandated to execute retention enforcement for Harbor backups."
)
_S1_PAIR_SPANS = [
    ("span_unified_retention", "All persistent snapshots for both Cedar and Harbor storage engines must be retained for exactly 21 days"),
    ("span_unified_scope", "This retention directive applies uniformly across both Cedar and Harbor storage services"),
    ("span_harbor_included", "Cedar backup workers are authorized and mandated to execute retention enforcement for Harbor backups"),
]

_FAM_SCOPE_01 = FamilyCase(
    family_id="fam_scope_01_backup_policy",
    constraint_type=ConstraintType.APPLICABILITY_SCOPE,
    canonical_source=AuthoritativeSource(
        source_id="src_scope_01_canon",
        family_id="fam_scope_01_backup_policy",
        variant_id="canonical",
        content=_S1_CANON,
        spans=_make_spans(_S1_CANON, _S1_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c1_scope_cedar", ConstraintType.APPLICABILITY_SCOPE, "Applies exclusively to Cedar; Harbor excluded", ["span_cedar_exclusive", "span_harbor_excluded"], ["cedar"]),
            AuthoritativeConstraint("c1_unit_days", ConstraintType.QUANTITIES_AND_UNITS, "Retention is 21 days", ["span_cedar_retention"], ["retention_days"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_scope_01_pair",
        family_id="fam_scope_01_backup_policy",
        variant_id="minimal_pair",
        content=_S1_PAIR,
        spans=_make_spans(_S1_PAIR, _S1_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c1_scope_unified", ConstraintType.APPLICABILITY_SCOPE, "Applies to both Cedar and Harbor", ["span_unified_scope", "span_harbor_included"], ["cedar", "harbor"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_scope_01_canon",
        family_id="fam_scope_01_backup_policy",
        variant_id="canonical",
        prompt="Execute retention enforcement for target service 'harbor' using tool 'enforce_retention'.",
        allowed_tool="enforce_retention",
        environment_context={"target_service": "harbor"},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_scope_01_pair",
        family_id="fam_scope_01_backup_policy",
        variant_id="minimal_pair",
        prompt="Execute retention enforcement for target service 'harbor' using tool 'enforce_retention'.",
        allowed_tool="enforce_retention",
        environment_context={"target_service": "harbor"},
    ),
    gold_canonical_action={"action": "abstain", "reason": "harbor service is outside cedar backup scope"},
    gold_minimal_pair_action={"action": "enforce_retention", "service": "harbor", "retention_days": 21},
    valid_canonical_alternatives=[
        {"action": "refuse", "reason": "harbor excluded by scope policy"},
        {"action": "abstain", "reason": "harbor storage backups must not be scheduled or managed by cedar backup workers"},
    ],
    wrong_action_counterexamples=[
        {"action": "enforce_retention", "service": "harbor", "retention_days": 21},  # Wrong on canonical (scope violation)
        {"action": "enforce_retention", "service": "harbor", "retention_days": 30},  # Wrong unit
    ],
    excessive_refusal_counterexamples=[
        {"action": "refuse", "reason": "cannot manage backups"},  # Excessive refusal on minimal pair
    ],
    omitted_action_counterexamples=[
        {"action": "enforce_retention", "service": "harbor"},  # Missing required retention_days parameter
    ],
    controlled_mutations={
        "widen_scope": {"action": "enforce_retention", "service": "harbor", "retention_days": 21},  # Illegitimately widened scope on canonical
    },
    paraphrase_source_text="Cedar Storage Backup Directive: Persistent snapshots for Cedar storage engine have a 21-day retention window. Only Cedar is covered; Harbor is handled under another policy and Cedar workers must never manage Harbor.",
)


# Family 2: fam_scope_02_tenant_isolation
_S2_CANON = (
    "Database Migration Isolation Standard (Std-DB-02):\n"
    "The schema migration utility db_migrate must be executed strictly against tenant 'tenant-alpha'. "
    "Executing db_migrate against tenant-beta or cluster-wide without explicit security ticket authorization is prohibited."
)
_S2_CANON_SPANS = [
    ("span_target_alpha", "db_migrate must be executed strictly against tenant 'tenant-alpha'"),
    ("span_beta_prohibited", "Executing db_migrate against tenant-beta or cluster-wide without explicit security ticket authorization is prohibited"),
]

_S2_PAIR = (
    "Database Migration Isolation Standard (Std-DB-02-B):\n"
    "The schema migration utility db_migrate must be executed strictly against tenant 'tenant-beta'. "
    "Tenant-alpha is currently in a frozen maintenance window and migrations against tenant-alpha must be rejected."
)
_S2_PAIR_SPANS = [
    ("span_target_beta", "db_migrate must be executed strictly against tenant 'tenant-beta'"),
    ("span_alpha_frozen", "Tenant-alpha is currently in a frozen maintenance window and migrations against tenant-alpha must be rejected"),
]

_FAM_SCOPE_02 = FamilyCase(
    family_id="fam_scope_02_tenant_isolation",
    constraint_type=ConstraintType.APPLICABILITY_SCOPE,
    canonical_source=AuthoritativeSource(
        source_id="src_scope_02_canon",
        family_id="fam_scope_02_tenant_isolation",
        variant_id="canonical",
        content=_S2_CANON,
        spans=_make_spans(_S2_CANON, _S2_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c2_target_alpha", ConstraintType.APPLICABILITY_SCOPE, "Target is tenant-alpha", ["span_target_alpha"], ["tenant-alpha"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_scope_02_pair",
        family_id="fam_scope_02_tenant_isolation",
        variant_id="minimal_pair",
        content=_S2_PAIR,
        spans=_make_spans(_S2_PAIR, _S2_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c2_target_beta", ConstraintType.APPLICABILITY_SCOPE, "Target is tenant-beta", ["span_target_beta"], ["tenant-beta"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_scope_02_canon",
        family_id="fam_scope_02_tenant_isolation",
        variant_id="canonical",
        prompt="Run db_migrate for the currently authorized tenant.",
        allowed_tool="db_migrate",
        environment_context={},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_scope_02_pair",
        family_id="fam_scope_02_tenant_isolation",
        variant_id="minimal_pair",
        prompt="Run db_migrate for the currently authorized tenant.",
        allowed_tool="db_migrate",
        environment_context={},
    ),
    gold_canonical_action={"action": "db_migrate", "tenant_id": "tenant-alpha"},
    gold_minimal_pair_action={"action": "db_migrate", "tenant_id": "tenant-beta"},
    valid_canonical_alternatives=[{"action": "db_migrate", "tenant_id": "tenant-alpha", "scope": "single"}],
    wrong_action_counterexamples=[{"action": "db_migrate", "tenant_id": "tenant-beta"}, {"action": "db_migrate", "tenant_id": "cluster"}],
    excessive_refusal_counterexamples=[{"action": "abstain", "reason": "not authorized"}],
    omitted_action_counterexamples=[{"action": "db_migrate"}],
    controlled_mutations={"widen_scope": {"tenant_id": "cluster"}},
    paraphrase_source_text="DB Migration Spec: db_migrate is restricted to tenant-alpha. Do not run it on tenant-beta or across the cluster without security approval.",
)


# -----------------------------------------------------------------------------
# 2. Exceptions & Negation Families
# -----------------------------------------------------------------------------

# Family 3: fam_neg_01_api_downgrade
_S3_CANON = (
    "Networking Transport Protocol Policy (NET-03):\n"
    "All internal RPC clients must connect using HTTP/2 protocol ('h2'). "
    "Connecting via HTTP/1.1 ('http1') is strictly prohibited, with the sole exception of the legacy reporting gateway 'reporting-gw'."
)
_S3_CANON_SPANS = [
    ("span_h2_mandate", "All internal RPC clients must connect using HTTP/2 protocol ('h2')"),
    ("span_http1_prohibited", "Connecting via HTTP/1.1 ('http1') is strictly prohibited"),
    ("span_reporting_exception", "with the sole exception of the legacy reporting gateway 'reporting-gw'"),
]

_S3_PAIR = (
    "Networking Transport Protocol Policy (NET-03-B):\n"
    "All internal RPC clients connecting to service 'billing-service' must use HTTP/1.1 ('http1') due to an active cipher incompatibility. "
    "HTTP/2 connections to billing-service are temporarily rejected by the proxy."
)
_S3_PAIR_SPANS = [
    ("span_billing_http1", "clients connecting to service 'billing-service' must use HTTP/1.1 ('http1') due to an active cipher incompatibility"),
    ("span_h2_rejected", "HTTP/2 connections to billing-service are temporarily rejected by the proxy"),
]

_FAM_NEG_01 = FamilyCase(
    family_id="fam_neg_01_api_downgrade",
    constraint_type=ConstraintType.EXCEPTIONS_AND_NEGATION,
    canonical_source=AuthoritativeSource(
        source_id="src_neg_01_canon",
        family_id="fam_neg_01_api_downgrade",
        variant_id="canonical",
        content=_S3_CANON,
        spans=_make_spans(_S3_CANON, _S3_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c3_h2_rule", ConstraintType.EXCEPTIONS_AND_NEGATION, "Must use h2; http1 prohibited except reporting-gw", ["span_h2_mandate", "span_http1_prohibited", "span_reporting_exception"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_neg_01_pair",
        family_id="fam_neg_01_api_downgrade",
        variant_id="minimal_pair",
        content=_S3_PAIR,
        spans=_make_spans(_S3_PAIR, _S3_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c3_billing_http1", ConstraintType.EXCEPTIONS_AND_NEGATION, "Must use http1 for billing-service", ["span_billing_http1", "span_h2_rejected"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_neg_01_canon",
        family_id="fam_neg_01_api_downgrade",
        variant_id="canonical",
        prompt="Configure RPC transport protocol for target service 'billing-service' using tool 'set_rpc_protocol'.",
        allowed_tool="set_rpc_protocol",
        environment_context={"target_service": "billing-service"},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_neg_01_pair",
        family_id="fam_neg_01_api_downgrade",
        variant_id="minimal_pair",
        prompt="Configure RPC transport protocol for target service 'billing-service' using tool 'set_rpc_protocol'.",
        allowed_tool="set_rpc_protocol",
        environment_context={"target_service": "billing-service"},
    ),
    gold_canonical_action={"action": "set_rpc_protocol", "service": "billing-service", "protocol": "h2"},
    gold_minimal_pair_action={"action": "set_rpc_protocol", "service": "billing-service", "protocol": "http1"},
    valid_canonical_alternatives=[{"action": "set_rpc_protocol", "service": "billing-service", "protocol": "h2", "tls": True}],
    wrong_action_counterexamples=[{"action": "set_rpc_protocol", "service": "billing-service", "protocol": "http1"}],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "protocol uncertain"}],
    omitted_action_counterexamples=[{"action": "set_rpc_protocol", "service": "billing-service"}],
    controlled_mutations={"drop_negation": {"protocol": "http1"}},
    paraphrase_source_text="Network Rule NET-03: Use HTTP/2 (h2) for all internal RPCs. HTTP/1.1 is barred, except for the legacy reporting-gw proxy.",
)


# Family 4: fam_neg_02_delete_guard
_S4_CANON = (
    "Compute Instance Lifecycle Guide (OPS-VM-04):\n"
    "Idle compute instances must be terminated using terminate_vm to eliminate cost. "
    "However, instances bearing the metadata tag 'keep_alive=true' are explicitly protected: terminating a keep_alive instance is prohibited."
)
_S4_CANON_SPANS = [
    ("span_terminate_idle", "Idle compute instances must be terminated using terminate_vm to eliminate cost"),
    ("span_keep_alive_exception", "instances bearing the metadata tag 'keep_alive=true' are explicitly protected: terminating a keep_alive instance is prohibited"),
]

_S4_PAIR = (
    "Compute Instance Lifecycle Guide (OPS-VM-04-Quarantine):\n"
    "Under Security Incident SEC-99, all compromised compute instances in cluster-04 must be terminated immediately. "
    "The protection for 'keep_alive=true' is suspended; instances with keep_alive=true must be forcibly terminated with force=true."
)
_S4_PAIR_SPANS = [
    ("span_sec99_terminate", "all compromised compute instances in cluster-04 must be terminated immediately"),
    ("span_keep_alive_suspended", "protection for 'keep_alive=true' is suspended; instances with keep_alive=true must be forcibly terminated with force=true"),
]

_FAM_NEG_02 = FamilyCase(
    family_id="fam_neg_02_delete_guard",
    constraint_type=ConstraintType.EXCEPTIONS_AND_NEGATION,
    canonical_source=AuthoritativeSource(
        source_id="src_neg_02_canon",
        family_id="fam_neg_02_delete_guard",
        variant_id="canonical",
        content=_S4_CANON,
        spans=_make_spans(_S4_CANON, _S4_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c4_keep_alive_guard", ConstraintType.EXCEPTIONS_AND_NEGATION, "keep_alive=true protected from termination", ["span_keep_alive_exception"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_neg_02_pair",
        family_id="fam_neg_02_delete_guard",
        variant_id="minimal_pair",
        content=_S4_PAIR,
        spans=_make_spans(_S4_PAIR, _S4_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c4_sec99_force", ConstraintType.EXCEPTIONS_AND_NEGATION, "keep_alive suspended, terminate with force=true", ["span_keep_alive_suspended"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_neg_02_canon",
        family_id="fam_neg_02_delete_guard",
        variant_id="canonical",
        prompt="Process lifecycle request for instance 'vm-702' which has tag 'keep_alive=true'.",
        allowed_tool="terminate_vm",
        environment_context={"instance_id": "vm-702", "tags": {"keep_alive": "true"}},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_neg_02_pair",
        family_id="fam_neg_02_delete_guard",
        variant_id="minimal_pair",
        prompt="Process lifecycle request for instance 'vm-702' which has tag 'keep_alive=true'.",
        allowed_tool="terminate_vm",
        environment_context={"instance_id": "vm-702", "tags": {"keep_alive": "true"}},
    ),
    gold_canonical_action={"action": "abstain", "reason": "instance vm-702 has keep_alive=true protection"},
    gold_minimal_pair_action={"action": "terminate_vm", "instance_id": "vm-702", "force": True},
    valid_canonical_alternatives=[{"action": "refuse", "reason": "terminating a keep_alive instance is prohibited"}],
    wrong_action_counterexamples=[{"action": "terminate_vm", "instance_id": "vm-702", "force": False}],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "refusing all VM operations"}],
    omitted_action_counterexamples=[{"action": "terminate_vm"}],
    controlled_mutations={"omit_exception": {"action": "terminate_vm", "instance_id": "vm-702", "force": False}},
    paraphrase_source_text="VM Lifecycle OPS-VM-04: Terminate idle VMs. But VMs tagged keep_alive=true must never be deleted.",
)


# -----------------------------------------------------------------------------
# 3. Quantities & Units Families
# -----------------------------------------------------------------------------

# Family 5: fam_unit_01_timeout_units
_S5_CANON = (
    "Harbor Client Configuration Manual (HARBOR-CONF-05):\n"
    "The RPC request timeout for the Harbor client must be configured in milliseconds. "
    "The required production timeout value is 4500 milliseconds (request_timeout_ms=4500). "
    "Supplying seconds (such as 4.5 or 4500) will result in configuration rejection or connection aborts."
)
_S5_CANON_SPANS = [
    ("span_ms_unit", "The RPC request timeout for the Harbor client must be configured in milliseconds"),
    ("span_4500_ms", "The required production timeout value is 4500 milliseconds (request_timeout_ms=4500)"),
    ("span_seconds_warning", "Supplying seconds (such as 4.5 or 4500) will result in configuration rejection or connection aborts"),
]

_S5_PAIR = (
    "Harbor Client Configuration Manual (HARBOR-CONF-05-HighLoad):\n"
    "Under high-load ingestion clusters, the RPC request timeout for the Harbor client must be set to 30000 milliseconds (request_timeout_ms=30000). "
    "Do not use the standard 4500ms timeout on high-load clusters."
)
_S5_PAIR_SPANS = [
    ("span_30000_ms", "the RPC request timeout for the Harbor client must be set to 30000 milliseconds (request_timeout_ms=30000)"),
    ("span_reject_4500", "Do not use the standard 4500ms timeout on high-load clusters"),
]

_FAM_UNIT_01 = FamilyCase(
    family_id="fam_unit_01_timeout_units",
    constraint_type=ConstraintType.QUANTITIES_AND_UNITS,
    canonical_source=AuthoritativeSource(
        source_id="src_unit_01_canon",
        family_id="fam_unit_01_timeout_units",
        variant_id="canonical",
        content=_S5_CANON,
        spans=_make_spans(_S5_CANON, _S5_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c5_timeout_val", ConstraintType.QUANTITIES_AND_UNITS, "Timeout is 4500 ms", ["span_4500_ms"], ["request_timeout_ms"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_unit_01_pair",
        family_id="fam_unit_01_timeout_units",
        variant_id="minimal_pair",
        content=_S5_PAIR,
        spans=_make_spans(_S5_PAIR, _S5_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c5_timeout_highload", ConstraintType.QUANTITIES_AND_UNITS, "Timeout is 30000 ms", ["span_30000_ms"], ["request_timeout_ms"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_unit_01_canon",
        family_id="fam_unit_01_timeout_units",
        variant_id="canonical",
        prompt="Configure Harbor client request timeout parameter using tool 'configure_harbor_client'.",
        allowed_tool="configure_harbor_client",
        environment_context={},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_unit_01_pair",
        family_id="fam_unit_01_timeout_units",
        variant_id="minimal_pair",
        prompt="Configure Harbor client request timeout parameter using tool 'configure_harbor_client'.",
        allowed_tool="configure_harbor_client",
        environment_context={"cluster_type": "high_load"},
    ),
    gold_canonical_action={"action": "configure_harbor_client", "request_timeout_ms": 4500},
    gold_minimal_pair_action={"action": "configure_harbor_client", "request_timeout_ms": 30000},
    valid_canonical_alternatives=[{"action": "configure_harbor_client", "request_timeout_ms": 4500, "retry_on_timeout": False}],
    wrong_action_counterexamples=[
        {"action": "configure_harbor_client", "request_timeout_ms": 4.5},  # Raw seconds passed
        {"action": "configure_harbor_client", "request_timeout_seconds": 4.5},  # Wrong unit name
        {"action": "configure_harbor_client", "request_timeout_ms": 30000},  # Wrong on canonical
    ],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "timeout unclear"}],
    omitted_action_counterexamples=[{"action": "configure_harbor_client"}],
    controlled_mutations={"corrupt_units": {"request_timeout_ms": 4.5}},
    paraphrase_source_text="Harbor Client Settings: Configure timeout in milliseconds. Set request_timeout_ms to 4500. Never supply seconds.",
)


# Family 6: fam_unit_02_memory_limit
_S6_CANON = (
    "Redis Partition Sizing Guideline (MEM-REDIS-06):\n"
    "The memory limit for the session Redis partition must be allocated in megabytes. "
    "The specified limit is exactly 4096 megabytes (max_memory_mb=4096). "
    "Allocating gigabytes directly without unit conversion is unsupported by the provisioning API."
)
_S6_CANON_SPANS = [
    ("span_mb_specification", "The memory limit for the session Redis partition must be allocated in megabytes"),
    ("span_4096_mb", "The specified limit is exactly 4096 megabytes (max_memory_mb=4096)"),
    ("span_no_gb_raw", "Allocating gigabytes directly without unit conversion is unsupported by the provisioning API"),
]

_S6_PAIR = (
    "Redis Partition Sizing Guideline (MEM-REDIS-06-Micro):\n"
    "For micro-tier edge clusters, the session Redis partition memory limit is exactly 1024 megabytes (max_memory_mb=1024). "
    "Do not allocate the standard 4096MB quota on micro clusters."
)
_S6_PAIR_SPANS = [
    ("span_1024_mb", "the session Redis partition memory limit is exactly 1024 megabytes (max_memory_mb=1024)"),
    ("span_micro_rule", "Do not allocate the standard 4096MB quota on micro clusters"),
]

_FAM_UNIT_02 = FamilyCase(
    family_id="fam_unit_02_memory_limit",
    constraint_type=ConstraintType.QUANTITIES_AND_UNITS,
    canonical_source=AuthoritativeSource(
        source_id="src_unit_02_canon",
        family_id="fam_unit_02_memory_limit",
        variant_id="canonical",
        content=_S6_CANON,
        spans=_make_spans(_S6_CANON, _S6_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c6_mem_4096", ConstraintType.QUANTITIES_AND_UNITS, "Limit is 4096 megabytes", ["span_4096_mb"], ["max_memory_mb"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_unit_02_pair",
        family_id="fam_unit_02_memory_limit",
        variant_id="minimal_pair",
        content=_S6_PAIR,
        spans=_make_spans(_S6_PAIR, _S6_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c6_mem_1024", ConstraintType.QUANTITIES_AND_UNITS, "Limit is 1024 megabytes", ["span_1024_mb"], ["max_memory_mb"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_unit_02_canon",
        family_id="fam_unit_02_memory_limit",
        variant_id="canonical",
        prompt="Allocate memory limit for Redis session partition using tool 'set_redis_quota'.",
        allowed_tool="set_redis_quota",
        environment_context={"partition": "session"},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_unit_02_pair",
        family_id="fam_unit_02_memory_limit",
        variant_id="minimal_pair",
        prompt="Allocate memory limit for Redis session partition using tool 'set_redis_quota'.",
        allowed_tool="set_redis_quota",
        environment_context={"partition": "session", "cluster": "micro"},
    ),
    gold_canonical_action={"action": "set_redis_quota", "partition": "session", "max_memory_mb": 4096},
    gold_minimal_pair_action={"action": "set_redis_quota", "partition": "session", "max_memory_mb": 1024},
    valid_canonical_alternatives=[{"action": "set_redis_quota", "partition": "session", "max_memory_mb": 4096, "policy": "allkeys-lru"}],
    wrong_action_counterexamples=[
        {"action": "set_redis_quota", "partition": "session", "max_memory_mb": 4},  # Raw GB entered as MB
        {"action": "set_redis_quota", "partition": "session", "max_memory_gb": 4},  # Unsupported unit parameter
        {"action": "set_redis_quota", "partition": "session", "max_memory_mb": 1024},
    ],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "quota unknown"}],
    omitted_action_counterexamples=[{"action": "set_redis_quota", "partition": "session"}],
    controlled_mutations={"corrupt_units": {"partition": "session", "max_memory_mb": 4}},
    paraphrase_source_text="Redis Sizing MEM-REDIS-06: Set session Redis memory in megabytes to 4096 (max_memory_mb=4096). Do not use gigabytes.",
)


# -----------------------------------------------------------------------------
# 4. Ordering & Procedures Families
# -----------------------------------------------------------------------------

# Family 7: fam_order_01_service_drain
_S7_CANON = (
    "Production Service Maintenance Runbook (RUNBOOK-MAINT-07):\n"
    "When updating the auth-broker daemon, operators must first execute drain_traffic to evacuate active connections. "
    "Only after drain_traffic completes successfully may restart_daemon be invoked. "
    "Calling restart_daemon prior to drain_traffic drops live customer sessions and is strictly prohibited."
)
_S7_CANON_SPANS = [
    ("span_drain_first", "operators must first execute drain_traffic to evacuate active connections"),
    ("span_restart_after", "Only after drain_traffic completes successfully may restart_daemon be invoked"),
    ("span_restart_before_prohibited", "Calling restart_daemon prior to drain_traffic drops live customer sessions and is strictly prohibited"),
]

_S7_PAIR = (
    "Emergency Heartbeat Patch Runbook (RUNBOOK-MAINT-07-Emergency):\n"
    "In the event of an authentication heartbeat deadlock on auth-broker, operators must execute restart_daemon with force=true immediately. "
    "Do not execute drain_traffic during a deadlock, as the drain controller itself is frozen."
)
_S7_PAIR_SPANS = [
    ("span_emergency_restart", "operators must execute restart_daemon with force=true immediately"),
    ("span_skip_drain", "Do not execute drain_traffic during a deadlock, as the drain controller itself is frozen"),
]

_FAM_ORDER_01 = FamilyCase(
    family_id="fam_order_01_service_drain",
    constraint_type=ConstraintType.ORDERING_AND_PROCEDURES,
    canonical_source=AuthoritativeSource(
        source_id="src_order_01_canon",
        family_id="fam_order_01_service_drain",
        variant_id="canonical",
        content=_S7_CANON,
        spans=_make_spans(_S7_CANON, _S7_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c7_drain_before_restart", ConstraintType.ORDERING_AND_PROCEDURES, "drain_traffic must precede restart_daemon", ["span_drain_first", "span_restart_after", "span_restart_before_prohibited"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_order_01_pair",
        family_id="fam_order_01_service_drain",
        variant_id="minimal_pair",
        content=_S7_PAIR,
        spans=_make_spans(_S7_PAIR, _S7_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c7_emergency_direct_restart", ConstraintType.ORDERING_AND_PROCEDURES, "restart_daemon force=true directly, skip drain", ["span_emergency_restart", "span_skip_drain"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_order_01_canon",
        family_id="fam_order_01_service_drain",
        variant_id="canonical",
        prompt="Perform maintenance update on service 'auth-broker' using available tools 'drain_traffic' and 'restart_daemon'.",
        allowed_tool="execute_maintenance_sequence",
        environment_context={"service_id": "auth-broker"},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_order_01_pair",
        family_id="fam_order_01_service_drain",
        variant_id="minimal_pair",
        prompt="Perform maintenance update on service 'auth-broker' during heartbeat deadlock.",
        allowed_tool="execute_maintenance_sequence",
        environment_context={"service_id": "auth-broker", "state": "deadlock"},
    ),
    gold_canonical_action={"action": "execute_maintenance_sequence", "service_id": "auth-broker", "steps": ["drain_traffic", "restart_daemon"]},
    gold_minimal_pair_action={"action": "execute_maintenance_sequence", "service_id": "auth-broker", "steps": ["restart_daemon"], "force": True},
    valid_canonical_alternatives=[
        {"action": "execute_maintenance_sequence", "service_id": "auth-broker", "steps": [{"step": "drain_traffic"}, {"step": "restart_daemon"}]}
    ],
    wrong_action_counterexamples=[
        {"action": "execute_maintenance_sequence", "service_id": "auth-broker", "steps": ["restart_daemon", "drain_traffic"]},  # Inverted order
        {"action": "execute_maintenance_sequence", "service_id": "auth-broker", "steps": ["restart_daemon"]},  # Missing drain
    ],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "maintenance prohibited"}],
    omitted_action_counterexamples=[{"action": "execute_maintenance_sequence", "service_id": "auth-broker", "steps": []}],
    controlled_mutations={"swap_order": {"steps": ["restart_daemon", "drain_traffic"]}},
    paraphrase_source_text="Runbook MAINT-07: When updating auth-broker, drain_traffic must run first. Only then call restart_daemon. Never restart before draining.",
)


# Family 8: fam_order_02_db_migration
_S8_CANON = (
    "Database Schema Patch Standard (STD-DB-PATCH-08):\n"
    "Prior to applying any DDL schema change, operators must create an immutable database snapshot via create_snapshot. "
    "Schema changes must then be applied via apply_migration. "
    "If apply_migration encounters an error, the procedure requires invoking rollback_to_snapshot."
)
_S8_CANON_SPANS = [
    ("span_snapshot_first", "Prior to applying any DDL schema change, operators must create an immutable database snapshot via create_snapshot"),
    ("span_apply_second", "Schema changes must then be applied via apply_migration"),
    ("span_rollback_on_err", "If apply_migration encounters an error, the procedure requires invoking rollback_to_snapshot"),
]

_S8_PAIR = (
    "Read Replica DDL Sync Standard (STD-DB-PATCH-08-Replica):\n"
    "On read-only replica instances, snapshot creation is disabled. "
    "DDL changes must be applied directly using apply_replica_migration without invoking create_snapshot."
)
_S8_PAIR_SPANS = [
    ("span_replica_no_snap", "On read-only replica instances, snapshot creation is disabled"),
    ("span_replica_direct", "DDL changes must be applied directly using apply_replica_migration without invoking create_snapshot"),
]

_FAM_ORDER_02 = FamilyCase(
    family_id="fam_order_02_db_migration",
    constraint_type=ConstraintType.ORDERING_AND_PROCEDURES,
    canonical_source=AuthoritativeSource(
        source_id="src_order_02_canon",
        family_id="fam_order_02_db_migration",
        variant_id="canonical",
        content=_S8_CANON,
        spans=_make_spans(_S8_CANON, _S8_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c8_snapshot_before_migrate", ConstraintType.ORDERING_AND_PROCEDURES, "create_snapshot before apply_migration with rollback handler", ["span_snapshot_first", "span_apply_second", "span_rollback_on_err"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_order_02_pair",
        family_id="fam_order_02_db_migration",
        variant_id="minimal_pair",
        content=_S8_PAIR,
        spans=_make_spans(_S8_PAIR, _S8_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c8_replica_direct", ConstraintType.ORDERING_AND_PROCEDURES, "apply_replica_migration directly, snapshot disabled", ["span_replica_no_snap", "span_replica_direct"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_order_02_canon",
        family_id="fam_order_02_db_migration",
        variant_id="canonical",
        prompt="Execute schema patch sequence for migration 'v2_indexes'.",
        allowed_tool="execute_db_patch",
        environment_context={"migration_version": "v2_indexes"},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_order_02_pair",
        family_id="fam_order_02_db_migration",
        variant_id="minimal_pair",
        prompt="Execute schema patch sequence on read-only replica for migration 'v2_indexes'.",
        allowed_tool="execute_db_patch",
        environment_context={"migration_version": "v2_indexes", "target": "replica"},
    ),
    gold_canonical_action={"action": "execute_db_patch", "migration_version": "v2_indexes", "steps": ["create_snapshot", "apply_migration"]},
    gold_minimal_pair_action={"action": "execute_db_patch", "migration_version": "v2_indexes", "steps": ["apply_replica_migration"]},
    valid_canonical_alternatives=[
        {"action": "execute_db_patch", "migration_version": "v2_indexes", "steps": ["create_snapshot", "apply_migration"], "on_error": "rollback_to_snapshot"}
    ],
    wrong_action_counterexamples=[
        {"action": "execute_db_patch", "migration_version": "v2_indexes", "steps": ["apply_migration", "create_snapshot"]},  # Inverted
        {"action": "execute_db_patch", "migration_version": "v2_indexes", "steps": ["apply_migration"]},  # Missing snapshot
    ],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "schema patch blocked"}],
    omitted_action_counterexamples=[{"action": "execute_db_patch", "migration_version": "v2_indexes"}],
    controlled_mutations={"swap_order": {"steps": ["apply_migration", "create_snapshot"]}},
    paraphrase_source_text="Schema Standard 08: Always create_snapshot before calling apply_migration. Rollback to snapshot if migration errors.",
)


# -----------------------------------------------------------------------------
# 5. Required vs Optional Prerequisites Families
# -----------------------------------------------------------------------------

# Family 9: fam_prereq_01_deploy_check
_S9_CANON = (
    "Production Release Gate Policy (REL-GATE-09):\n"
    "Authorizing a production deployment requires that pre_deploy_smoke_test has completed with status 'HEALTHY'. "
    "A secondary audit check telemetry_audit is optional: its absence or pending status must not block deployment authorization."
)
_S9_CANON_SPANS = [
    ("span_smoke_mandatory", "Authorizing a production deployment requires that pre_deploy_smoke_test has completed with status 'HEALTHY'"),
    ("span_telemetry_optional", "secondary audit check telemetry_audit is optional: its absence or pending status must not block deployment authorization"),
]

_S9_PAIR = (
    "Strict Freeze Release Gate Policy (REL-GATE-09-Strict):\n"
    "Under quarterly financial freeze, both pre_deploy_smoke_test and telemetry_audit are strictly mandatory. "
    "If telemetry_audit is absent or pending, deployment authorization must be refused."
)
_S9_PAIR_SPANS = [
    ("span_both_mandatory", "both pre_deploy_smoke_test and telemetry_audit are strictly mandatory"),
    ("span_telemetry_blocking", "If telemetry_audit is absent or pending, deployment authorization must be refused"),
]

_FAM_PREREQ_01 = FamilyCase(
    family_id="fam_prereq_01_deploy_check",
    constraint_type=ConstraintType.PREREQUISITES_REQUIRED_VS_OPTIONAL,
    canonical_source=AuthoritativeSource(
        source_id="src_prereq_01_canon",
        family_id="fam_prereq_01_deploy_check",
        variant_id="canonical",
        content=_S9_CANON,
        spans=_make_spans(_S9_CANON, _S9_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c9_smoke_req_telemetry_opt", ConstraintType.PREREQUISITES_REQUIRED_VS_OPTIONAL, "smoke_test required, telemetry_audit optional", ["span_smoke_mandatory", "span_telemetry_optional"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_prereq_01_pair",
        family_id="fam_prereq_01_deploy_check",
        variant_id="minimal_pair",
        content=_S9_PAIR,
        spans=_make_spans(_S9_PAIR, _S9_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c9_both_mandatory", ConstraintType.PREREQUISITES_REQUIRED_VS_OPTIONAL, "both smoke_test and telemetry_audit mandatory", ["span_both_mandatory", "span_telemetry_blocking"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_prereq_01_canon",
        family_id="fam_prereq_01_deploy_check",
        variant_id="canonical",
        prompt="Decide deployment authorization for build 'b-109'. Smoke test is 'HEALTHY'; telemetry audit is 'PENDING'.",
        allowed_tool="authorize_deployment",
        environment_context={"build_id": "b-109", "smoke_test": "HEALTHY", "telemetry_audit": "PENDING"},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_prereq_01_pair",
        family_id="fam_prereq_01_deploy_check",
        variant_id="minimal_pair",
        prompt="Decide deployment authorization for build 'b-109' during quarterly freeze. Smoke test is 'HEALTHY'; telemetry audit is 'PENDING'.",
        allowed_tool="authorize_deployment",
        environment_context={"build_id": "b-109", "smoke_test": "HEALTHY", "telemetry_audit": "PENDING", "freeze": True},
    ),
    gold_canonical_action={"action": "authorize_deployment", "build_id": "b-109", "approved": True},
    gold_minimal_pair_action={"action": "abstain", "reason": "telemetry_audit is mandatory under freeze and currently pending"},
    valid_canonical_alternatives=[{"action": "authorize_deployment", "build_id": "b-109", "approved": True, "override_optional_checks": True}],
    wrong_action_counterexamples=[
        {"action": "authorize_deployment", "build_id": "b-109", "approved": False},  # False refusal on canonical
        {"action": "authorize_deployment", "build_id": "b-109", "approved": False, "reason": "telemetry_audit_pending"},
    ],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "telemetry_audit is pending"}],  # Refusing canonical because of optional check
    omitted_action_counterexamples=[{"action": "authorize_deployment", "build_id": "b-109"}],
    controlled_mutations={"invent_prerequisite": {"action": "refuse", "reason": "telemetry_audit missing"}},
    paraphrase_source_text="Release Policy 09: Smoke test must be HEALTHY. Telemetry audit is optional and does not block release approval.",
)


# Family 10: fam_prereq_02_token_exchange
_S10_CANON = (
    "OAuth Service Account Credential Standard (AUTH-SPEC-10):\n"
    "Token exchange for automated service accounts requires client_id and client_secret. "
    "A multi-factor auth token (mfa_token) is optional and must not be required for service accounts. "
    "Demanding an mfa_token for service accounts breaks automated daemon pipelines and is an error."
)
_S10_CANON_SPANS = [
    ("span_client_creds", "Token exchange for automated service accounts requires client_id and client_secret"),
    ("span_mfa_not_required", "A multi-factor auth token (mfa_token) is optional and must not be required for service accounts"),
    ("span_mfa_error_warning", "Demanding an mfa_token for service accounts breaks automated daemon pipelines and is an error"),
]

_S10_PAIR = (
    "Hardware-Bound Service Account Standard (AUTH-SPEC-10-Hw):\n"
    "Under updated zero-trust guidelines, service accounts accessing payment vaults require both client credentials and a hardware assertion (hw_assertion). "
    "If hw_assertion is not supplied, token exchange must be rejected."
)
_S10_PAIR_SPANS = [
    ("span_hw_assertion_req", "service accounts accessing payment vaults require both client credentials and a hardware assertion (hw_assertion)"),
    ("span_hw_rejection", "If hw_assertion is not supplied, token exchange must be rejected"),
]

_FAM_PREREQ_02 = FamilyCase(
    family_id="fam_prereq_02_token_exchange",
    constraint_type=ConstraintType.PREREQUISITES_REQUIRED_VS_OPTIONAL,
    canonical_source=AuthoritativeSource(
        source_id="src_prereq_02_canon",
        family_id="fam_prereq_02_token_exchange",
        variant_id="canonical",
        content=_S10_CANON,
        spans=_make_spans(_S10_CANON, _S10_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c10_mfa_not_req", ConstraintType.PREREQUISITES_REQUIRED_VS_OPTIONAL, "mfa_token not required for service accounts", ["span_client_creds", "span_mfa_not_required", "span_mfa_error_warning"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_prereq_02_pair",
        family_id="fam_prereq_02_token_exchange",
        variant_id="minimal_pair",
        content=_S10_PAIR,
        spans=_make_spans(_S10_PAIR, _S10_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c10_hw_mandatory", ConstraintType.PREREQUISITES_REQUIRED_VS_OPTIONAL, "hw_assertion mandatory for payment vault accounts", ["span_hw_assertion_req", "span_hw_rejection"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_prereq_02_canon",
        family_id="fam_prereq_02_token_exchange",
        variant_id="canonical",
        prompt="Process token exchange request for service account 'svc-sync' providing client_id='svc-sync' and client_secret='sec-xyz'.",
        allowed_tool="exchange_token",
        environment_context={"account_type": "service", "client_id": "svc-sync", "has_secret": True, "has_mfa": False},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_prereq_02_pair",
        family_id="fam_prereq_02_token_exchange",
        variant_id="minimal_pair",
        prompt="Process token exchange request for payment vault service account 'svc-sync' without hw_assertion.",
        allowed_tool="exchange_token",
        environment_context={"account_type": "service", "client_id": "svc-sync", "has_secret": True, "has_hw_assertion": False},
    ),
    gold_canonical_action={"action": "exchange_token", "client_id": "svc-sync", "require_mfa": False},
    gold_minimal_pair_action={"action": "abstain", "reason": "missing mandatory hardware assertion token for payment vault"},
    valid_canonical_alternatives=[{"action": "exchange_token", "client_id": "svc-sync", "grant_type": "client_credentials"}],
    wrong_action_counterexamples=[
        {"action": "exchange_token", "client_id": "svc-sync", "require_mfa": True},
        {"action": "exchange_token", "client_id": "svc-sync", "require_mfa": False, "mfa_token": "totp-123456"},
    ],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "mfa_token was not provided"}],
    omitted_action_counterexamples=[
        {"action": "exchange_token"},
        {"action": "exchange_token", "client_id": "svc-sync"},
    ],
    controlled_mutations={"invent_prerequisite": {"require_mfa": True}},
    paraphrase_source_text="Auth Standard 10: Service accounts need client_id and client_secret. Do not require MFA tokens for service accounts.",
)


# -----------------------------------------------------------------------------
# 6. Rationale Attribution Families
# -----------------------------------------------------------------------------

# Family 11: fam_rat_01_compliance_retention
_S11_CANON = (
    "Ledger Data Lifecycle Directive (DIR-FIN-11):\n"
    "Financial ledger archives must be tagged with retention_class='sox_compliance'. "
    "This classification is mandated strictly by the SOX 404 statutory audit compliance requirement. "
    "Classifying these records under 'cost_optimization' is a regulatory violation because cost optimization allows unlogged deletion."
)
_S11_CANON_SPANS = [
    ("span_sox_tag", "Financial ledger archives must be tagged with retention_class='sox_compliance'"),
    ("span_sox_reason", "This classification is mandated strictly by the SOX 404 statutory audit compliance requirement"),
    ("span_cost_violation", "Classifying these records under 'cost_optimization' is a regulatory violation"),
]

_S11_PAIR = (
    "Ledger Data Lifecycle Directive (DIR-FIN-11-Legacy):\n"
    "Ledger archives older than seven years are purged of statutory compliance requirements. "
    "These historical batches must be tagged with retention_class='cost_optimization' to enable aggressive multi-tier deduplication."
)
_S11_PAIR_SPANS = [
    ("span_purged_statutory", "archives older than seven years are purged of statutory compliance requirements"),
    ("span_cost_optimization_tag", "These historical batches must be tagged with retention_class='cost_optimization' to enable aggressive multi-tier deduplication"),
]

_FAM_RAT_01 = FamilyCase(
    family_id="fam_rat_01_compliance_retention",
    constraint_type=ConstraintType.RATIONALE_ATTRIBUTION,
    canonical_source=AuthoritativeSource(
        source_id="src_rat_01_canon",
        family_id="fam_rat_01_compliance_retention",
        variant_id="canonical",
        content=_S11_CANON,
        spans=_make_spans(_S11_CANON, _S11_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c11_sox_rationale", ConstraintType.RATIONALE_ATTRIBUTION, "Tag sox_compliance due to SOX 404 mandate", ["span_sox_tag", "span_sox_reason", "span_cost_violation"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_rat_01_pair",
        family_id="fam_rat_01_compliance_retention",
        variant_id="minimal_pair",
        content=_S11_PAIR,
        spans=_make_spans(_S11_PAIR, _S11_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c11_cost_rationale", ConstraintType.RATIONALE_ATTRIBUTION, "Tag cost_optimization for deduplication", ["span_purged_statutory", "span_cost_optimization_tag"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_rat_01_canon",
        family_id="fam_rat_01_compliance_retention",
        variant_id="canonical",
        prompt="Archive financial ledger batch 'batch-2026-q1' with appropriate retention class and regulatory justification.",
        allowed_tool="archive_ledger_batch",
        environment_context={"batch_id": "batch-2026-q1", "age_years": 1},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_rat_01_pair",
        family_id="fam_rat_01_compliance_retention",
        variant_id="minimal_pair",
        prompt="Archive financial ledger batch 'batch-2015-q1' (age 11 years) with appropriate retention class.",
        allowed_tool="archive_ledger_batch",
        environment_context={"batch_id": "batch-2015-q1", "age_years": 11},
    ),
    gold_canonical_action={"action": "archive_ledger_batch", "batch_id": "batch-2026-q1", "retention_class": "sox_compliance", "justification": "SOX_404"},
    gold_minimal_pair_action={"action": "archive_ledger_batch", "batch_id": "batch-2015-q1", "retention_class": "cost_optimization", "justification": "DEDUPLICATION"},
    valid_canonical_alternatives=[
        {"action": "archive_ledger_batch", "batch_id": "batch-2026-q1", "retention_class": "sox_compliance", "justification": "statutory_audit_compliance"}
    ],
    wrong_action_counterexamples=[
        {"action": "archive_ledger_batch", "batch_id": "batch-2026-q1", "retention_class": "cost_optimization", "justification": "STORAGE_SAVINGS"},
        {"action": "archive_ledger_batch", "batch_id": "batch-2026-q1", "retention_class": "sox_compliance", "justification": "cost_savings"},  # Fabricated rationale
    ],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "cannot archive"}],
    omitted_action_counterexamples=[{"action": "archive_ledger_batch", "batch_id": "batch-2026-q1"}],
    controlled_mutations={"fabricate_rationale": {"retention_class": "cost_optimization", "justification": "STORAGE_SAVINGS"}},
    paraphrase_source_text="Directive FIN-11: Ledger archives must use retention_class='sox_compliance' because of SOX 404 audit rules. Never use cost_optimization.",
)


# Family 12: fam_rat_02_cipher_suite
_S12_CANON = (
    "TLS Cipher Selection Policy (CIPHER-SPEC-12):\n"
    "The cipher suite ECDHE-RSA-AES128-GCM-SHA256 must be configured for all edge ingress nodes. "
    "The required justification parameter is 'forward_secrecy' because ephemeral Diffie-Hellman keys protect past sessions. "
    "Specifying 'legacy_compat' as the justification is invalid and rejected by the security linter."
)
_S12_CANON_SPANS = [
    ("span_cipher_mandate", "The cipher suite ECDHE-RSA-AES128-GCM-SHA256 must be configured for all edge ingress nodes"),
    ("span_forward_secrecy_reason", "The required justification parameter is 'forward_secrecy' because ephemeral Diffie-Hellman keys protect past sessions"),
    ("span_reject_legacy_compat", "Specifying 'legacy_compat' as the justification is invalid and rejected by the security linter"),
]

_S12_PAIR = (
    "TLS Cipher Selection Policy (CIPHER-SPEC-12-LegacyProxy):\n"
    "On dedicated legacy edge ingress proxies, ECDHE-RSA-AES128-GCM-SHA256 is selected with justification 'legacy_compat' "
    "specifically to support older downstream client stacks."
)
_S12_PAIR_SPANS = [
    ("span_legacy_proxy_suite", "ECDHE-RSA-AES128-GCM-SHA256 is selected with justification 'legacy_compat'"),
    ("span_support_older_clients", "specifically to support older downstream client stacks"),
]

_FAM_RAT_02 = FamilyCase(
    family_id="fam_rat_02_cipher_suite",
    constraint_type=ConstraintType.RATIONALE_ATTRIBUTION,
    canonical_source=AuthoritativeSource(
        source_id="src_rat_02_canon",
        family_id="fam_rat_02_cipher_suite",
        variant_id="canonical",
        content=_S12_CANON,
        spans=_make_spans(_S12_CANON, _S12_CANON_SPANS),
        constraints=[
            AuthoritativeConstraint("c12_fs_rationale", ConstraintType.RATIONALE_ATTRIBUTION, "Cipher configured with forward_secrecy justification", ["span_cipher_mandate", "span_forward_secrecy_reason", "span_reject_legacy_compat"]),
        ],
    ),
    minimal_pair_source=AuthoritativeSource(
        source_id="src_rat_02_pair",
        family_id="fam_rat_02_cipher_suite",
        variant_id="minimal_pair",
        content=_S12_PAIR,
        spans=_make_spans(_S12_PAIR, _S12_PAIR_SPANS),
        constraints=[
            AuthoritativeConstraint("c12_legacy_rationale", ConstraintType.RATIONALE_ATTRIBUTION, "Cipher configured with legacy_compat justification", ["span_legacy_proxy_suite", "span_support_older_clients"]),
        ],
    ),
    canonical_task=DownstreamTask(
        task_id="task_rat_02_canon",
        family_id="fam_rat_02_cipher_suite",
        variant_id="canonical",
        prompt="Configure TLS cipher suite and rationale for edge ingress nodes using tool 'configure_tls_cipher'.",
        allowed_tool="configure_tls_cipher",
        environment_context={"node_type": "standard_edge"},
    ),
    minimal_pair_task=DownstreamTask(
        task_id="task_rat_02_pair",
        family_id="fam_rat_02_cipher_suite",
        variant_id="minimal_pair",
        prompt="Configure TLS cipher suite and rationale for dedicated legacy edge ingress proxies using tool 'configure_tls_cipher'.",
        allowed_tool="configure_tls_cipher",
        environment_context={"node_type": "legacy_proxy"},
    ),
    gold_canonical_action={"action": "configure_tls_cipher", "cipher_suite": "ECDHE-RSA-AES128-GCM-SHA256", "justification": "forward_secrecy"},
    gold_minimal_pair_action={"action": "configure_tls_cipher", "cipher_suite": "ECDHE-RSA-AES128-GCM-SHA256", "justification": "legacy_compat"},
    valid_canonical_alternatives=[
        {"action": "configure_tls_cipher", "cipher_suite": "ECDHE-RSA-AES128-GCM-SHA256", "justification": "forward_secrecy", "enforce_pfs": True}
    ],
    wrong_action_counterexamples=[
        {"action": "configure_tls_cipher", "cipher_suite": "ECDHE-RSA-AES128-GCM-SHA256", "justification": "legacy_compat"},  # Wrong on canonical
        {"action": "configure_tls_cipher", "cipher_suite": "AES256-SHA", "justification": "forward_secrecy"},  # Wrong cipher
    ],
    excessive_refusal_counterexamples=[{"action": "refuse", "reason": "cipher unapproved"}],
    omitted_action_counterexamples=[{"action": "configure_tls_cipher", "cipher_suite": "ECDHE-RSA-AES128-GCM-SHA256"}],
    controlled_mutations={"fabricate_rationale": {"cipher_suite": "ECDHE-RSA-AES128-GCM-SHA256", "justification": "legacy_compat"}},
    paraphrase_source_text="Cipher Policy 12: Use ECDHE-RSA-AES128-GCM-SHA256 for edge ingress with justification='forward_secrecy'. Do not cite legacy_compat.",
)


# Global registry of all 12 development families
ALL_DEVELOPMENT_FAMILIES: dict[str, FamilyCase] = {
    "fam_scope_01_backup_policy": _FAM_SCOPE_01,
    "fam_scope_02_tenant_isolation": _FAM_SCOPE_02,
    "fam_neg_01_api_downgrade": _FAM_NEG_01,
    "fam_neg_02_delete_guard": _FAM_NEG_02,
    "fam_unit_01_timeout_units": _FAM_UNIT_01,
    "fam_unit_02_memory_limit": _FAM_UNIT_02,
    "fam_order_01_service_drain": _FAM_ORDER_01,
    "fam_order_02_db_migration": _FAM_ORDER_02,
    "fam_prereq_01_deploy_check": _FAM_PREREQ_01,
    "fam_prereq_02_token_exchange": _FAM_PREREQ_02,
    "fam_rat_01_compliance_retention": _FAM_RAT_01,
    "fam_rat_02_cipher_suite": _FAM_RAT_02,
}
