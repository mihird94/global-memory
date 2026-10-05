"""Formal verification suite for GMS Cognitive Governance & Laws:
- Test Case 1: Non-Monotonic Supersession (Law 3)
- Test Case 2: Contradiction Quarantine on Ambiguous Updates
- Test Case 3: Zero-Trust Authority Escalation Guard (Law 5)
- Test Case 4: Predicate & Scope Isolation (The Aurora Bug)
- Test Case 5: Temporal Exponential Decay Scoring (W(t))
"""

import json
import math
import sqlite3
import time
from pathlib import Path
import pytest

from consolidation_policy import classify_candidate
from memory_authority import validate_authority
from context_packet import build_context_packet
from context_retrieval_planner import retrieve
import memory_mcp_server


@pytest.fixture
def clean_memory_env(tmp_path, monkeypatch):
    root = tmp_path / "memories"
    root.mkdir()
    (root / "operational").mkdir()
    (root / "semantic").mkdir()
    (root / "projects" / "infra").mkdir(parents=True)
    db_path = root / "gms_trust.sqlite"
    monkeypatch.setattr(memory_mcp_server, "MEM_ROOT", root)
    monkeypatch.setattr(memory_mcp_server, "DB_PATH", db_path)
    memory_mcp_server.init_db(db_path)
    return root, db_path


# ──────────────────────────────────────────────────────────────────────────────
# Test Case 1: Non-Monotonic Supersession (Law 3)
# ──────────────────────────────────────────────────────────────────────────────

