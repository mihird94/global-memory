"""
audit.py — Offline Integrity & Replay Auditor for Decision Fidelity
===================================================================
Conducts comprehensive offline audit checks without LLM inference:
  1. Corpus Span Integrity: All character spans match exact source slices.
  2. Gold Contract Replay: 100% of gold actions pass on both canonical and minimal pairs.
  3. Alternative Action Replay: 100% of valid alternative serializations pass.
  4. Counterexample Rejection: 100% of wrong-action, excessive-refusal, and omitted actions fail.
  5. Representation Integrity: All 4 arms build valid non-empty reader contexts from public text.
  6. Semantic Validator & Admission Audit: Validates records and strictly catches bypass probes.
  7. Cryptographic Manifest: Computes SHA-256 digests across all authoritative source definitions.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from research_harness.decision_fidelity.corpus import ALL_DEVELOPMENT_FAMILIES, FamilyCase
from research_harness.decision_fidelity.evaluator.evaluator import DecisionFidelityEvaluator
from research_harness.decision_fidelity.models import ActionOutcome
from research_harness.decision_fidelity.representations.arm_a_full_source import ArmAFullSource
from research_harness.decision_fidelity.representations.arm_b_extractive_excerpts import ArmBExtractiveExcerpts
from research_harness.decision_fidelity.representations.arm_c_ordinary_structured import ArmCOrdinaryStructured
from research_harness.decision_fidelity.representations.arm_d_source_bound import (
    ArmDSourceBound,
    DiagnosticOracleArmD,
    SourceBoundConstraintRecord,
)


class DecisionFidelityAuditor:
    """Audits the decision fidelity corpus, simulators, and representations offline."""

    def __init__(self, families: dict[str, FamilyCase] | None = None):
        self.families = families or ALL_DEVELOPMENT_FAMILIES
        self.evaluator = DecisionFidelityEvaluator()

    def audit_span_integrity(self) -> tuple[bool, list[str]]:
        """Verifies that all defined spans match the exact source text slice."""
        errors = []
        for fid, fam in self.families.items():
            for var_label, src in [("canonical", fam.canonical_source), ("minimal_pair", fam.minimal_pair_source)]:
                for sp_id, span in src.spans.items():
                    actual = src.content[span.start_char : span.end_char]
                    if actual != span.text:
                        errors.append(f"[{fid}:{var_label}] Span '{sp_id}' slice mismatch: got '{actual}' expected '{span.text}'")
        return len(errors) == 0, errors

    def audit_gold_and_alternatives_replay(self) -> tuple[bool, dict[str, Any]]:
        """Verifies that gold actions and valid alternatives pass across all families."""
        results = {"canonical_passed": 0, "canonical_total": 0, "pair_passed": 0, "pair_total": 0, "alternatives_passed": 0, "failures": []}
        rep = ArmAFullSource()

        for fid, fam in self.families.items():
            # 1. Canonical Gold
            results["canonical_total"] += 1
            rec_c = self.evaluator.evaluate_action_trial(fam, fam.canonical_source, fam.canonical_task, rep, fam.gold_canonical_action)
            expected_c = ActionOutcome.CORRECT_ACTION if fam.gold_canonical_action.get("action") not in ("abstain", "refuse") else ActionOutcome.LEGITIMATE_ABSTENTION
            if rec_c.simulation_result.outcome == expected_c:
                results["canonical_passed"] += 1
            else:
                results["failures"].append(f"[{fid}:canonical] Gold action failed: {rec_c.simulation_result}")

            # 2. Minimal Pair Gold
            results["pair_total"] += 1
            rec_p = self.evaluator.evaluate_action_trial(fam, fam.minimal_pair_source, fam.minimal_pair_task, rep, fam.gold_minimal_pair_action)
            expected_p = ActionOutcome.CORRECT_ACTION if fam.gold_minimal_pair_action.get("action") not in ("abstain", "refuse") else ActionOutcome.LEGITIMATE_ABSTENTION
            if rec_p.simulation_result.outcome == expected_p:
                results["pair_passed"] += 1
            else:
                results["failures"].append(f"[{fid}:minimal_pair] Gold action failed: {rec_p.simulation_result}")

            # 3. Valid Alternatives
            for alt in fam.valid_canonical_alternatives:
                rec_a = self.evaluator.evaluate_action_trial(fam, fam.canonical_source, fam.canonical_task, rep, alt)
                expected_alt = ActionOutcome.CORRECT_ACTION if alt.get("action") not in ("abstain", "refuse") else ActionOutcome.LEGITIMATE_ABSTENTION
                if rec_a.simulation_result.outcome == expected_alt:
                    results["alternatives_passed"] += 1
                else:
                    results["failures"].append(f"[{fid}:alt] Alternative failed: {alt} -> {rec_a.simulation_result.outcome}")

        all_passed = (results["canonical_passed"] == results["canonical_total"]) and (results["pair_passed"] == results["pair_total"]) and (len(results["failures"]) == 0)
        return all_passed, results

    def audit_counterexamples_rejection(self) -> tuple[bool, dict[str, Any]]:
        """Verifies that wrong actions, excessive refusals, and omitted actions are rejected."""
        results = {"rejected_wrong": 0, "rejected_refusal": 0, "rejected_omitted": 0, "false_passes": []}
        rep = ArmAFullSource()

        for fid, fam in self.families.items():
            # Wrong action counterexamples
            for w in fam.wrong_action_counterexamples:
                rec = self.evaluator.evaluate_action_trial(fam, fam.canonical_source, fam.canonical_task, rep, w)
                if rec.simulation_result.outcome == ActionOutcome.WRONG_ACTION:
                    results["rejected_wrong"] += 1
                else:
                    results["false_passes"].append(f"[{fid}] Wrong action counterexample did not yield WRONG_ACTION: {w} -> {rec.simulation_result.outcome}")

            # Excessive refusal counterexamples
            for r in fam.excessive_refusal_counterexamples:
                use_pair = fam.gold_canonical_action.get("action") in ("abstain", "refuse")
                target_src = fam.minimal_pair_source if use_pair else fam.canonical_source
                target_task = fam.minimal_pair_task if use_pair else fam.canonical_task
                rec = self.evaluator.evaluate_action_trial(fam, target_src, target_task, rep, r)
                if rec.simulation_result.outcome == ActionOutcome.EXCESSIVE_REFUSAL:
                    results["rejected_refusal"] += 1
                else:
                    results["false_passes"].append(f"[{fid}] Excessive refusal did not yield EXCESSIVE_REFUSAL: {r} -> {rec.simulation_result.outcome}")

            # Omitted action counterexamples
            for o in fam.omitted_action_counterexamples:
                rec = self.evaluator.evaluate_action_trial(fam, fam.canonical_source, fam.canonical_task, rep, o)
                if rec.simulation_result.outcome in (ActionOutcome.OMITTED_ACTION, ActionOutcome.WRONG_ACTION):
                    results["rejected_omitted"] += 1
                else:
                    results["false_passes"].append(f"[{fid}] Omitted action did not yield OMITTED/WRONG: {o} -> {rec.simulation_result.outcome}")

        all_rejected = len(results["false_passes"]) == 0
        return all_rejected, results

    def audit_representation_arms(self) -> tuple[bool, dict[str, Any]]:
        """Verifies that all 4 arms build non-empty, well-formatted reader payloads without hidden label access."""
        arms = [ArmAFullSource(), ArmBExtractiveExcerpts(), ArmCOrdinaryStructured(), ArmDSourceBound()]
        results = {arm.arm_id: {"tested": 0, "passed": 0} for arm in arms}

        for fid, fam in self.families.items():
            pub_input = fam.canonical_source.to_public_input()
            for arm in arms:
                results[arm.arm_id]["tested"] += 1
                ctx = arm.build_reader_context(pub_input, fam.canonical_task)
                if len(ctx.strip()) > 30 and (fam.family_id in ctx or pub_input.source_id in ctx):
                    results[arm.arm_id]["passed"] += 1

        all_ok = all(d["passed"] == d["tested"] for d in results.values())
        return all_ok, results

    def audit_span_entailment_validator(self) -> tuple[bool, list[str]]:
        """Tests that Arm D validation accepts well-grounded records and rejects ungrounded bypasses."""
        oracle_arm = DiagnosticOracleArmD()
        errors = []
        for fid, fam in self.families.items():
            rec = oracle_arm.synthesize_oracle_record(fam.canonical_source)
            ok_exist, err_exist = rec.validate_span_existence(fam.canonical_source.content)
            if not ok_exist:
                errors.extend(f"[{fid}] Valid record span existence failed: {e}" for e in err_exist)
            ok_val, err_val = rec.validate_record(fam.canonical_source.content)
            if not ok_val:
                errors.extend(f"[{fid}] Valid record semantic validation failed: {e}" for e in err_val)

        # Negative test 1: Fabricated span
        sample_fam = next(iter(self.families.values()))
        bad_rec = oracle_arm.synthesize_oracle_record(sample_fam.canonical_source)
        bad_rec.span_citations["applicability_scope"] = "THIS STRING DOES NOT EXIST IN THE SOURCE TEXT"
        ok_bad, _ = bad_rec.validate_span_existence(sample_fam.canonical_source.content)
        if ok_bad:
            errors.append("Negative span existence control failed: fabricated span was falsely accepted")

        # Negative test 2: Probe 2 (Unsupported widened scope)
        probe_text = "This policy applies only to Cedar backups."
        probe_rec = SourceBoundConstraintRecord(
            source_id="probe_src",
            source_sha256=hashlib.sha256(probe_text.encode("utf-8")).hexdigest(),
            primary_statement="All projects must delete backups",
            applicability_scope="Every project including Harbor",
            span_citations={"applicability_scope": probe_text},
        )
        ok_probe, _ = probe_rec.validate_record(probe_text)
        if ok_probe:
            errors.append("Probe 2 negative control failed: unsupported widened scope was falsely accepted")

        return len(errors) == 0, errors

    def generate_cryptographic_manifest(self, output_path: Path | None = None) -> dict[str, Any]:
        """Generates a cryptographic manifest of all source texts and SHA-256 digests."""
        manifest = {}
        for fid, fam in self.families.items():
            manifest[f"{fid}:canonical"] = {
                "source_id": fam.canonical_source.source_id,
                "sha256": fam.canonical_source.sha256,
                "span_count": len(fam.canonical_source.spans),
                "constraint_count": len(fam.canonical_source.constraints),
            }
            manifest[f"{fid}:minimal_pair"] = {
                "source_id": fam.minimal_pair_source.source_id,
                "sha256": fam.minimal_pair_source.sha256,
                "span_count": len(fam.minimal_pair_source.spans),
                "constraint_count": len(fam.minimal_pair_source.constraints),
            }

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(manifest, indent=2))
        return manifest

    def run_all_audits(self, report_dir: Path | None = None) -> dict[str, Any]:
        """Runs the entire offline audit suite and returns structured results."""
        ok_spans, err_spans = self.audit_span_integrity()
        ok_gold, res_gold = self.audit_gold_and_alternatives_replay()
        ok_counter, res_counter = self.audit_counterexamples_rejection()
        ok_arms, res_arms = self.audit_representation_arms()
        ok_entail, err_entail = self.audit_span_entailment_validator()

        manifest_path = (report_dir / "offline_audit_manifest.json") if report_dir else None
        manifest = self.generate_cryptographic_manifest(manifest_path)

        overall_pass = ok_spans and ok_gold and ok_counter and ok_arms and ok_entail
        summary = {
            "overall_pass": overall_pass,
            "span_integrity": {"pass": ok_spans, "errors": err_spans},
            "gold_replay": {"pass": ok_gold, "metrics": res_gold},
            "counterexample_rejection": {"pass": ok_counter, "metrics": res_counter},
            "representation_arms": {"pass": ok_arms, "metrics": res_arms},
            "semantic_validation": {"pass": ok_entail, "errors": err_entail},
            "families_audited": len(self.families),
            "total_scenarios": len(self.families) * 2,
        }

        if report_dir:
            summary_path = report_dir / "offline_audit_summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps(summary, indent=2))

        return summary
