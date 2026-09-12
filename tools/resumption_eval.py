"""Real-World Resumption and Retrieval Benchmark Evaluation Suite.

Evaluates retrieval quality and agent continuation readiness across 10 realistic
scenarios derived from project history without synthetic metric inflations.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib import request

from context_retrieval_planner import retrieve
from project_briefing import generate_project_briefing, build_resume_bundle

DEFAULT_AGENT_MODEL = "qwen3:8b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


def _meaningful_tokens(value: str) -> set[str]:
    stop = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
            "of", "on", "or", "that", "the", "this", "to", "was", "were", "with"}
    return {x for x in re.findall(r"[a-z0-9]+", value.lower()) if len(x) > 2 and x not in stop}


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start:end + 1])
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
    return None


def _score_agent_answer(answer: dict[str, Any] | None, bundle: dict[str, Any]) -> dict[str, Any]:
    """Score generated continuation content, never model identity or bundle shape."""
    if not answer:
        return {"passed": False, "schema_valid": False, "checks": {},
                "unsupported_claims": ["No valid JSON object was generated."]}

    briefing = bundle.get("briefing", {})
    expected_goal = str((briefing.get("goal") or {}).get("statement") or "")
    expected_next = str((briefing.get("next_action") or {}).get("statement") or "")
    actual_goal = str(answer.get("goal") or "")
    actual_state = str(answer.get("current_state") or "")
    actual_next = str(answer.get("next_action") or "")
    unfinished = answer.get("unfinished_work")
    evidence_refs = answer.get("evidence_refs")
    uncertainties = answer.get("uncertainties")

    goal_terms = _meaningful_tokens(expected_goal)
    next_terms = _meaningful_tokens(expected_next)
    goal_recall = len(goal_terms & _meaningful_tokens(actual_goal)) / max(1, len(goal_terms))
    next_recall = len(next_terms & _meaningful_tokens(actual_next)) / max(1, len(next_terms))
    task_label = expected_next.split(":", 1)[-1].strip() if ":" in expected_next else expected_next
    task_terms = _meaningful_tokens(task_label)
    current_task_recall = len(task_terms & _meaningful_tokens(actual_state)) / max(1, len(task_terms))

    allowed_refs = {str(item["source"]) for item in briefing.get("inclusion_manifest", []) if item.get("source")}
    allowed_refs.update(str(ref) for ref in (briefing.get("goal") or {}).get("source_refs", []))
    for section in ("current_truth", "active_work", "binding_decisions", "constraints", "blocking_issues", "recent_changes", "verification"):
        for item in briefing.get(section, []):
            if isinstance(item, dict) and item.get("source"):
                allowed_refs.add(str(item["source"]))
    cited = [str(x) for x in evidence_refs] if isinstance(evidence_refs, list) else []
    # A checkpoint may cite an artifact that is nested in a task statement
    # rather than repeated by inclusion_manifest. It is grounded when its
    # exact string occurs anywhere in the supplied bundle.
    serialized_bundle = json.dumps(bundle, sort_keys=True)
    bad_refs = [x for x in cited if x not in allowed_refs and x not in serialized_bundle]

    bundle_text = json.dumps(bundle, sort_keys=True).lower()
    answer_text = json.dumps(answer, sort_keys=True).lower()
    unsupported_literals = sorted({x for x in re.findall(r"\b(?:\d{4}-\d{2}-\d{2}|\d+(?:\.\d+)?%?)\b", answer_text)
                                   if x not in bundle_text})
    stale_markers = [x for x in ("227/227", "8/10", "token-overlap similarity", "50% required-key")
                     if x in answer_text]
    checks = {
        "required_fields": all(k in answer for k in ("goal", "current_state", "unfinished_work", "next_action", "evidence_refs", "uncertainties")),
        "goal_grounded": goal_recall >= 0.35,
        "next_action_grounded": next_recall >= 0.60,
        "current_task_grounded": current_task_recall >= 0.50,
        "unfinished_work_present": isinstance(unfinished, list) and bool(unfinished),
        "evidence_refs_grounded": bool(cited) and not bad_refs,
        "uncertainty_reported": isinstance(uncertainties, list),
        "no_new_numeric_or_date_claims": not unsupported_literals,
        "stale_verification_avoided": not stale_markers,
    }
    unsupported = []
    if bad_refs:
        unsupported.append(f"Unknown evidence references: {', '.join(bad_refs)}")
    if unsupported_literals:
        unsupported.append(f"Numbers/dates absent from bundle: {', '.join(unsupported_literals)}")
    if stale_markers:
        unsupported.append(f"Recorded-not-live state presented as current: {', '.join(stale_markers)}")
    return {"passed": all(checks.values()), "schema_valid": True, "checks": checks,
            "goal_term_recall": round(goal_recall, 3), "next_action_term_recall": round(next_recall, 3),
            "current_task_term_recall": round(current_task_recall, 3),
            "unsupported_claims": unsupported}


def _installed_ollama_models(base_url: str) -> tuple[bool, list[str], str | None]:
    try:
        with request.urlopen(f"{base_url}/api/tags", timeout=5.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return True, [str(m.get("name", "")) for m in payload.get("models", [])], None
    except Exception as exc:
        return False, [], str(exc)


def _unload_ollama_model(model: str, base_url: str) -> bool:
    try:
        req = request.Request(f"{base_url}/api/generate",
                              data=json.dumps({"model": model, "keep_alive": 0}).encode("utf-8"),
                              headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=15.0):
            return True
    except Exception:
        return False


def _run_live_agent_continuation(bundle: dict[str, Any], *, model: str, base_url: str) -> dict[str, Any]:
    online, installed, availability_error = _installed_ollama_models(base_url)
    if not online:
        return {"project_id": bundle.get("project_id"), "model": model, "passed": False,
                "status": "not_run", "reason": f"Ollama unavailable: {availability_error}",
                "model_unload_success": None}
    if model not in installed:
        return {"project_id": bundle.get("project_id"), "model": model, "passed": False,
                "status": "not_run", "reason": "Requested model is not installed; automatic downloads are prohibited.",
                "installed_models": installed, "model_unload_success": None}

    briefing = bundle.get("briefing", {})
    # A continuation agent needs the high-signal packet, not duplicated prompt
    # prose or every low-ranked retrieval candidate. This projection contains
    # only material already present in the generated bundle.
    trial_input = {
        "project_id": bundle.get("project_id"),
        "goal": briefing.get("goal"),
        "active_work": briefing.get("active_work", [])[:1],
        "blocking_issues": briefing.get("blocking_issues", [])[:3],
        "recent_changes": briefing.get("recent_changes", [])[:1],
        "verification_status": {
            "live_verification_available": False,
            "recorded_not_live_items_excluded": len(briefing.get("verification", [])),
        },
        "next_action": briefing.get("next_action"),
    }
    allowed_output_refs: set[str] = set()
    def collect_refs(value: Any, parent_key: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                collect_refs(child, key)
        elif isinstance(value, list):
            for child in value:
                collect_refs(child, parent_key)
        elif parent_key in {"source", "source_refs", "artifact_refs"} and isinstance(value, str) and value:
            allowed_output_refs.add(value)
    collect_refs(trial_input)
    output_schema = {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "current_state": {"type": "string"},
            "unfinished_work": {"type": "array", "items": {"type": "string"}},
            "next_action": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string", "enum": sorted(allowed_output_refs)}},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["goal", "current_state", "unfinished_work", "next_action", "evidence_refs", "uncertainties"],
        "additionalProperties": False,
    }
    prompt = (
        "Act as a fresh continuation agent. Use only the supplied resume bundle; do not use prior knowledge. "
        "Describe the active task in current_state and use only the newest recent_changes item. Recorded verification "
        "claims were deliberately excluded because they are not live proof. Copy the supplied goal.statement and next_action.statement "
        "verbatim into goal and next_action so their fidelity is auditable. Copy evidence references exactly from "
        "source, source_refs, or artifact_refs fields. Do not invent dates, metrics, files, tests, or completed work.\n\nRESUME BUNDLE:\n"
        + json.dumps(trial_input, sort_keys=True)
        + "\n\nReturn only the JSON object required by the response schema."
    )
    payload = {"model": model, "prompt": prompt, "stream": False, "keep_alive": 0,
               "format": output_schema, "options": {"temperature": 0, "num_predict": 400}}
    started = time.perf_counter()
    raw = ""
    inference_error = None
    try:
        req = request.Request(f"{base_url}/api/generate", data=json.dumps(payload).encode("utf-8"),
                              headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=180.0) as response:
            raw = str(json.loads(response.read().decode("utf-8")).get("response") or "")
    except Exception as exc:
        inference_error = str(exc)
    finally:
        unload_ok = _unload_ollama_model(model, base_url)

    if inference_error:
        return {"project_id": bundle.get("project_id"), "model": model, "passed": False,
                "status": "failed", "reason": f"Generation failed: {inference_error}",
                "latency_seconds": round(time.perf_counter() - started, 3), "model_unload_success": unload_ok}
    answer = _extract_json_object(raw)
    scoring = _score_agent_answer(answer, bundle)
    return {"project_id": bundle.get("project_id"), "model": model,
            "passed": scoring["passed"], "status": "passed" if scoring["passed"] else "failed",
            "latency_seconds": round(time.perf_counter() - started, 3), "model_unload_success": unload_ok,
            "generated_answer": answer, "raw_output_preview": raw[:500], "scoring": scoring}

# 10 Real-World Benchmark Scenarios
RESUMPTION_SCENARIOS = [
    {
        "id": "scen_1_resume_mbrain_current_pass",
        "class": "resume_completeness",
        "title": "Resume the current Mbrain pass and identify unfinished work",
        "query": "Mbrain current pass audit unfinished work retrieval verification next action",
        "project": "global-memory",
        "required_keys": ["global-memory.activeContext.md", "pass 8", "retrieval", "verification"],
        "prohibited_keys": [],
        "expected_next_action": "Pass 8",
    },
    {
        "id": "scen_2_why_trust_retired",
        "class": "decision_faithfulness",
        "title": "Explain why global agent trust was retired",
        "query": "Why was global agent trust retired in Mbrain?",
        "project": "global-memory",
        "required_keys": ["trust", "retired", "collapses", "task domain", "evidence quality"],
        "prohibited_keys": [],
        "expected_next_action": None,
    },
    {
        "id": "scen_3_dream_cycle_schedule",
        "class": "current_truth_accuracy",
        "title": "Recover current Dream Cycle schedule and distinguish from stale values",
        "query": "What is the scheduled launchd time for nightly Dream Cycle?",
        "project": "global-memory",
        "required_keys": ["03:10", "dream_cycle"],
        "prohibited_keys": ["02:00"],  # stale Pass 4/5 schedule
        "expected_next_action": None,
    },
    {
        "id": "scen_4_alphaos_collision",
        "class": "contradiction_recall",
        "title": "Identify AlphaOS plugin-version collision without resolving it",
        "query": "alphaos swing plugin version collision",
        "project": "global-memory",
        "required_keys": ["alphaos.swing.plugin.version"],
        "prohibited_keys": [],
        "expected_next_action": "Resolve blocking issue",
    },
    {
        "id": "scen_5_task_resume_bundle",
        "class": "resume_completeness",
        "title": "Resume a task from checkpoint and handoff with files/tests/next action",
        "query": "resume active task checkpoint handoff acceptance criteria",
        "project": "global-memory",
        "required_keys": ["task", "acceptance_criteria", "next_action"],
        "prohibited_keys": [],
        "expected_next_action": "Resume",
    },
    {
        "id": "scen_6_historical_as_of",
        "class": "temporal_accuracy",
        "title": "Answer a historical 'what was true then?' question",
        "query": "What was the active context on 2026-09-08?",
        "project": "global-memory",
        "as_of": "2026-09-08",
        "required_keys": ["2026-09-08"],
        "prohibited_keys": ["2026-09-09"],
        "expected_next_action": None,
    },
    {
        "id": "scen_7_sqlite_wal_procedure",
        "class": "procedure_applicability",
        "title": "Retrieve procedure applicable to SQLite concurrency",
        "query": "What procedures govern SQLite concurrency and WAL mode?",
        "project": "global-memory",
        "required_keys": ["wal", "busy_timeout", "concurrency"],
        "prohibited_keys": [],
        "expected_next_action": None,
    },
    {
        "id": "scen_8_blocking_contradiction_priority",
        "class": "contradiction_recall",
        "title": "Surface blocking contradiction despite lower semantic similarity",
        "query": "plugin version configuration settings",
        "project": "global-memory",
        "required_keys": ["alphaos.swing.plugin.version"],
        "prohibited_keys": [],
        "expected_next_action": None,
    },
    {
        "id": "scen_9_project_isolation",
        "class": "project_isolation",
        "title": "Ignore irrelevant high-similarity memories from another project",
        "query": "current execution engine portfolio options",
        "project": "global-memory",
        "required_keys": ["global-memory"],
        "prohibited_keys": ["robinhood", "alpaca_secret"],
        "expected_next_action": None,
    },
    {
        "id": "scen_10_opaque_status_safety",
        "class": "current_truth_accuracy",
        "title": "Explain why an opaque status cannot be safely acted on",
        "query": "car stickers status actionability",
        "project": "global-memory",
        "required_keys": ["car_stickers_status"],
        "prohibited_keys": [],
        "expected_next_action": None,
    },
]


def run_resumption_evaluation(
    mem_root: Path,
    *,
    enable_indexed_vector: bool = False,
    run_agent_trial: bool = False,
    agent_model: str = DEFAULT_AGENT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
) -> dict[str, Any]:
    root = Path(mem_root)
    scenario_results = []
    class_metrics: dict[str, dict[str, Any]] = {}
    lane_latency_accum: dict[str, list[float]] = {}

    t_start = time.perf_counter()

    for scen in RESUMPTION_SCENARIOS:
        q = scen["query"]
        proj = scen["project"]
        as_of = scen.get("as_of")
        s_class = scen["class"]

        t0 = time.perf_counter()
        retrieval = retrieve(root, q, project=proj, as_of=as_of, token_budget=4000,
                             enable_indexed_vector=enable_indexed_vector)
        t_elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        items = retrieval.get("items", [])
        combined_text = " ".join([f"{it.get('key', '')} {it.get('statement', '')}".lower() for it in items])

        # Record lane latencies
        for l_name, l_lat in retrieval.get("lane_latencies_ms", {}).items():
            lane_latency_accum.setdefault(l_name, []).append(l_lat)

        # Check required tokens/keys
        req_hits = [k for k in scen["required_keys"] if k.lower() in combined_text]
        req_acc = len(req_hits) / max(1, len(scen["required_keys"]))

        # Check prohibited tokens (e.g. stale values or cross-project leaks)
        proh_leaks = [k for k in scen["prohibited_keys"] if k.lower() in combined_text]
        proh_free = len(proh_leaks) == 0

        # A live task is a prerequisite for evaluating task resumption. Its
        # absence is data readiness, not a retrieval failure or a fabricated
        # success.
        not_evaluable_reason = None
        if scen["id"] == "scen_5_task_resume_bundle":
            task_candidates = retrieval.get("manifest", {}).get("lane_candidates", {}).get("tasks", 0)
            if task_candidates == 0:
                not_evaluable_reason = "No active project task, checkpoint, or handoff exists to resume."

        scen_passed = not not_evaluable_reason and (req_acc == 1.0) and proh_free

        scen_res = {
            "scenario_id": scen["id"],
            "class": s_class,
            "title": scen["title"],
            "passed": scen_passed,
            "status": "not_evaluable" if not_evaluable_reason else ("passed" if scen_passed else "failed"),
            "not_evaluable_reason": not_evaluable_reason,
            "latency_ms": t_elapsed_ms,
            "items_retrieved": len(items),
            "required_keys_hit": f"{len(req_hits)}/{len(scen['required_keys'])}",
            "prohibited_leaks": proh_leaks,
            "lanes_used": retrieval.get("manifest", {}).get("lanes_used", []),
        }
        scenario_results.append(scen_res)

        # Accumulate by class
        if s_class not in class_metrics:
            class_metrics[s_class] = {"total": 0, "passed": 0, "req_hit_ratio": []}
        if not not_evaluable_reason:
            class_metrics[s_class]["total"] += 1
            if scen_passed:
                class_metrics[s_class]["passed"] += 1
            class_metrics[s_class]["req_hit_ratio"].append(req_acc)

    total_eval_time = round(time.perf_counter() - t_start, 2)

    # Class-level scores
    class_summary = {}
    for c_name, c_data in class_metrics.items():
        pass_rate = round(c_data["passed"] / max(1, c_data["total"]), 3)
        avg_hit = round(sum(c_data["req_hit_ratio"]) / max(1, len(c_data["req_hit_ratio"])), 3)
        class_summary[c_name] = {
            "scenarios_count": c_data["total"],
            "pass_rate": pass_rate,
            "average_key_accuracy": avg_hit,
        }

    # Lane average latencies
    avg_lane_latencies = {
        l: round(sum(lats) / max(1, len(lats)), 2)
        for l, lats in lane_latency_accum.items()
    }

    # Bundle validation is not an agent continuation trial. Preserve the
    # evidence without claiming a downstream model succeeded.
    bundle = build_resume_bundle(root, "global-memory", target_format="antigravity")
    bundle_contract_valid = (
        bundle.get("next_action") is not None
        and bool(bundle.get("prompt"))
        and "Goal" in bundle.get("prompt", "")
        and bundle.get("dispatch_prohibited") is True
    )

    evaluable = [s for s in scenario_results if s["status"] != "not_evaluable"]
    passed = [s for s in evaluable if s["passed"]]
    not_evaluable = [s for s in scenario_results if s["status"] == "not_evaluable"]

    continuation_trial = (
        _run_live_agent_continuation(bundle, model=agent_model, base_url=ollama_url)
        if run_agent_trial else {
            "project_id": "global-memory",
            "model": agent_model,
            "passed": False,
            "status": "not_run",
            "reason": "No fresh agent/model answer was generated and scored; bundle validation alone is insufficient.",
            "bundle_contract_valid": bundle_contract_valid,
            "next_action": bundle.get("next_action", {}).get("statement"),
            "token_estimate": len(bundle.get("prompt", "")) // 4,
            "dispatch_prohibited": bundle.get("dispatch_prohibited"),
        }
    )
    continuation_trial.setdefault("bundle_contract_valid", bundle_contract_valid)
    continuation_trial.setdefault("dispatch_prohibited", bundle.get("dispatch_prohibited"))

    return {
        "schema_version": "gms-resumption-eval-report-v1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_scenarios": len(RESUMPTION_SCENARIOS),
        "evaluable_scenarios": len(evaluable),
        "not_evaluable_scenarios": len(not_evaluable),
        "scenarios_passed": len(passed),
        "overall_pass_rate": round(len(passed) / max(1, len(evaluable)), 3),
        "total_eval_time_seconds": total_eval_time,
        "class_metrics": class_summary,
        "average_lane_latencies_ms": avg_lane_latencies,
        "agent_continuation_trial": continuation_trial,
        "scenario_results": scenario_results,
        # The gate requires both perfect evaluated performance and complete
        # coverage; missing live task evidence keeps it closed.
        "quality_gate_passed": (
            len(passed) == len(evaluable)
            and not not_evaluable
            and continuation_trial.get("passed") is True
        ),
        "indexed_vector_requested": enable_indexed_vector,
        "agent_trial_requested": run_agent_trial,
    }
