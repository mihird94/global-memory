"""Synthetic seeded robustness scenario generator and multi-seed evaluation harness.

Generates consent-safe, strictly fictionalized synthetic evaluation scenarios
across deterministic pseudo-random seeds (e.g., 42, 123, 999) to evaluate
CCP decision gate robustness against adversarial perturbations.

RESEARCH LIMITATION / EVALUATION DISCLOSURE:
These scenarios represent synthetic seeded robustness evaluations, NOT held-out
human or real-world validation data. Ground-truth labels are authored parametrically
alongside the harness. Do not characterize these benchmarks as independent held-out
validation without independently authored and pre-frozen empirical test sets.
"""

from __future__ import annotations

import hashlib
import random
import warnings
from typing import Any

from research_harness.ccp.baselines import (
    BaselineB0AlwaysShare,
    BaselineB1StaticRegexDLP,
    BaselineB2DistinctAgentCount,
    BaselineB3CCPGate,
)
from research_harness.ccp.benchmark import run_benchmark_for_baseline
from research_harness.ccp.engine import CCPEngine
from research_harness.ccp.models import (
    ArtifactIdentity,
    EdgeRelation,
    EvidenceEdge,
    EvidenceNode,
    NodeType,
    PromotionAction,
    PromotionCandidate,
    ScopeTier,
)
from research_harness.ccp.schema import init_temporary_ccp_db


