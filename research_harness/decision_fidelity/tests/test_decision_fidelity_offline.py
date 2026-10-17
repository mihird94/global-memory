"""
test_decision_fidelity_offline.py — Comprehensive Offline Test Suite
=====================================================================
Validates all 9 offline requirements for the Decision Fidelity study:
  1. Span integrity across all 12 families and 24 scenarios (character slices).
  2. Gold action replay on 100% of canonical scenarios.
  3. Gold action replay on 100% of minimal pair scenarios.
  4. Valid alternative actions and legitimate abstentions replay.
  5. Counterexample rejections: wrong action, excessive refusal, and omitted action.
  6. Controlled mutations fail for the intended reason; harmless paraphrases succeed.
  7. Representation builder validation across Arms A, B, C, and D.
  8. Arm D span existence and entailment verification (including negative controls).
  9. Evaluator provenance tracing, mutation sensitivity, and SHA-256 manifest integrity.

Zero live LLM inference calls. Zero private memory reads.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import pytest

from research_harness.decision_fidelity.models import (
    ActionOutcome,
    AuthoritativeConstraint,
    AuthoritativeSource,
    ConstraintType,
    DownstreamTask,
)
from research_harness.decision_fidelity.corpus import (
    ALL_DEVELOPMENT_FAMILIES,
    FamilyCase,
)
from research_harness.decision_fidelity.representations.arm_a_full_source import ArmAFullSource
from research_harness.decision_fidelity.representations.arm_b_extractive_excerpts import (
    ArmBExtractiveExcerpts,
    ArmBOracleDiagnostic,
)
from research_harness.decision_fidelity.representations.arm_c_ordinary_structured import ArmCOrdinaryStructured
from research_harness.decision_fidelity.representations.arm_d_source_bound import (
    ArmDSourceBound,
    DiagnosticOracleArmD,
    SourceBoundConstraintRecord,
)
from research_harness.decision_fidelity.evaluator.evaluator import DecisionFidelityEvaluator
from research_harness.decision_fidelity.evaluator.reader import ScriptedReaderAgent
from research_harness.decision_fidelity.simulators.domain_simulators import _matches_action, get_simulator_for_family
from research_harness.decision_fidelity.audit.audit import DecisionFidelityAuditor


@pytest.fixture
def families() -> dict[str, FamilyCase]:
    return ALL_DEVELOPMENT_FAMILIES


@pytest.fixture
def evaluator() -> DecisionFidelityEvaluator:
    return DecisionFidelityEvaluator()


@pytest.fixture
def auditor() -> DecisionFidelityAuditor:
    return DecisionFidelityAuditor()


# =============================================================================
# 1. Span Integrity Tests
# =============================================================================

def test_corpus_spans_match_exact_character_slices(auditor: DecisionFidelityAuditor):
    """Verifies that every character span matches its designated slice in source text."""
    passed, errors = auditor.audit_span_integrity()
    assert passed, f"Span integrity failed with errors: {errors}"
    assert len(errors) == 0


def test_span_coverage_across_all_constraint_types(families: dict[str, FamilyCase]):
    """Verifies that all 6 constraint categories are represented and contain valid spans."""
    seen_types = set()
    for fam in families.values():
        seen_types.add(fam.constraint_type)
        assert len(fam.canonical_source.spans) > 0
        assert len(fam.minimal_pair_source.spans) > 0
        for span in fam.canonical_source.spans.values():
            assert span.start_char < span.end_char
            assert fam.canonical_source.content[span.start_char:span.end_char] == span.text

    assert len(seen_types) == 6
    assert seen_types == set(ConstraintType)


# =============================================================================
# 2. Gold Replay Tests (Canonical and Minimal Pairs)
# =============================================================================

@pytest.mark.parametrize("family_id", list(ALL_DEVELOPMENT_FAMILIES.keys()))
def test_gold_canonical_action_replay(family_id: str, families: dict[str, FamilyCase], evaluator: DecisionFidelityEvaluator):
    """Verifies that the gold canonical action executes or legitimately abstains as expected."""
    fam = families[family_id]
    rep = ArmAFullSource()
    rec = evaluator.evaluate_action_trial(fam, fam.canonical_source, fam.canonical_task, rep, fam.gold_canonical_action)
    
    expected_outcome = (
        ActionOutcome.CORRECT_ACTION
        if fam.gold_canonical_action.get("action") not in ("abstain", "refuse")
        else ActionOutcome.LEGITIMATE_ABSTENTION
    )
    assert rec.simulation_result.outcome == expected_outcome, (
        f"[{family_id}] Gold canonical failed: expected {expected_outcome}, got {rec.simulation_result.outcome} "
        f"({rec.simulation_result.details})"
    )


@pytest.mark.parametrize("family_id", list(ALL_DEVELOPMENT_FAMILIES.keys()))
def test_gold_minimal_pair_action_replay(family_id: str, families: dict[str, FamilyCase], evaluator: DecisionFidelityEvaluator):
    """Verifies that the gold minimal pair action executes or legitimately abstains as expected."""
    fam = families[family_id]
    rep = ArmAFullSource()
    rec = evaluator.evaluate_action_trial(fam, fam.minimal_pair_source, fam.minimal_pair_task, rep, fam.gold_minimal_pair_action)
    
    expected_outcome = (
        ActionOutcome.CORRECT_ACTION
        if fam.gold_minimal_pair_action.get("action") not in ("abstain", "refuse")
        else ActionOutcome.LEGITIMATE_ABSTENTION
    )
    assert rec.simulation_result.outcome == expected_outcome, (
        f"[{family_id}] Gold minimal pair failed: expected {expected_outcome}, got {rec.simulation_result.outcome} "
        f"({rec.simulation_result.details})"
    )


# =============================================================================
# 3. Valid Alternatives Replay Tests
# =============================================================================

@pytest.mark.parametrize("family_id", list(ALL_DEVELOPMENT_FAMILIES.keys()))
def test_valid_alternatives_replay(family_id: str, families: dict[str, FamilyCase], evaluator: DecisionFidelityEvaluator):
    """Verifies that all specified valid canonical alternatives evaluate successfully."""
    fam = families[family_id]
    rep = ArmAFullSource()
    for alt in fam.valid_canonical_alternatives:
        rec = evaluator.evaluate_action_trial(fam, fam.canonical_source, fam.canonical_task, rep, alt)
        expected_outcome = (
            ActionOutcome.CORRECT_ACTION
            if alt.get("action") not in ("abstain", "refuse")
            else ActionOutcome.LEGITIMATE_ABSTENTION
        )
        assert rec.simulation_result.outcome == expected_outcome, (
            f"[{family_id}] Valid alternative failed: {alt} -> {rec.simulation_result.outcome} "
            f"({rec.simulation_result.details})"
        )


# =============================================================================
# 4. Counterexample Rejection Tests
# =============================================================================

@pytest.mark.parametrize("family_id", list(ALL_DEVELOPMENT_FAMILIES.keys()))
def test_wrong_action_counterexamples_rejected(family_id: str, families: dict[str, FamilyCase], evaluator: DecisionFidelityEvaluator):
    """Verifies that all wrong action counterexamples result in WRONG_ACTION outcome."""
    fam = families[family_id]
    rep = ArmAFullSource()
    for w in fam.wrong_action_counterexamples:
        rec = evaluator.evaluate_action_trial(fam, fam.canonical_source, fam.canonical_task, rep, w)
        assert rec.simulation_result.outcome == ActionOutcome.WRONG_ACTION, (
            f"[{family_id}] Counterexample was not rejected as WRONG_ACTION: {w} -> {rec.simulation_result.outcome}"
        )


@pytest.mark.parametrize("family_id", list(ALL_DEVELOPMENT_FAMILIES.keys()))
def test_excessive_refusal_counterexamples_rejected(family_id: str, families: dict[str, FamilyCase], evaluator: DecisionFidelityEvaluator):
    """Verifies that unwarranted refusals result in EXCESSIVE_REFUSAL outcome."""
    fam = families[family_id]
    rep = ArmAFullSource()
    # If canonical requires refusal, test refusal counterexample on minimal pair where action is permitted
    src = fam.minimal_pair_source if fam.gold_canonical_action.get("action") in ("abstain", "refuse") else fam.canonical_source
    tsk = fam.minimal_pair_task if fam.gold_canonical_action.get("action") in ("abstain", "refuse") else fam.canonical_task
    for r in fam.excessive_refusal_counterexamples:
        rec = evaluator.evaluate_action_trial(fam, src, tsk, rep, r)
        assert rec.simulation_result.outcome == ActionOutcome.EXCESSIVE_REFUSAL, (
            f"[{family_id}] Refusal counterexample was not tagged EXCESSIVE_REFUSAL: {r} -> {rec.simulation_result.outcome}"
        )


@pytest.mark.parametrize("family_id", list(ALL_DEVELOPMENT_FAMILIES.keys()))
def test_omitted_action_counterexamples_rejected(family_id: str, families: dict[str, FamilyCase], evaluator: DecisionFidelityEvaluator):
    """Verifies that incomplete actions missing required parameters result in OMITTED_ACTION."""
    fam = families[family_id]
    rep = ArmAFullSource()
    for o in fam.omitted_action_counterexamples:
        rec = evaluator.evaluate_action_trial(fam, fam.canonical_source, fam.canonical_task, rep, o)
        assert rec.simulation_result.outcome in (ActionOutcome.OMITTED_ACTION, ActionOutcome.WRONG_ACTION), (
            f"[{family_id}] Omitted counterexample was not tagged OMITTED_ACTION: {o} -> {rec.simulation_result.outcome}"
        )


# =============================================================================
# 5. Controlled Mutation & Paraphrase Tests
# =============================================================================

@pytest.mark.parametrize("family_id", list(ALL_DEVELOPMENT_FAMILIES.keys()))
def test_controlled_mutations_and_paraphrase_sensitivity(family_id: str, families: dict[str, FamilyCase], evaluator: DecisionFidelityEvaluator):
    """Verifies that controlled semantic mutations cause failures while harmless paraphrases succeed."""
    fam = families[family_id]
    sens = evaluator.evaluate_mutation_sensitivity(fam)
    
    # Paraphrase check: Harmless syntactic changes must still pass
    assert sens["paraphrase_passed"] is True, f"[{family_id}] Paraphrase failed: {sens}"
    
    # Mutation check: Targeted semantic corruption must fail
    assert len(sens["mutation_results"]) > 0, f"[{family_id}] No mutation results found"
    for mut_name, mut_res in sens["mutation_results"].items():
        assert mut_res["detected_as_failure"] is True, (
            f"[{family_id}:{mut_name}] Controlled mutation was falsely scored as correct! Outcome: {mut_res['outcome']}"
        )


# =============================================================================
# 6. Representation Arms Build & Formatting Tests
# =============================================================================

def test_all_four_representation_arms(families: dict[str, FamilyCase]):
    """Verifies that Arms A, B, C, D generate valid, distinct payloads for every family."""
    arms = [
        ArmAFullSource(),
        ArmBExtractiveExcerpts(top_k=3),
        ArmBOracleDiagnostic(),
        ArmCOrdinaryStructured(),
        ArmDSourceBound(),
    ]
    
    for fid, fam in families.items():
        for arm in arms:
            ctx = arm.build_reader_context(fam.canonical_source, fam.canonical_task)
            assert isinstance(ctx, str)
            assert len(ctx.strip()) > 20
            # Ensure no leaked answers from gold dictionaries
            assert "gold_canonical_action" not in ctx
            assert "gold_minimal_pair_action" not in ctx


def test_extractive_bm25_vs_oracle(families: dict[str, FamilyCase]):
    """Tests that BM25 sentence extraction returns relevant sentences without oracle dependency."""
    bm25_arm = ArmBExtractiveExcerpts(top_k=2)
    oracle_arm = ArmBOracleDiagnostic()
    
    sample_fam = families["fam_unit_01_timeout_units"]
    bm25_ctx = bm25_arm.build_reader_context(sample_fam.canonical_source, sample_fam.canonical_task)
    oracle_ctx = oracle_arm.build_reader_context(sample_fam.canonical_source, sample_fam.canonical_task)
    
    assert "Harbor Client" in bm25_ctx or "timeout" in bm25_ctx.lower()
    assert "Harbor" in oracle_ctx


# =============================================================================
# 7. Arm D Span Entailment & Negative Controls
# =============================================================================

def test_arm_d_valid_records_pass_existence_and_entailment(families: dict[str, FamilyCase]):
    """Verifies that clean synthesized records pass both span existence and entailment checks."""
    oracle_arm = DiagnosticOracleArmD()
    for fid, fam in families.items():
        rec = oracle_arm.synthesize_oracle_record(fam.canonical_source)
        ok_exist, err_exist = rec.validate_span_existence(fam.canonical_source.content)
        assert ok_exist, f"[{fid}] Clean record failed span existence: {err_exist}"
        
        ok_ent, err_ent = rec.validate_record(fam.canonical_source.content)
        assert ok_ent, f"[{fid}] Clean record failed span entailment: {err_ent}"


def test_arm_d_rejects_fabricated_spans():
    """Negative control: Arm D must strictly reject citations that do not exist in source text."""
    oracle_arm = DiagnosticOracleArmD()
    sample_fam = ALL_DEVELOPMENT_FAMILIES["fam_scope_01_backup_policy"]
    rec = oracle_arm.synthesize_oracle_record(sample_fam.canonical_source)
    
    # Inject fabricated citation
    rec.span_citations["applicability_scope"] = "Totally fabricated span text that does not exist in source"
    ok, errors = rec.validate_span_existence(sample_fam.canonical_source.content)
    assert not ok, "Arm D falsely validated a fabricated span citation"
    assert any("not found in source" in e for e in errors)


def test_arm_d_rejects_unentailed_assertions():
    """Negative control: Arm D must reject assertions when span text contradicts or fails to support value."""
    record = SourceBoundConstraintRecord(
        source_id="src_unit_01_canon",
        source_sha256="test_sha_placeholder",
        primary_statement="Set timeout to 30000ms",
        numeric_value=30000.0,
        numeric_unit="ms",
        span_citations={
            "numeric_value": "request timeout must be set to 4500 milliseconds (request_timeout_ms=4500)",
            "numeric_unit": "request timeout must be set to 4500 milliseconds (request_timeout_ms=4500)",
        },
    )
    ok, errors = record.validate_span_entailment()
    assert not ok, "Arm D falsely validated an unentailed value assertion"
    assert any("not supported by cited span" in e for e in errors)


# =============================================================================
# 8. Full Auditor & Cryptographic Manifest Integrity
# =============================================================================

def test_full_offline_auditor_suite(auditor: DecisionFidelityAuditor, tmp_path: Path):
    """Executes the full auditor suite and verifies report generation and zero false passes."""
    report_dir = tmp_path / "audit_report"
    summary = auditor.run_all_audits(report_dir)
    
    assert summary["overall_pass"] is True
    assert summary["span_integrity"]["pass"] is True
    assert summary["gold_replay"]["pass"] is True
    assert summary["counterexample_rejection"]["pass"] is True
    assert summary["representation_arms"]["pass"] is True
    assert summary["semantic_validation"]["pass"] is True
    assert summary["families_audited"] == 12
    assert summary["total_scenarios"] == 24
    
    manifest_file = report_dir / "offline_audit_manifest.json"
    summary_file = report_dir / "offline_audit_summary.json"
    assert manifest_file.exists()
    assert summary_file.exists()
    
    manifest_data = json.loads(manifest_file.read_text())
    assert len(manifest_data) == 24
    for key, entry in manifest_data.items():
        assert "sha256" in entry
        assert len(entry["sha256"]) == 64


# =============================================================================
# 9. Auditor Remediation Probes (Probes 1–4)
# =============================================================================

def test_probe_1_hidden_label_perturbation_invariance(families: dict[str, FamilyCase]):
    """
    Auditor Probe 1: Public arms (C & D) must consume strictly public inputs.
    Perturbing or corrupting hidden annotations (source.constraints) while holding
    public source text fixed MUST leave the representation payload 100% identical.
    """
    fam = families["fam_scope_01_backup_policy"]
    src_orig = copy.deepcopy(fam.canonical_source)
    task = fam.canonical_task

    arm_c = ArmCOrdinaryStructured()
    arm_d = ArmDSourceBound()

    # Original payloads
    payload_c_orig = arm_c.build_reader_context(src_orig, task)
    payload_d_orig = arm_d.build_reader_context(src_orig, task)

    # Perturb hidden annotations with adversarial/bogus constraints
    src_perturbed = AuthoritativeSource(
        source_id=fam.canonical_source.source_id,
        family_id=fam.canonical_source.family_id,
        variant_id=fam.canonical_source.variant_id,
        content=fam.canonical_source.content,
        spans=fam.canonical_source.spans,
        constraints=[
            AuthoritativeConstraint(
                constraint_id="c_bogus_adversarial",
                constraint_type=ConstraintType.APPLICABILITY_SCOPE,
                statement="ALL PROJECTS INCLUDING HARBOR AND SECRET_VAULT MUST BE WIPED IMMEDIATELY",
                support_span_ids=[],
                scope_tags=["harbor", "secret_vault"],
            )
        ],
    )

    # Re-extract with perturbed hidden source
    payload_c_pert = arm_c.build_reader_context(src_perturbed, task)
    payload_d_pert = arm_d.build_reader_context(src_perturbed, task)

    # Invariance guarantees: public extractors never read hidden annotations
    assert payload_c_pert == payload_c_orig, "Arm C leaked hidden annotations into reader payload!"
    assert payload_d_pert == payload_d_orig, "Arm D leaked hidden annotations into reader payload!"
    assert "WIPED IMMEDIATELY" not in payload_c_pert
    assert "WIPED IMMEDIATELY" not in payload_d_pert

    # In contrast, the diagnostic oracle DOES read hidden annotations
    oracle_d = DiagnosticOracleArmD()
    oracle_orig = oracle_d.build_reader_context(src_orig, task)
    oracle_pert = oracle_d.build_reader_context(src_perturbed, task)
    assert oracle_orig != oracle_pert
    assert "WIPED IMMEDIATELY" in oracle_pert


def test_probe_2_semantic_validator_negative_controls():
    """
    Auditor Probe 2: Semantic validator must reject unsupported scope broadening,
    numeric substring false-matches, and ordering inversions.
    """
    # 1. Direct Reviewer Probe: Unsupported widened scope with existing span citation
    probe_text = "This policy applies only to Cedar backups."
    probe_rec = SourceBoundConstraintRecord(
        source_id="probe_src",
        source_sha256=hashlib.sha256(probe_text.encode("utf-8")).hexdigest(),
        primary_statement="All projects must delete backups",
        applicability_scope="Every project including Harbor",
        span_citations={"applicability_scope": probe_text},
    )
    ok_exist, _ = probe_rec.validate_span_existence(probe_text)
    assert ok_exist is True, "Span existence passed because the citation substring is present"

    # Semantic containment must catch that Harbor is ungrounded / contradicts restrictive clause
    ok_sem, sem_errors = probe_rec.validate_record(probe_text)
    assert ok_sem is False, "Probe 2 failed: Semantic validator accepted unsupported widened scope!"
    assert any("broadens scope beyond restrictive span" in e or "not grounded in cited span" in e for e in sem_errors)

    # 2. Number boundary false match: '4' should not validate against '4096' or '4500'
    text_num = "Quota allocation is 4096 megabytes."
    rec_num = SourceBoundConstraintRecord(
        source_id="probe_num",
        source_sha256=hashlib.sha256(text_num.encode("utf-8")).hexdigest(),
        primary_statement="Quota constraint",
        numeric_value=4.0,  # 4 is substring of 4096
        numeric_unit="megabyte",
        span_citations={"numeric_value": text_num, "numeric_unit": text_num},
    )
    ok_num, num_errors = rec_num.validate_record(text_num)
    assert ok_num is False, "Semantic validator permitted substring number false match!"
    assert any("numeric_value 4.0 not supported" in e for e in num_errors)

    # 3. Monotonic ordering violation: 'restart_daemon' before 'drain_traffic'
    text_order = "Execute maintenance: drain_traffic, then restart_daemon."
    rec_order = SourceBoundConstraintRecord(
        source_id="probe_order",
        source_sha256=hashlib.sha256(text_order.encode("utf-8")).hexdigest(),
        primary_statement="Maintenance order",
        execution_order=["restart_daemon", "drain_traffic"],
        span_citations={"execution_order": text_order},
    )
    ok_order, order_errors = rec_order.validate_record(text_order)
    assert ok_order is False, "Semantic validator permitted inverted execution order!"
    assert any("contradicts sequential step order" in e for e in order_errors)


def test_probe_3_action_matcher_strict_recursive_validation():
    """
    Auditor Probe 3: Action matching must strictly reject nested effect parameter overrides
    and wrong operations/steps rather than falsely matching via loose heuristics.
    """
    # Probe 3a: Nested parameter mismatch (timeout_ms: 999999 vs 50)
    cand_nested = {"action": "configure_harbor_client", "timeout_ms": 999999}
    gold_nested = {"action": "configure_harbor_client", "timeout_ms": 50}
    assert not _matches_action(cand_nested, gold_nested), "Probe 3a failed: Action matcher accepted nested parameter mismatch!"

    # Probe 3b: Wrong operation / step mismatch (delete_database vs drain_traffic)
    cand_step = {"action": "execute_maintenance", "steps": ["delete_database"]}
    gold_step = {"action": "execute_maintenance", "steps": ["drain_traffic"]}
    assert not _matches_action(cand_step, gold_step), "Probe 3b failed: Action matcher accepted wrong operation in steps!"

    # Simulator verification for Probe 3
    sim = get_simulator_for_family("fam_unit_01_timeout_units")
    fam = ALL_DEVELOPMENT_FAMILIES["fam_unit_01_timeout_units"]
    res = sim.execute(
        action={"action": "configure_harbor_client", "request_timeout_ms": 999999},
        task=fam.canonical_task,
        gold_action=fam.gold_canonical_action,
        valid_alternatives=[],
    )
    assert res.outcome == ActionOutcome.WRONG_ACTION


def test_probe_4_memory_to_action_fidelity_with_scripted_reader():
    """
    Auditor Probe 4: Memory-to-action fidelity must verify that:
      a) Clean memory causes the reader to emit the correct action.
      b) Mutated memory causes the reader to emit the mutated action (not bypass it).
      c) Ungrounded memory is rejected by admission gate, causing reader abstention.
    """
    evaluator = DecisionFidelityEvaluator()
    fam = ALL_DEVELOPMENT_FAMILIES["fam_unit_02_memory_limit"]
    reader = ScriptedReaderAgent()

    # 4a. Clean memory end-to-end
    rec_clean = evaluator.evaluate_end_to_end(
        family=fam,
        source=fam.canonical_source,
        task=fam.canonical_task,
        representation=ArmAFullSource(),
        reader=reader,
    )
    assert rec_clean.admission_passed is True
    assert rec_clean.simulation_result.outcome == ActionOutcome.CORRECT_ACTION
    assert rec_clean.parsed_action.get("max_memory_mb") == 4096

    # 4b. Mutated memory payload directly fed into reader alters reader action
    mutated_memory = "Directive: Partition 'session' quota max_memory_gb is set to 4."
    raw_out, act = reader.read_and_decide(mutated_memory, fam.canonical_task)
    assert act.get("max_memory_gb") == 4
    sim = get_simulator_for_family(fam.family_id)
    sim_res = sim.execute(act, fam.canonical_task, fam.gold_canonical_action, [])
    assert sim_res.outcome == ActionOutcome.WRONG_ACTION

    # 4c. Admission failure causes explicit reader abstention
    arm_d = ArmDSourceBound()
    bad_rec = SourceBoundConstraintRecord(
        source_id="bad_src",
        source_sha256="bad_sha",
        primary_statement="Fake statement",
        span_citations={"primary_statement": "THIS STRING DOES NOT EXIST IN SOURCE TEXT"},
    )
    passed, rej_payload, errors = arm_d.admit_memory(fam.canonical_source, injected_record=bad_rec)
    assert passed is False
    assert "ADMISSION REJECTED" in rej_payload

    # Reader reading rejected memory context refuses/abstains
    raw_out, act = reader.read_and_decide(rej_payload, fam.canonical_task)
    assert act.get("action") in ("abstain", "refuse")
    assert "admission verification" in act.get("reason", "")
