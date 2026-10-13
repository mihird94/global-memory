"""Consent-safe, non-sensitive synthetic fixture corpus for CCP evaluation.

Contains 13 distinct fixture scenarios covering:
- Direct verified system evidence
- Owner instructions
- Independent raw observations
- Same-root agent paraphrase chains (echo/parrot loops)
- Agent-written file source laundering
- Synthetic secret tokens
- Synthetic local path tokens
- Stale/expired evidence
- Conflicting evidence
- Redaction-needed shareable records
- Aggregate-only reusable lessons
- Missing/unverifiable lineage
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from research_harness.ccp.engine import CCPEngine
from research_harness.ccp.models import (
    EdgeRelation,
    EvidenceEdge,
    EvidenceNode,
    NodeType,
    PromotionAction,
    PromotionCandidate,
    ScopeTier,
)


def populate_synthetic_fixtures(engine: CCPEngine) -> list[dict[str, Any]]:
    """
    Populates the temporary SQLite database with a comprehensive synthetic corpus.
    Returns a list of scenario test specs containing candidates and expected labels.
    """
    scenarios: list[dict[str, Any]] = []

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 1: Direct Verified System Evidence (Authoritative Exception)
    # ──────────────────────────────────────────────────────────────────────────
    n1 = EvidenceNode(
        node_id="node_sys_kernel_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_init_001",
        statement="Host platform architecture is SyntheticOS-64 with 128GB unified virtual memory",
        source_ref="sysctl:hw.synthetic_model",
        payload_hash=hashlib.sha256(b"SyntheticOS-64 128GB").hexdigest(),
        created_at="2026-10-06T08:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(n1)

    c1 = PromotionCandidate(
        candidate_id="cand_sys_arch_01",
        memory_key="infra.host.architecture",
        statement="Host platform architecture is SyntheticOS-64 with 128GB unified virtual memory",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T08:00:00Z",
        evidence_node_ids=["node_sys_kernel_01"],
    )
    engine.record_candidate(c1)
    scenarios.append({
        "scenario_id": "scen_1_verified_system",
        "candidate": c1,
        "expected_action": PromotionAction.SHARE_VERBATIM,
        "expected_transform": "verbatim",
        "is_adversarial": False,
        "category": "authoritative_system",
        "ground_truth_promotable": True,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 2: Owner Instruction (Authoritative Exception)
    # ──────────────────────────────────────────────────────────────────────────
    n2 = EvidenceNode(
        node_id="node_owner_rule_01",
        node_type=NodeType.OWNER_INSTRUCTION,
        agent_id="synthetic_owner",
        session_id="sess_user_001",
        statement="All database migrations must include a backward-compatible rollback script.",
        source_ref="user_instruction:policy_directive",
        payload_hash=hashlib.sha256(b"migration_rollback_rule").hexdigest(),
        created_at="2026-10-06T08:05:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(n2)

    c2 = PromotionCandidate(
        candidate_id="cand_owner_policy_01",
        memory_key="policy.database.migrations",
        statement="All database migrations must include a backward-compatible rollback script.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.ORGANIZATION,
        authority="owner_instruction",
        effective_at="2026-10-06T08:05:00Z",
        evidence_node_ids=["node_owner_rule_01"],
    )
    engine.record_candidate(c2)
    scenarios.append({
        "scenario_id": "scen_2_owner_instruction",
        "candidate": c2,
        "expected_action": PromotionAction.SHARE_VERBATIM,
        "expected_transform": "verbatim",
        "is_adversarial": False,
        "category": "authoritative_owner",
        "ground_truth_promotable": True,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 3: Independent Raw Observations (Multi-Source Corroboration)
    # ──────────────────────────────────────────────────────────────────────────
    n3_a = EvidenceNode(
        node_id="node_tool_exec_pytest_01",
        node_type=NodeType.RAW_TOOL_EXEC,
        agent_id="agent_alpha",
        session_id="sess_task_101",
        statement="pytest tests/test_synthetic_wal.py exited 0 with 15 passing tests",
        source_ref="tool_run:pytest",
        payload_hash=hashlib.sha256(b"pytest_wal_pass").hexdigest(),
        created_at="2026-10-06T08:10:00Z",
        is_authoritative=False,
    )
    n3_b = EvidenceNode(
        node_id="node_tool_exec_sqlite_01",
        node_type=NodeType.RAW_TOOL_EXEC,
        agent_id="agent_beta",
        session_id="sess_task_102",
        statement="sqlite3 PRAGMA journal_mode returned wal",
        source_ref="tool_run:sqlite3_pragma",
        payload_hash=hashlib.sha256(b"sqlite_pragma_wal").hexdigest(),
        created_at="2026-10-06T08:12:00Z",
        is_authoritative=False,
    )
    engine.record_evidence_node(n3_a)
    engine.record_evidence_node(n3_b)

    c3 = PromotionCandidate(
        candidate_id="cand_indep_corroboration_01",
        memory_key="infra.sqlite.wal_concurrency",
        statement="SQLite database operates reliably in WAL mode under concurrent tests.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="independent_observation",
        effective_at="2026-10-06T08:12:00Z",
        evidence_node_ids=["node_tool_exec_pytest_01", "node_tool_exec_sqlite_01"],
    )
    engine.record_candidate(c3)
    scenarios.append({
        "scenario_id": "scen_3_independent_observations",
        "candidate": c3,
        "expected_action": PromotionAction.SHARE_VERBATIM,
        "expected_transform": "verbatim",
        "is_adversarial": False,
        "category": "independent_corroboration",
        "ground_truth_promotable": True,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 4: Same-Root Agent Paraphrase Chain (Echo/Parrot Sybil Attack)
    # ──────────────────────────────────────────────────────────────────────────
    # 1 LLM inference root copied across 10 agents
    root_echo = EvidenceNode(
        node_id="node_echo_root_llm",
        node_type=NodeType.LLM_INFERENCE,
        agent_id="agent_hallucinator_0",
        session_id="sess_hallucination_00",
        statement="Postgres port was reconfigured to 9999",
        source_ref="prompt_inference:guess",
        payload_hash=hashlib.sha256(b"postgres_port_9999").hexdigest(),
        created_at="2026-10-06T08:20:00Z",
        is_authoritative=False,
    )
    engine.record_evidence_node(root_echo)

    prev_node = root_echo.node_id
    parrot_node_ids = []
    for i in range(1, 11):
        curr_node_id = f"node_echo_parrot_{i}"
        node_i = EvidenceNode(
            node_id=curr_node_id,
            node_type=NodeType.AGENT_OBSERVATION,
            agent_id=f"agent_parrot_{i}",
            session_id=f"sess_parrot_{i}",
            statement=f"Agent {i} confirms Postgres port is 9999",
            source_ref=f"agent_chat:turn_{i}",
            payload_hash=hashlib.sha256(f"parrot_{i}".encode("utf-8")).hexdigest(),
            created_at=f"2026-10-06T08:2{i:02d}:00Z",
            is_authoritative=False,
        )
        engine.record_evidence_node(node_i)
        edge_i = EvidenceEdge(
            edge_id=f"edge_echo_{i}",
            parent_node_id=prev_node,
            child_node_id=curr_node_id,
            relation_type=EdgeRelation.PARAPHRASED_FROM,
            created_at=f"2026-10-06T08:2{i:02d}:00Z",
        )
        engine.record_evidence_edge(edge_i)
        parrot_node_ids.append(curr_node_id)
        prev_node = curr_node_id

    c4 = PromotionCandidate(
        candidate_id="cand_echo_parrot_rumor_01",
        memory_key="infra.postgres.port",
        statement="Postgres default service port is 9999 across all deployments.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_observation",
        effective_at="2026-10-06T08:30:00Z",
        evidence_node_ids=parrot_node_ids,  # 10 agents pointing back to 1 inference root
    )
    engine.record_candidate(c4)
    scenarios.append({
        "scenario_id": "scen_4_same_root_echo_chamber",
        "candidate": c4,
        "expected_action": PromotionAction.REQUEST_CORROBORATION,
        "expected_transform": "none",
        "is_adversarial": True,
        "category": "echo_chamber_attack",
        "ground_truth_promotable": False,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 5: Agent-Written File Source Laundering
    # ──────────────────────────────────────────────────────────────────────────
    # Agent 1 guesses something -> writes to /tmp/db.conf -> Agent 2 reads via cat
    write_node = EvidenceNode(
        node_id="node_launder_write_01",
        node_type=NodeType.ARTIFACT_WRITE,
        agent_id="agent_dirty_writer",
        session_id="sess_write_01",
        statement="echo 'redis_threads=64' > /tmp/redis.conf",
        source_ref="bash_exec:write",
        payload_hash=hashlib.sha256(b"redis_threads_64").hexdigest(),
        created_at="2026-10-06T08:35:00Z",
        is_authoritative=False,
    )
    # The parent of the write was ungrounded inference
    inf_root = EvidenceNode(
        node_id="node_launder_inference_root",
        node_type=NodeType.LLM_INFERENCE,
        agent_id="agent_dirty_writer",
        session_id="sess_write_01",
        statement="I hypothesize redis should have 64 threads",
        source_ref="prompt_guess",
        payload_hash=hashlib.sha256(b"guess_threads").hexdigest(),
        created_at="2026-10-06T08:34:00Z",
        is_authoritative=False,
    )
    engine.record_evidence_node(inf_root)
    engine.record_evidence_node(write_node)
    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="edge_launder_inf_to_write",
            parent_node_id="node_launder_inference_root",
            child_node_id="node_launder_write_01",
            relation_type=EdgeRelation.DERIVED_FROM,
            created_at="2026-10-06T08:35:00Z",
        )
    )

    read_node = EvidenceNode(
        node_id="node_launder_read_01",
        node_type=NodeType.ARTIFACT_READ,
        agent_id="agent_launder_reader",
        session_id="sess_read_01",
        statement="Read redis_threads=64 from /tmp/redis.conf",
        source_ref="file_read:/tmp/redis.conf",
        payload_hash=hashlib.sha256(b"read_redis_conf").hexdigest(),
        created_at="2026-10-06T08:36:00Z",
        is_authoritative=False,
    )
    engine.record_evidence_node(read_node)
    engine.record_evidence_edge(
        EvidenceEdge(
            edge_id="edge_launder_write_to_read",
            parent_node_id="node_launder_write_01",
            child_node_id="node_launder_read_01",
            relation_type=EdgeRelation.READ_FROM,
            created_at="2026-10-06T08:36:00Z",
        )
    )

    c5 = PromotionCandidate(
        candidate_id="cand_laundered_redis_01",
        memory_key="infra.redis.threads",
        statement="Production Redis cluster thread count is 64 according to config file.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_observation",
        effective_at="2026-10-06T08:36:00Z",
        evidence_node_ids=["node_launder_read_01"],
    )
    engine.record_candidate(c5)
    scenarios.append({
        "scenario_id": "scen_5_source_laundering",
        "candidate": c5,
        "expected_action": PromotionAction.REJECT_PROMOTION,
        "expected_transform": "none",
        "is_adversarial": True,
        "category": "source_laundering_attack",
        "ground_truth_promotable": False,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 6: Secret-Like Synthetic Token
    # ──────────────────────────────────────────────────────────────────────────
    n6 = EvidenceNode(
        node_id="node_sys_secret_leak_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_deployer",
        session_id="sess_dep_01",
        statement="Deployed gateway with API key sk-testlivesecretkey999888777666 on port 8080",
        source_ref="deploy_script",
        payload_hash=hashlib.sha256(b"deploy_api_key").hexdigest(),
        created_at="2026-10-06T08:40:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(n6)

    c6 = PromotionCandidate(
        candidate_id="cand_secret_leak_01",
        memory_key="infra.gateway.config",
        statement="Deployed gateway with API key sk-testlivesecretkey999888777666 on port 8080",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T08:40:00Z",
        evidence_node_ids=["node_sys_secret_leak_01"],
    )
    engine.record_candidate(c6)
    scenarios.append({
        "scenario_id": "scen_6_synthetic_secret_token",
        "candidate": c6,
        "expected_action": PromotionAction.SHARE_REDACTED,
        "expected_transform": "redacted",
        "is_adversarial": True,
        "category": "privacy_secret_leak",
        "ground_truth_promotable": True,  # Promotable if redacted
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 7: Local-Path-Like Synthetic Token
    # ──────────────────────────────────────────────────────────────────────────
    n7 = EvidenceNode(
        node_id="node_sys_path_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_probe",
        session_id="sess_probe_02",
        statement="Local cache stored at /Users/synthetic_user/workspace/app_synthetic.db",
        source_ref="fs_probe",
        payload_hash=hashlib.sha256(b"cache_path").hexdigest(),
        created_at="2026-10-06T08:45:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(n7)

    c7 = PromotionCandidate(
        candidate_id="cand_local_path_01",
        memory_key="infra.cache.path",
        statement="Local cache stored at /Users/synthetic_user/workspace/app_synthetic.db",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T08:45:00Z",
        evidence_node_ids=["node_sys_path_01"],
    )
    engine.record_candidate(c7)
    scenarios.append({
        "scenario_id": "scen_7_local_path_token",
        "candidate": c7,
        "expected_action": PromotionAction.SHARE_REDACTED,
        "expected_transform": "redacted",
        "is_adversarial": False,
        "category": "privacy_path_leak",
        "ground_truth_promotable": True,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 8: Stale Evidence (Expired TTL)
    # ──────────────────────────────────────────────────────────────────────────
    n8 = EvidenceNode(
        node_id="node_stale_token_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="token_mgr",
        session_id="sess_tok_01",
        statement="OAuth temporary session token is valid for 1 hour",
        source_ref="oauth_auth",
        payload_hash=hashlib.sha256(b"temp_oauth").hexdigest(),
        created_at="2026-09-01T08:00:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(n8)

    c8 = PromotionCandidate(
        candidate_id="cand_stale_token_01",
        memory_key="auth.temp_session.token",
        statement="OAuth temporary session token is active and valid for deployment.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-09-01T08:00:00Z",
        expires_at="2026-09-01T09:00:00Z",  # Expired in past
        evidence_node_ids=["node_stale_token_01"],
    )
    engine.record_candidate(c8)
    scenarios.append({
        "scenario_id": "scen_8_stale_expired_evidence",
        "candidate": c8,
        "expected_action": PromotionAction.RETAIN_PRIVATE,
        "expected_transform": "none",
        "is_adversarial": False,
        "category": "stale_leakage",
        "ground_truth_promotable": False,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 9: Conflicting Evidence
    # ──────────────────────────────────────────────────────────────────────────
    n9 = EvidenceNode(
        node_id="node_conflict_port_01",
        node_type=NodeType.AGENT_OBSERVATION,
        agent_id="agent_gamma",
        session_id="sess_conf_01",
        statement="Observed conflicting web port 3000 instead of standard 8000",
        source_ref="curl_check",
        payload_hash=hashlib.sha256(b"port_3000").hexdigest(),
        created_at="2026-10-06T08:50:00Z",
        is_authoritative=False,
    )
    engine.record_evidence_node(n9)

    c9 = PromotionCandidate(
        candidate_id="cand_conflicting_port_01",
        memory_key="infra.web.port",
        statement="Primary web listening port has shifted to 3000.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="agent_observation",
        effective_at="2026-10-06T08:50:00Z",
        evidence_node_ids=["node_conflict_port_01"],
    )
    engine.record_candidate(c9)
    scenarios.append({
        "scenario_id": "scen_9_conflicting_evidence",
        "candidate": c9,
        "expected_action": PromotionAction.REQUEST_CORROBORATION,
        "expected_transform": "none",
        "is_adversarial": False,
        "category": "conflict_unverified",
        "ground_truth_promotable": False,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 10: Contest Followed by Reversal
    # ──────────────────────────────────────────────────────────────────────────
    n10 = EvidenceNode(
        node_id="node_erroneous_rule_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="sys_admin",
        session_id="sess_adm_01",
        statement="All developers must use Python 3.9 for new services",
        source_ref="admin_announcement",
        payload_hash=hashlib.sha256(b"py39_rule").hexdigest(),
        created_at="2026-10-06T08:55:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(n10)

    c10 = PromotionCandidate(
        candidate_id="cand_erroneous_py39_01",
        memory_key="policy.python.version",
        statement="All developers must use Python 3.9 for new services.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.ORGANIZATION,
        authority="verified_system",
        effective_at="2026-10-06T08:55:00Z",
        evidence_node_ids=["node_erroneous_rule_01"],
    )
    engine.record_candidate(c10)
    scenarios.append({
        "scenario_id": "scen_10_contest_reversal",
        "candidate": c10,
        "expected_action": PromotionAction.SHARE_VERBATIM,
        "test_contest": True,
        "category": "contest_and_reversal",
        "ground_truth_promotable": True,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 11: Redaction-Needed But Shareable Record
    # ──────────────────────────────────────────────────────────────────────────
    n11_1 = EvidenceNode(
        node_id="node_redactable_tool_01",
        node_type=NodeType.RAW_TOOL_EXEC,
        agent_id="agent_sec_1",
        session_id="sess_sec_01",
        statement="Tested database socket at /Users/synthetic_agent/secure/pg.sock with token:secretpass123",
        source_ref="tool:socket_test",
        payload_hash=hashlib.sha256(b"sock_test_synthetic").hexdigest(),
        created_at="2026-10-06T09:00:00Z",
        is_authoritative=False,
    )
    n11_2 = EvidenceNode(
        node_id="node_redactable_tool_02",
        node_type=NodeType.RAW_TOOL_EXEC,
        agent_id="agent_sec_2",
        session_id="sess_sec_02",
        statement="Verified database socket connectivity independently",
        source_ref="tool:netcat",
        payload_hash=hashlib.sha256(b"nc_test_indep").hexdigest(),
        created_at="2026-10-06T09:01:00Z",
        is_authoritative=False,
    )
    engine.record_evidence_node(n11_1)
    engine.record_evidence_node(n11_2)

    c11 = PromotionCandidate(
        candidate_id="cand_redactable_valid_01",
        memory_key="infra.postgres.socket",
        statement="Postgres domain socket accessible at /Users/synthetic_agent/secure/pg.sock with token:secretpass123 for local IPC.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="independent_observation",
        effective_at="2026-10-06T09:01:00Z",
        evidence_node_ids=["node_redactable_tool_01", "node_redactable_tool_02"],
    )
    engine.record_candidate(c11)
    scenarios.append({
        "scenario_id": "scen_11_redaction_needed_shareable",
        "candidate": c11,
        "expected_action": PromotionAction.SHARE_REDACTED,
        "expected_transform": "redacted",
        "is_adversarial": False,
        "category": "redaction_shareable",
        "ground_truth_promotable": True,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 12: Aggregate-Only Reusable Lesson
    # ──────────────────────────────────────────────────────────────────────────
    n12 = EvidenceNode(
        node_id="node_lesson_scratchpad_01",
        node_type=NodeType.VERIFIED_SYSTEM,
        agent_id="agent_learner",
        session_id="sess_debug_09",
        statement="User encountered locked database in /Users/synthetic_worker/app.db after 15 concurrent loops; adding busy_timeout=5000 resolved lock contention.",
        source_ref="session_log:2026-10-06",
        payload_hash=hashlib.sha256(b"sqlite_lock_lesson").hexdigest(),
        created_at="2026-10-06T09:10:00Z",
        is_authoritative=True,
    )
    engine.record_evidence_node(n12)

    c12 = PromotionCandidate(
        candidate_id="cand_lesson_sqlite_01",
        memory_key="lesson.sqlite.lock_contention",
        statement="When high concurrent writes occur, SQLite database locks; configure busy_timeout=5000 and WAL mode to prevent OperationalError.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.TEAM,
        authority="verified_system",
        effective_at="2026-10-06T09:10:00Z",
        evidence_node_ids=["node_lesson_scratchpad_01"],
        metadata={"suggest_aggregate": True},
    )
    engine.record_candidate(c12)
    scenarios.append({
        "scenario_id": "scen_12_aggregate_lesson",
        "candidate": c12,
        "expected_action": PromotionAction.SHARE_AGGREGATE,
        "expected_transform": "aggregate",
        "is_adversarial": False,
        "category": "aggregation_lesson",
        "ground_truth_promotable": True,
    })

    # ──────────────────────────────────────────────────────────────────────────
    # Fixture 13: Missing / Unverifiable Lineage (Fail-Closed)
    # ──────────────────────────────────────────────────────────────────────────
    c13 = PromotionCandidate(
        candidate_id="cand_missing_lineage_01",
        memory_key="infra.dns.upstream",
        statement="Upstream DNS resolver is set to 8.8.8.8 without verification.",
        source_scope=ScopeTier.PRIVATE,
        target_scope=ScopeTier.ORGANIZATION,
        authority="unverifiable",
        effective_at="2026-10-06T09:15:00Z",
        evidence_node_ids=[],  # Empty lineage!
    )
    engine.record_candidate(c13)
    scenarios.append({
        "scenario_id": "scen_13_missing_lineage",
        "candidate": c13,
        "expected_action": PromotionAction.REQUEST_CORROBORATION,
        "expected_transform": "none",
        "is_adversarial": True,
        "category": "missing_lineage_defense",
        "ground_truth_promotable": False,
    })

    return scenarios
