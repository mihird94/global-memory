"""
evaluator.py — End-to-End Decision Fidelity Evaluator
=====================================================
Executes and traces the full provenance chain:
  source -> public extraction -> admission gate -> reader agent ->
  raw reader output -> parsed action -> domain simulator effect -> outcome

Provides:
  1. evaluate_end_to_end: Full memory-to-action trial with injectable reader.
  2. evaluate_action_trial: Direct action-oracle trial testing action execution against simulator.
  3. evaluate_mutation_sensitivity: Tests both representation mutation and action mutation.
  4. aggregate_results: Computes accuracy, error breakdowns, and constraint-level metrics.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional, Union
from research_harness.decision_fidelity.corpus import FamilyCase
from research_harness.decision_fidelity.models import (
    ActionOutcome,
    AuthoritativeSource,
    ConstraintType,
    DownstreamTask,
    EvaluationRecord,
    PublicSourceInput,
    SimulationResult,
)
from research_harness.decision_fidelity.representations.base import BaseMemoryRepresentation
from research_harness.decision_fidelity.simulators.domain_simulators import get_simulator_for_family
from research_harness.decision_fidelity.evaluator.reader import BaseReaderAgent, ScriptedReaderAgent


class DecisionFidelityEvaluator:
    """Evaluates decision fidelity across representation arms, reader agents, and task families."""

    def __init__(self):
        pass

    def evaluate_end_to_end(
        self,
        family: FamilyCase,
        source: Union[AuthoritativeSource, PublicSourceInput],
        task: DownstreamTask,
        representation: BaseMemoryRepresentation,
        reader: Optional[BaseReaderAgent] = None,
        raw_writer_json: Optional[str] = None,
    ) -> EvaluationRecord:
        """
        Full end-to-end provenance trial:
          1. Public extraction from public source input (no hidden labels).
          2. Admission gate verification (span existence + semantic checks).
          3. Reader agent reads admitted context and emits action.
          4. Domain simulator executes action against domain state models.
        """
        reader = reader or ScriptedReaderAgent()
        pub = source.to_public_input() if hasattr(source, "to_public_input") else source

        # 1 & 2. Representation extraction and admission
        admission_passed, admitted_payload, admission_errors = representation.admit_memory(pub, task)
        token_costs = representation.estimate_token_cost(pub, task)

        # 3. Reader execution
        raw_reader_output, parsed_action = reader.read_and_decide(admitted_payload, task)

        # 4. Domain simulator execution
        sim = get_simulator_for_family(family.family_id)
        is_canonical = "canonical" in pub.variant_id
        gold_action = family.gold_canonical_action if is_canonical else family.gold_minimal_pair_action
        valid_alts = family.valid_canonical_alternatives if is_canonical else []

        sim_res = sim.execute(
            action=parsed_action,
            task=task,
            gold_action=gold_action,
            valid_alternatives=valid_alts,
        )

        # 5. Categorize failure tags
        failure_tags = []
        if sim_res.outcome == ActionOutcome.WRONG_ACTION:
            failure_tags.append(f"wrong_{family.constraint_type.value}")
        elif sim_res.outcome == ActionOutcome.EXCESSIVE_REFUSAL:
            failure_tags.append("excessive_refusal")
        elif sim_res.outcome == ActionOutcome.OMITTED_ACTION:
            failure_tags.append("omitted_required_action")
        elif sim_res.outcome == ActionOutcome.INVALID_OUTPUT:
            failure_tags.append("invalid_output_syntax")

        return EvaluationRecord(
            family_id=family.family_id,
            variant_id=pub.variant_id,
            constraint_type=family.constraint_type,
            representation_arm=representation.arm_id,
            source_id=pub.source_id,
            source_sha256=pub.sha256,
            task_id=task.task_id,
            raw_memory_payload=admitted_payload,
            admitted_memory_payload=admitted_payload,
            admission_passed=admission_passed,
            admission_errors=admission_errors,
            raw_writer_response=raw_writer_json,
            raw_reader_output=raw_reader_output,
            parsed_action=parsed_action,
            simulation_result=sim_res,
            constraint_failure_tags=failure_tags,
            is_diagnostic_oracle=representation.is_diagnostic_oracle,
            estimated_prompt_tokens=token_costs.get("reader_prompt_tokens", 0),
            estimated_completion_tokens=max(1, len(raw_reader_output) // 4),
        )

    def evaluate_action_trial(
        self,
        family: FamilyCase,
        source: Union[AuthoritativeSource, PublicSourceInput],
        task: DownstreamTask,
        representation: BaseMemoryRepresentation,
        action: dict[str, Any],
        raw_reader_output: Optional[str] = None,
    ) -> EvaluationRecord:
        """
        Action-oracle unit evaluation: Directly evaluates an action dictionary
        against the domain simulator to verify simulator contracts.
        """
        pub = source.to_public_input() if hasattr(source, "to_public_input") else source
        admission_passed, admitted_payload, admission_errors = representation.admit_memory(pub, task)
        token_costs = representation.estimate_token_cost(pub, task)

        sim = get_simulator_for_family(family.family_id)
        is_canonical = "canonical" in pub.variant_id
        gold_action = family.gold_canonical_action if is_canonical else family.gold_minimal_pair_action
        valid_alts = family.valid_canonical_alternatives if is_canonical else []

        sim_res = sim.execute(
            action=action,
            task=task,
            gold_action=gold_action,
            valid_alternatives=valid_alts,
        )

        failure_tags = []
        if sim_res.outcome == ActionOutcome.WRONG_ACTION:
            failure_tags.append(f"wrong_{family.constraint_type.value}")
        elif sim_res.outcome == ActionOutcome.EXCESSIVE_REFUSAL:
            failure_tags.append("excessive_refusal")
        elif sim_res.outcome == ActionOutcome.OMITTED_ACTION:
            failure_tags.append("omitted_required_action")
        elif sim_res.outcome == ActionOutcome.INVALID_OUTPUT:
            failure_tags.append("invalid_output_syntax")

        return EvaluationRecord(
            family_id=family.family_id,
            variant_id=pub.variant_id,
            constraint_type=family.constraint_type,
            representation_arm=representation.arm_id,
            source_id=pub.source_id,
            source_sha256=pub.sha256,
            task_id=task.task_id,
            raw_memory_payload=admitted_payload,
            admitted_memory_payload=admitted_payload,
            admission_passed=admission_passed,
            admission_errors=admission_errors,
            raw_reader_output=raw_reader_output or json.dumps(action),
            parsed_action=action,
            simulation_result=sim_res,
            constraint_failure_tags=failure_tags,
            is_diagnostic_oracle=representation.is_diagnostic_oracle,
            estimated_prompt_tokens=token_costs.get("reader_prompt_tokens", 0),
            estimated_completion_tokens=max(1, len(json.dumps(action)) // 4),
        )

    def evaluate_mutation_sensitivity(
        self,
        family: FamilyCase,
        representation: Optional[BaseMemoryRepresentation] = None,
        reader: Optional[BaseReaderAgent] = None,
    ) -> dict[str, Any]:
        """
        Tests whether controlled memory mutations trigger the expected failure outcomes,
        and whether harmless paraphrases remain correct.
        Supports both direct action-oracle evaluation and end-to-end reader derivation.
        """
        if representation is None:
            from research_harness.decision_fidelity.representations.arm_a_full_source import ArmAFullSource
            representation = ArmAFullSource()

        reader = reader or ScriptedReaderAgent()
        results = {}

        # 1. Canonical Gold via end-to-end reader
        gold_rec = self.evaluate_end_to_end(
            family=family,
            source=family.canonical_source,
            task=family.canonical_task,
            representation=representation,
            reader=reader,
        )
        expected_gold = ActionOutcome.CORRECT_ACTION if family.gold_canonical_action.get("action") not in ("abstain", "refuse") else ActionOutcome.LEGITIMATE_ABSTENTION
        results["gold_passes"] = (gold_rec.simulation_result.outcome == expected_gold)

        # 2. Valid alternatives (action-oracle check)
        alt_passes = []
        for alt in family.valid_canonical_alternatives:
            alt_rec = self.evaluate_action_trial(
                family=family,
                source=family.canonical_source,
                task=family.canonical_task,
                representation=representation,
                action=alt,
            )
            expected_alt = ActionOutcome.CORRECT_ACTION if alt.get("action") not in ("abstain", "refuse") else ActionOutcome.LEGITIMATE_ABSTENTION
            alt_passes.append(alt_rec.simulation_result.outcome == expected_alt)
        results["alternatives_pass"] = all(alt_passes) if alt_passes else True

        # 3. Harmless paraphrase check via end-to-end reader
        if family.paraphrase_source_text:
            para_pub = PublicSourceInput(
                source_id=f"{family.canonical_source.source_id}_para",
                family_id=family.family_id,
                variant_id="canonical_paraphrase",
                content=family.paraphrase_source_text,
                sha256="",
            )
            para_rec = self.evaluate_end_to_end(
                family=family,
                source=para_pub,
                task=family.canonical_task,
                representation=representation,
                reader=reader,
            )
            results["paraphrase_passed"] = (para_rec.simulation_result.outcome == expected_gold)
        else:
            results["paraphrase_passed"] = True

        # 4. Controlled mutations check
        mutation_results = {}
        for mut_name, mut_action in family.controlled_mutations.items():
            if "action" not in mut_action:
                test_action = dict(family.gold_canonical_action)
                test_action.update(mut_action)
            else:
                test_action = mut_action

            mut_rec = self.evaluate_action_trial(
                family=family,
                source=family.canonical_source,
                task=family.canonical_task,
                representation=representation,
                action=test_action,
            )
            is_caught = mut_rec.simulation_result.outcome in (
                ActionOutcome.WRONG_ACTION,
                ActionOutcome.OMITTED_ACTION,
                ActionOutcome.EXCESSIVE_REFUSAL,
                ActionOutcome.INVALID_OUTPUT,
            )
            mutation_results[mut_name] = {
                "detected_as_failure": is_caught,
                "outcome": mut_rec.simulation_result.outcome,
            }

        results["mutations_caught"] = all(m["detected_as_failure"] for m in mutation_results.values())
        results["mutation_results"] = mutation_results
        return results

    def aggregate_results(self, records: list[EvaluationRecord]) -> dict[str, Any]:
        """Aggregates a list of evaluation records into structured metrics."""
        total = len(records)
        if total == 0:
            return {"total_trials": 0}

        counts = {
            "correct_actions": sum(1 for r in records if r.simulation_result.outcome == ActionOutcome.CORRECT_ACTION),
            "legitimate_abstentions": sum(1 for r in records if r.simulation_result.outcome == ActionOutcome.LEGITIMATE_ABSTENTION),
            "wrong_actions": sum(1 for r in records if r.simulation_result.outcome == ActionOutcome.WRONG_ACTION),
            "excessive_refusals": sum(1 for r in records if r.simulation_result.outcome == ActionOutcome.EXCESSIVE_REFUSAL),
            "omitted_actions": sum(1 for r in records if r.simulation_result.outcome == ActionOutcome.OMITTED_ACTION),
            "invalid_outputs": sum(1 for r in records if r.simulation_result.outcome == ActionOutcome.INVALID_OUTPUT),
            "admission_rejections": sum(1 for r in records if not r.admission_passed),
        }
        success_count = counts["correct_actions"] + counts["legitimate_abstentions"]
        accuracy = success_count / total

        return {
            "total_trials": total,
            "accuracy": round(accuracy, 4),
            "counts": counts,
        }