def generate_synthetic_robustness_scenarios(engine: CCPEngine, seed: int = 42, count: int = 26) -> list[dict[str, Any]]:
    """
    Deterministically generates synthetic robustness scenarios across diverse categories:
    - Authoritative system
    - Owner directives
    - Independent corroboration
    - Unsupported claim mismatch
    - Echo chains
    - Source laundering
    - Authority relabeling
    - Secret leaks
    - Local path leaks
    - Stale items
    - Missing lineage
    - Authoritative contradictions
    - Contest and rollback
    """
    rng = random.Random(seed)
    scenarios: list[dict[str, Any]] = []

    for i in range(count):
        case_type = i % 13
        base_id = f"s{seed}_c{i}"

        if case_type == 0:
            # 1. Authoritative system config
            val = rng.choice([16, 32, 64, 128])
            node = EvidenceNode(
                node_id=f"node_{base_id}_sys",
                node_type=NodeType.VERIFIED_SYSTEM,
                agent_id="sys_probe_heldout",
                session_id=f"sess_{base_id}",
                statement=f"Kernel hardware limit max_files set to {val}000",
                source_ref=f"sysctl:kern.maxfiles_{seed}",
                payload_hash=hashlib.sha256(f"maxfiles_{val}".encode()).hexdigest(),
                created_at="2026-10-06T10:00:00Z",
                is_authoritative=True,
                supported_claim_key=f"infra.sysctl.maxfiles_{i}",
            )
            engine.record_evidence_node(node)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"infra.sysctl.maxfiles_{i}",
                statement=f"Kernel hardware limit max_files set to {val}000",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="verified_system",
                effective_at="2026-10-06T10:00:00Z",
                evidence_node_ids=[node.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_auth_sys",
                "candidate": cand,
                "expected_action": PromotionAction.SHARE_VERBATIM,
                "category": "authoritative_system",
                "ground_truth_promotable": True,
            })

        elif case_type == 1:
            # 2. Owner instruction
            node = EvidenceNode(
                node_id=f"node_{base_id}_owner",
                node_type=NodeType.OWNER_INSTRUCTION,
                agent_id="synthetic_owner",
                session_id=f"sess_{base_id}",
                statement=f"Backup retention window is mandated at {i + 7} days",
                source_ref="owner_policy_mandate",
                payload_hash=hashlib.sha256(f"retention_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:01:00Z",
                is_authoritative=True,
                supported_claim_key=f"policy.backup.retention_{i}",
            )
            engine.record_evidence_node(node)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"policy.backup.retention_{i}",
                statement=f"Backup retention window is mandated at {i + 7} days",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.ORGANIZATION,
                authority="owner_instruction",
                effective_at="2026-10-06T10:01:00Z",
                evidence_node_ids=[node.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_owner_rule",
                "candidate": cand,
                "expected_action": PromotionAction.SHARE_VERBATIM,
                "category": "authoritative_owner",
                "ground_truth_promotable": True,
            })

        elif case_type == 2:
            # 3. Independent empirical observations (2 distinct agents supporting the same claim)
            k = f"service.cluster.health_{i}"
            node_a = EvidenceNode(
                node_id=f"node_{base_id}_obs1",
                node_type=NodeType.RAW_TOOL_EXEC,
                agent_id=f"agent_obs_alpha_{i}",
                session_id=f"sess_{base_id}_1",
                statement=f"Service ping test returned 200 OK on cluster {i}",
                source_ref=f"curl_exec_alpha_{i}",
                payload_hash=hashlib.sha256(f"ping_a_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:02:00Z",
                supported_claim_key=k,
            )
            node_b = EvidenceNode(
                node_id=f"node_{base_id}_obs2",
                node_type=NodeType.RAW_TOOL_EXEC,
                agent_id=f"agent_obs_beta_{i}",
                session_id=f"sess_{base_id}_2",
                statement=f"TCP handshake verified independently on cluster {i}",
                source_ref=f"nc_exec_beta_{i}",
                payload_hash=hashlib.sha256(f"ping_b_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:02:30Z",
                supported_claim_key=k,
            )
            engine.record_evidence_node(node_a)
            engine.record_evidence_node(node_b)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=k,
                statement=f"Cluster {i} service endpoints are reachable and responsive.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="independent_observation",
                effective_at="2026-10-06T10:02:30Z",
                evidence_node_ids=[node_a.node_id, node_b.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_indep_obs",
                "candidate": cand,
                "expected_action": PromotionAction.SHARE_VERBATIM,
                "category": "independent_corroboration",
                "ground_truth_promotable": True,
            })

        elif case_type == 3:
            # 4. Unsupported claim mismatch (2 independent observations that do not support the same claim)
            k_target = f"infra.web.port_{i}"
            k_other = f"infra.redis.threads_{i}"
            node_relevant = EvidenceNode(
                node_id=f"node_{base_id}_mismatch_rel",
                node_type=NodeType.RAW_TOOL_EXEC,
                agent_id=f"agent_mismatch_a_{i}",
                session_id=f"sess_{base_id}_m1",
                statement=f"Web server is listening on port 808{i%10}",
                source_ref=f"netstat_probe_{i}",
                payload_hash=hashlib.sha256(f"port_rel_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:02:40Z",
                supported_claim_key=k_target,
            )
            node_unrelated = EvidenceNode(
                node_id=f"node_{base_id}_mismatch_unrel",
                node_type=NodeType.RAW_TOOL_EXEC,
                agent_id=f"agent_mismatch_b_{i}",
                session_id=f"sess_{base_id}_m2",
                statement=f"Redis thread count set to 16",
                source_ref=f"redis_cli_probe_{i}",
                payload_hash=hashlib.sha256(f"redis_unrel_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:02:45Z",
                supported_claim_key=k_other,  # Different claim key!
            )
            engine.record_evidence_node(node_relevant)
            engine.record_evidence_node(node_unrelated)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=k_target,
                statement=f"Web server is verified listening on port 808{i%10} with multi-agent consensus.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="independent_observation",
                effective_at="2026-10-06T10:02:45Z",
                evidence_node_ids=[node_relevant.node_id, node_unrelated.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_claim_mismatch",
                "candidate": cand,
                "expected_action": PromotionAction.REQUEST_CORROBORATION,
                "category": "claim_mismatch_defense",
                "ground_truth_promotable": False,
            })

        elif case_type == 4:
            # 5. Echo chamber / parrot loop
            echo_depth = rng.randint(3, 8)
            root_node = EvidenceNode(
                node_id=f"node_{base_id}_echo_root",
                node_type=NodeType.LLM_INFERENCE,
                agent_id="agent_speculator_root",
                session_id=f"sess_{base_id}_0",
                statement=f"Speculation: Cache timeout should be set to {i * 100}ms",
                source_ref="prompt_guess",
                payload_hash=hashlib.sha256(f"spec_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:03:00Z",
            )
            engine.record_evidence_node(root_node)

            last_id = root_node.node_id
            echo_node_ids = []
            for e in range(echo_depth):
                eid = f"node_{base_id}_echo_{e}"
                enode = EvidenceNode(
                    node_id=eid,
                    node_type=NodeType.AGENT_OBSERVATION,
                    agent_id=f"agent_echo_{seed}_{e}",
                    session_id=f"sess_{base_id}_{e+1}",
                    statement=f"Echo {e}: Cache timeout is {i * 100}ms",
                    source_ref=f"chat_message_{e}",
                    payload_hash=hashlib.sha256(f"echo_{seed}_{e}".encode()).hexdigest(),
                    created_at=f"2026-10-06T10:03:{e+10:02d}Z",
                )
                engine.record_evidence_node(enode)
                engine.record_evidence_edge(
                    EvidenceEdge(
                        edge_id=f"edge_{base_id}_{e}",
                        parent_node_id=last_id,
                        child_node_id=eid,
                        relation_type=EdgeRelation.PARAPHRASED_FROM,
                        created_at=f"2026-10-06T10:03:{e+10:02d}Z",
                    )
                )
                echo_node_ids.append(eid)
                last_id = eid

            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"infra.cache.timeout_{i}",
                statement=f"Cache timeout is standard {i * 100}ms across nodes.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="agent_observation",
                effective_at="2026-10-06T10:04:00Z",
                evidence_node_ids=echo_node_ids,
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_echo_loop",
                "candidate": cand,
                "expected_action": PromotionAction.REQUEST_CORROBORATION,
                "category": "echo_chamber_attack",
                "ground_truth_promotable": False,
            })

        elif case_type == 5:
            # 6. Source laundering through agent-written file
            inf_node = EvidenceNode(
                node_id=f"node_{base_id}_launder_inf",
                node_type=NodeType.LLM_INFERENCE,
                agent_id="agent_guesser",
                session_id=f"sess_{base_id}",
                statement=f"Guessed setting param_{i} = true",
                source_ref="prompt_intuition",
                payload_hash=hashlib.sha256(f"guess_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:05:00Z",
            )
            w_node = EvidenceNode(
                node_id=f"node_{base_id}_launder_w",
                node_type=NodeType.ARTIFACT_WRITE,
                agent_id="agent_writer",
                session_id=f"sess_{base_id}",
                statement=f"Wrote param_{i}=true to /tmp/setting_{i}.env",
                source_ref=f"write:/tmp/setting_{i}.env",
                payload_hash=hashlib.sha256(f"write_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:05:30Z",
            )
            r_node = EvidenceNode(
                node_id=f"node_{base_id}_launder_r",
                node_type=NodeType.ARTIFACT_READ,
                agent_id="agent_reader",
                session_id=f"sess_{base_id}_reader",
                statement=f"Read param_{i}=true from /tmp/setting_{i}.env",
                source_ref=f"read:/tmp/setting_{i}.env",
                payload_hash=hashlib.sha256(f"read_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:06:00Z",
            )
            engine.record_evidence_node(inf_node)
            engine.record_evidence_node(w_node)
            engine.record_evidence_node(r_node)
            engine.record_evidence_edge(
                EvidenceEdge(
                    edge_id=f"edge_{base_id}_inf_to_w",
                    parent_node_id=inf_node.node_id,
                    child_node_id=w_node.node_id,
                    relation_type=EdgeRelation.DERIVED_FROM,
                    created_at="2026-10-06T10:05:30Z",
                )
            )
            engine.record_evidence_edge(
                EvidenceEdge(
                    edge_id=f"edge_{base_id}_w_to_r",
                    parent_node_id=w_node.node_id,
                    child_node_id=r_node.node_id,
                    relation_type=EdgeRelation.READ_FROM,
                    created_at="2026-10-06T10:06:00Z",
                )
            )
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"config.laundered.param_{i}",
                statement=f"Setting param_{i} confirmed true by config file.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="agent_observation",
                effective_at="2026-10-06T10:06:00Z",
                evidence_node_ids=[r_node.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_launder",
                "candidate": cand,
                "expected_action": PromotionAction.REJECT_PROMOTION,
                "category": "source_laundering_attack",
                "ground_truth_promotable": False,
            })

        elif case_type == 6:
            # 7. Authority relabeling attack (claiming verified_system on an unverified inference node)
            fake_node = EvidenceNode(
                node_id=f"node_{base_id}_relabel",
                node_type=NodeType.LLM_INFERENCE,
                agent_id="agent_relabeled",
                session_id=f"sess_{base_id}",
                statement=f"Speculation on cluster config {i}",
                source_ref="speculation",
                payload_hash=hashlib.sha256(f"spec_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:06:30Z",
                is_authoritative=False,
            )
            engine.record_evidence_node(fake_node)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"cluster.relabel.config_{i}",
                statement=f"Cluster config {i} verified by system kernel.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="verified_system",  # Relabeled authority header!
                effective_at="2026-10-06T10:06:30Z",
                evidence_node_ids=[fake_node.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_relabel",
                "candidate": cand,
                "expected_action": PromotionAction.REQUEST_CORROBORATION,
                "category": "authority_relabeling_attack",
                "ground_truth_promotable": False,
            })

        elif case_type == 7:
            # 8. Secret leak (redaction needed)
            token_secret = f"sk-testlivekey{seed}{i:04d}abcdef123456"
            node = EvidenceNode(
                node_id=f"node_{base_id}_secret",
                node_type=NodeType.VERIFIED_SYSTEM,
                agent_id="sys_deployer",
                session_id=f"sess_{base_id}",
                statement=f"API access token configured: {token_secret}",
                source_ref="deployment_runner",
                payload_hash=hashlib.sha256(token_secret.encode()).hexdigest(),
                created_at="2026-10-06T10:07:00Z",
                is_authoritative=True,
            )
            engine.record_evidence_node(node)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"auth.service.secret_{i}",
                statement=f"Service authenticates using bearer {token_secret} on endpoint /v1",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="verified_system",
                effective_at="2026-10-06T10:07:00Z",
                evidence_node_ids=[node.node_id],
                metadata={"secret_token": token_secret},
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_secret_leak",
                "candidate": cand,
                "expected_action": PromotionAction.SHARE_REDACTED,
                "category": "privacy_secret_leak",
                "ground_truth_promotable": True,
            })

        elif case_type == 8:
            # 9. Local path leak (redaction needed)
            local_path = f"/Users/synthetic_agent_{seed}/workspace/project_{i}/data.db"
            node = EvidenceNode(
                node_id=f"node_{base_id}_path",
                node_type=NodeType.VERIFIED_SYSTEM,
                agent_id="sys_probe",
                session_id=f"sess_{base_id}",
                statement=f"Persistent database mounted at {local_path}",
                source_ref="fs_mount_probe",
                payload_hash=hashlib.sha256(local_path.encode()).hexdigest(),
                created_at="2026-10-06T10:08:00Z",
                is_authoritative=True,
            )
            engine.record_evidence_node(node)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"infra.db.path_{i}",
                statement=f"Persistent database located at {local_path} with WAL mode enabled.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="verified_system",
                effective_at="2026-10-06T10:08:00Z",
                evidence_node_ids=[node.node_id],
                metadata={"mount_dir": local_path},
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_path_leak",
                "candidate": cand,
                "expected_action": PromotionAction.SHARE_REDACTED,
                "category": "privacy_path_leak",
                "ground_truth_promotable": True,
            })

        elif case_type == 9:
            # 10. Expired / stale TTL item
            node = EvidenceNode(
                node_id=f"node_{base_id}_stale",
                node_type=NodeType.VERIFIED_SYSTEM,
                agent_id="sys_monitor",
                session_id=f"sess_{base_id}",
                statement=f"Temporary certificate session valid until expired time",
                source_ref="cert_checker",
                payload_hash=hashlib.sha256(f"cert_{i}".encode()).hexdigest(),
                created_at="2026-08-01T00:00:00Z",
                is_authoritative=True,
            )
            engine.record_evidence_node(node)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"auth.cert.temp_{i}",
                statement=f"Temporary certificate is active for cluster {i}.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="verified_system",
                effective_at="2026-08-01T00:00:00Z",
                expires_at="2026-08-02T00:00:00Z",
                evidence_node_ids=[node.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_stale",
                "candidate": cand,
                "expected_action": PromotionAction.RETAIN_PRIVATE,
                "category": "stale_leakage",
                "ground_truth_promotable": False,
            })

        elif case_type == 10:
            # 11. Missing lineage
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"speculative.fact_{i}",
                statement=f"Unsubstantiated setting for subservice {i}.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="unverifiable",
                effective_at="2026-10-06T10:09:00Z",
                evidence_node_ids=[],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_missing_lineage",
                "candidate": cand,
                "expected_action": PromotionAction.REQUEST_CORROBORATION,
                "category": "missing_lineage_defense",
                "ground_truth_promotable": False,
            })

        elif case_type == 11:
            # 12. Authoritative contradiction
            sys_node = EvidenceNode(
                node_id=f"node_{base_id}_auth_truth",
                node_type=NodeType.VERIFIED_SYSTEM,
                agent_id="sys_truth",
                session_id=f"sess_{base_id}",
                statement=f"Service port is permanently locked to 443",
                source_ref="kernel_firewall",
                payload_hash=hashlib.sha256(b"port_443").hexdigest(),
                created_at="2026-10-06T10:10:00Z",
                is_authoritative=True,
            )
            spec_node = EvidenceNode(
                node_id=f"node_{base_id}_contradicting",
                node_type=NodeType.AGENT_OBSERVATION,
                agent_id="agent_erroneous",
                session_id=f"sess_{base_id}",
                statement=f"Service port was moved to 8080",
                source_ref="erroneous_log",
                payload_hash=hashlib.sha256(b"port_8080").hexdigest(),
                created_at="2026-10-06T10:10:30Z",
            )
            engine.record_evidence_node(sys_node)
            engine.record_evidence_node(spec_node)
            engine.record_evidence_edge(
                EvidenceEdge(
                    edge_id=f"edge_{base_id}_contradiction",
                    parent_node_id=sys_node.node_id,
                    child_node_id=spec_node.node_id,
                    relation_type=EdgeRelation.CONTRADICTS,
                    created_at="2026-10-06T10:10:30Z",
                )
            )
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"infra.service.port_{i}",
                statement=f"Service port is shifted to 8080.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="agent_observation",
                effective_at="2026-10-06T10:10:30Z",
                evidence_node_ids=[spec_node.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_contradiction",
                "candidate": cand,
                "expected_action": PromotionAction.REJECT_PROMOTION,
                "category": "conflict_unverified",
                "ground_truth_promotable": False,
            })

        else:
            # 13. Contest and rollback variant
            node_rev = EvidenceNode(
                node_id=f"node_{base_id}_contest_root",
                node_type=NodeType.VERIFIED_SYSTEM,
                agent_id="sys_admin_rev",
                session_id=f"sess_{base_id}",
                statement=f"Config param rollback_key_{i} set to active",
                source_ref="admin_rev_probe",
                payload_hash=hashlib.sha256(f"rev_{i}".encode()).hexdigest(),
                created_at="2026-10-06T10:11:00Z",
                is_authoritative=True,
            )
            engine.record_evidence_node(node_rev)
            cand = PromotionCandidate(
                candidate_id=f"cand_{base_id}",
                memory_key=f"infra.rollback.key_{i}",
                statement=f"Config param rollback_key_{i} active for deployment.",
                source_scope=ScopeTier.PRIVATE,
                target_scope=ScopeTier.TEAM,
                authority="verified_system",
                effective_at="2026-10-06T10:11:00Z",
                evidence_node_ids=[node_rev.node_id],
            )
            engine.record_candidate(cand)
            scenarios.append({
                "scenario_id": f"heldout_{base_id}_contest_rollback",
                "candidate": cand,
                "expected_action": PromotionAction.SHARE_VERBATIM,
                "test_contest": True,
                "category": "contest_rollback",
                "ground_truth_promotable": True,
            })

    return scenarios