def test_case_1_non_monotonic_supersession(clean_memory_env):
    root, db_path = clean_memory_env
    facts_file = root / "semantic" / "facts.json"

    # Initial State in gms_claims and facts.json
    facts_file.write_text(json.dumps({"infra.python_version": "3.10"}))

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, confidence, created_at)
        VALUES ('semantic', 'infra.python_version', '3.10', 'developer', 'main', 'active', 1.0, '2026-09-01T00:00:00Z')
    """)
    claim_v1_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Incoming Candidate with explicit supersession
    candidate_v2 = {
        "key": "infra.python_version",
        "statement": "Python version upgraded to 3.13",
        "freshness": {
            "supersedes": ["infra.python_version"],
            "effective_at": "2026-10-01T00:00:00Z"
        }
    }

    # Step 1: Run through classify_candidate
    existing_facts = {"infra.python_version": "3.10"}
    classification = classify_candidate(candidate_v2, existing_facts)

    # Assertion 1: Operation is classified as supersede
    assert classification["operation"] == "supersede"
    assert classification["requires_review"] is True

    # Step 2: Stage and review candidate to execute supersession transition
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cand_payload = {
        "statement": "Python version upgraded to 3.13",
        "provenance": {"extractor": "ci_pipeline", "author": "developer"},
        "scope": {"project": "infra"}
    }
    cand_id = "cand_py313"
    cur.execute("""
        INSERT INTO gms_context_candidates (
            candidate_id, schema_version, record_type, canonical_key,
            payload_json, source_fingerprint, content_hash,
            extractor_agent, prompt_version, review_status
        ) VALUES (?, 'gms-context-record-v1', 'fact', 'infra.python_version', ?, 'fp_123', 'hash_v2_py313', 'ci_pipeline', 'v1', 'proposed')
    """, (cand_id, json.dumps(cand_payload)))
    conn.commit()
    conn.close()

    # Apply supersede review action
    rev_res = memory_mcp_server.review_context_candidate(
        candidate_id=cand_id,
        action="supersede",
        reviewer="mihir",
        rationale="Verified Python 3.13 upgrade across test runners",
        db_path=db_path
    )
    assert rev_res["status"] == "accepted"

    # Step 3: Assertions on gms_claims transitions
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Assertion 2: gms_claims status for v1 transitions to 'superseded'
    cur.execute("SELECT status, confidence FROM gms_claims WHERE claim_id = ?", (claim_v1_id,))
    v1_row = cur.fetchone()
    assert v1_row[0] == "superseded"
    assert v1_row[1] == 0.0

    # Assertion 3: gms_claims for v2 is created with supersedes_claim_id == claim_v1.id
    cur.execute("""
        SELECT claim_id, value, status, supersedes_claim_id
        FROM gms_claims
        WHERE memory_key = 'infra.python_version' AND status = 'active'
    """)
    v2_rows = cur.fetchall()
    assert len(v2_rows) == 1
    v2_claim = v2_rows[0]
    assert v2_claim[2] == "active"
    assert v2_claim[3] == claim_v1_id  # supersedes_claim_id points to v1

    # Assertion 4: Querying active facts returns ONLY v2
    cur.execute("""
        SELECT value FROM gms_claims WHERE memory_key = 'infra.python_version' AND status = 'active'
    """)
    active_claims = cur.fetchall()
    assert len(active_claims) == 1
    assert "3.13" in active_claims[0][0]

    facts_on_disk = json.loads(facts_file.read_text(encoding="utf-8"))
    assert "3.13" in facts_on_disk["infra.python_version"]
    assert "3.10" not in facts_on_disk["infra.python_version"]
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test Case 2: Contradiction Quarantine on Ambiguous Updates
# ──────────────────────────────────────────────────────────────────────────────

def test_case_2_contradiction_quarantine_on_ambiguous_updates():
    existing_facts = {"infra.db_port": "5432"}

    # Incoming unauthenticated candidate missing supersedes & effective_at
    candidate = {
        "key": "infra.db_port",
        "statement": "Database port is 3306",
        "freshness": {}  # Missing supersedes and effective_at
    }

    result = classify_candidate(candidate, existing_facts)

    # Assertion 1: Operation is flagged as contradict
    assert result["operation"] == "contradict"

    # Assertion 2: Review is strictly required, auto-promotion halted
    assert result["requires_review"] is True
    assert result["automatic_promotion"] is False
    assert "alias-equivalent key has a different value" in result["reason"]

    # Assertion 3: Active fact remains untouched in existing storage
    assert existing_facts["infra.db_port"] == "5432"


# ──────────────────────────────────────────────────────────────────────────────
# Test Case 3: Zero-Trust Authority Escalation Guard (Law 5)
# ──────────────────────────────────────────────────────────────────────────────

def test_case_3_zero_trust_authority_escalation_guard():
    malicious_record = {
        "record_type": "policy",
        "authority": "llm_inference",
        "provenance": {"author": "mihir", "extractor": "subagent-9"},
        "review": {"status": "accepted"}
    }

    result = validate_authority(malicious_record, authenticated_user=False)

    # Assertion 1: Validation fails
    assert result["valid"] is False

    # Assertion 2: Rejects unauthorized author=mihir forgery
    assert any("author=mihir requires an authenticated user action" in err for err in result["errors"])

    # Assertion 3: Rejects auto-accepted AI-inferred policy
    assert any("AI-inferred decisions and policies require explicit human review" in err for err in result["errors"])


# ──────────────────────────────────────────────────────────────────────────────
# Test Case 4: Predicate & Scope Isolation (The Aurora Bug)
# ──────────────────────────────────────────────────────────────────────────────

def test_case_4_predicate_and_scope_isolation(clean_memory_env):
    root, db_path = clean_memory_env
    from schemas import ProceduralTaskContract, ScopeModel

    # Setup: Stored procedure: ProceduralTaskContract with scope.applies_to = ["provisioned_rds"] and action "--timeout=30m"
    proc_contract = ProceduralTaskContract(
        name="rds_maintenance_procedure",
        trigger="maintenance_window",
        action="--timeout=30m",
        scope=ScopeModel(
            level="project",
            project="infra",
            applies_to=["provisioned_rds"]
        )
    )

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    proc_context = {"scope": proc_contract.scope.model_dump()}
    cur.execute("""
        INSERT INTO gms_procedures (name, "trigger", action, context, status)
        VALUES (?, ?, ?, ?, 'active')
    """, (proc_contract.name, proc_contract.trigger, proc_contract.action, json.dumps(proc_context)))
    conn.commit()
    conn.close()

    # Query context target service is "aurora_serverless"
    query_ctx = {
        "project": "infra",
        "target_service": "aurora_serverless"
    }

    packet = build_context_packet(
        root,
        query="procedure maintenance window configuration",
        project="infra",
        query_context=query_ctx
    )

    # Assertion 1: Retrieval planner excludes the '--timeout=30m' procedure from items
    matching_items = [it for it in packet["items"] if "--timeout=30m" in str(it.get("statement", ""))]
    assert len(matching_items) == 0, f"Scope leak: found {matching_items} in context packet"

    # Assertion 2: Filter logs show scope mismatch on applies_to
    all_filter_logs = packet.get("filter_logs", []) + [om.get("reason", "") for om in packet.get("omission_manifest", [])]
    scope_mismatches = [log for log in all_filter_logs if "Scope mismatch on applies_to" in log]
    assert len(scope_mismatches) >= 1, f"Expected scope mismatch in filter logs, got: {all_filter_logs}"
    assert "provisioned_rds" in scope_mismatches[0]
    assert "aurora_serverless" in scope_mismatches[0]


# ──────────────────────────────────────────────────────────────────────────────
# Test Case 5: Temporal Exponential Decay Scoring (W(t))
# ──────────────────────────────────────────────────────────────────────────────

def test_case_5_temporal_exponential_decay_scoring():
    from datetime import datetime, timedelta
    from memoryctl import get_decay_rate_for_item

    decay_lambda = 0.05
    raw_similarity = 0.85
    now = datetime(2026, 10, 5, 12, 0, 0)

    # Document A: Timestamped t = now - 1 day, raw cosine similarity = 0.85
    doc_A_date = now - timedelta(days=1)
    doc_A = {
        "source": f"history/{doc_A_date.strftime('%Y-%m-%d')}.md",
        "text": "Operational memory record regarding active cluster configuration",
        "raw_score": raw_similarity
    }

    # Document B: Timestamped t = now - 180 days, raw cosine similarity = 0.85
    doc_B_date = now - timedelta(days=180)
    doc_B = {
        "source": f"history/{doc_B_date.strftime('%Y-%m-%d')}.md",
        "text": "Operational memory record regarding active cluster configuration",
        "raw_score": raw_similarity
    }

    # Execute scoring through GMS retrieval decay engine (memoryctl)
    days_ago_A = (now - doc_A_date).days
    rate_A = get_decay_rate_for_item(doc_A["source"], doc_A["text"], decay_lambda)
    decay_factor_A = math.exp(-rate_A * days_ago_A)
    fused_score_A = float(doc_A["raw_score"] * decay_factor_A)

    days_ago_B = (now - doc_B_date).days
    rate_B = get_decay_rate_for_item(doc_B["source"], doc_B["text"], decay_lambda)
    decay_factor_B = math.exp(-rate_B * days_ago_B)
    fused_score_B = float(doc_B["raw_score"] * decay_factor_B)

    # Assertion 1: Final fused score of Document A is significantly higher than Document B
    assert fused_score_A > fused_score_B
    assert fused_score_A > (fused_score_B * 5000.0), f"Doc A ({fused_score_A}) not significantly higher than Doc B ({fused_score_B})"

    # Assertion 2: Ratio of scores matches the exponential decay curve within 1% tolerance
    actual_ratio = fused_score_A / fused_score_B
    # Theoretical ratio: e^(-lambda * 1) / e^(-lambda * 180) = e^(0.05 * 179)
    theoretical_ratio = math.exp(decay_lambda * (days_ago_B - days_ago_A))

    relative_error = abs(actual_ratio - theoretical_ratio) / theoretical_ratio
    assert relative_error < 0.01, f"Decay curve ratio error {relative_error:.6f} exceeds 1% tolerance"
    assert math.isclose(actual_ratio, theoretical_ratio, rel_tol=0.0001)