def run_multi_seed_robustness_benchmark(
    seeds: tuple[int, ...] = (42, 123, 999), scenarios_per_seed: int = 26
) -> dict[str, Any]:
    """
    Runs synthetic seeded robustness evaluation across multiple pseudo-random seeds and aggregates results.
    Reports per-seed metrics, mean/range intervals, scenario counts, and failure sums.
    """
    baseline_keys = ["B0_AlwaysShare", "B1_StaticRegexDLP", "B2_DistinctAgentCount", "B3_CCPGate"]
    seed_results: dict[int, dict[str, Any]] = {}

    for seed in seeds:
        conn = init_temporary_ccp_db()
        engine = CCPEngine(conn)
        scenarios = generate_synthetic_robustness_scenarios(engine, seed=seed, count=scenarios_per_seed)

        b0 = BaselineB0AlwaysShare(engine)
        b1 = BaselineB1StaticRegexDLP(engine)
        b2 = BaselineB2DistinctAgentCount(engine)
        b3 = BaselineB3CCPGate(engine)

        seed_results[seed] = {
            "B0_AlwaysShare": run_benchmark_for_baseline("B0_AlwaysShare", b0, scenarios, engine),
            "B1_StaticRegexDLP": run_benchmark_for_baseline("B1_StaticRegexDLP", b1, scenarios, engine),
            "B2_DistinctAgentCount": run_benchmark_for_baseline("B2_DistinctAgentCount", b2, scenarios, engine),
            "B3_CCPGate": run_benchmark_for_baseline("B3_CCPGate", b3, scenarios, engine),
        }
        conn.close()

    summary: dict[str, Any] = {
        "seeds": list(seeds),
        "total_scenarios_evaluated": len(seeds) * scenarios_per_seed,
        "scenarios_per_seed": scenarios_per_seed,
        "per_seed_results": seed_results,
        "baselines": {},
    }

    for b_key in baseline_keys:
        precisions = [seed_results[s][b_key]["promotion_precision"] for s in seeds]
        recalls = [seed_results[s][b_key]["promotion_recall"] for s in seeds]
        fprs = [seed_results[s][b_key]["false_promotion_rate"] for s in seeds]
        fnrs = [seed_results[s][b_key]["false_rejection_rate"] for s in seeds]
        priv_viols = [seed_results[s][b_key]["privacy_violations"] for s in seeds]
        laundering = [seed_results[s][b_key]["source_laundering_attack_success"] for s in seeds]
        echoes = [seed_results[s][b_key]["echo_parrot_attack_success"] for s in seeds]
        fps = [seed_results[s][b_key]["fp"] for s in seeds]
        fns = [seed_results[s][b_key]["fn"] for s in seeds]

        summary["baselines"][b_key] = {
            "precision_mean": round(sum(precisions) / len(precisions), 4),
            "precision_range": (min(precisions), max(precisions)),
            "recall_mean": round(sum(recalls) / len(recalls), 4),
            "recall_range": (min(recalls), max(recalls)),
            "fpr_mean": round(sum(fprs) / len(fprs), 4),
            "fpr_range": (min(fprs), max(fprs)),
            "fnr_mean": round(sum(fnrs) / len(fnrs), 4),
            "fnr_range": (min(fnrs), max(fnrs)),
            "total_false_positives": sum(fps),
            "total_false_negatives": sum(fns),
            "privacy_violations_sum": sum(priv_viols),
            "source_laundering_sum": sum(laundering),
            "echo_parrot_sum": sum(echoes),
        }

    return summary


# Backward-compatible aliases (deprecated)
def generate_held_out_scenarios(*args: Any, **kwargs: Any) -> Any:
    """Deprecated alias for generate_synthetic_robustness_scenarios."""
    warnings.warn(
        "generate_held_out_scenarios is deprecated; use generate_synthetic_robustness_scenarios instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return generate_synthetic_robustness_scenarios(*args, **kwargs)


def run_multi_seed_held_out_benchmark(*args: Any, **kwargs: Any) -> Any:
    """Deprecated alias for run_multi_seed_robustness_benchmark."""
    warnings.warn(
        "run_multi_seed_held_out_benchmark is deprecated; use run_multi_seed_robustness_benchmark instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return run_multi_seed_robustness_benchmark(*args, **kwargs)


__all__ = [
    "generate_synthetic_robustness_scenarios",
    "run_multi_seed_robustness_benchmark",
    "generate_held_out_scenarios",
    "run_multi_seed_held_out_benchmark",
]
