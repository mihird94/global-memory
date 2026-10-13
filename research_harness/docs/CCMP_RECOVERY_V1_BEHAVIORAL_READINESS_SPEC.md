# CCMP Recovery v1.1: behavioral study readiness

Status: offline implementation specification. No real model executions authorized by this document.

## Objective

Make correction-propagation recovery measurable without encoding the expected policy ranking in the worker, checker, or baseline. Preserve the structural harness, then produce a reviewable execution proposal.

Parent: `CCMP_CORRECTION_PROPAGATION_RECOVERY_STUDY_SPEC.md`. This specification supersedes conflicting implementation choices in `ccmp_recovery/protocol/recovery_protocol_v1.json`; preserve that protocol and its evidence as historical artifacts.

## Independently verified starting point

On 2026-10-12, all 21 existing recovery tests passed under Python 3.13. That establishes the current harness's tested behavior, not behavioral efficacy.

Source inspection found these readiness defects:

1. `runner/fake_worker.py` chooses stale versus corrected answers from `policy_arm` and reads hidden task witnesses. Its latency and token counts are constants. Rehearsal outcomes are constructed fixtures.
2. `policies/full_reset.py` rebuilds from V2 alone, dropping unchanged authoritative control sources. This violates the parent specification and forces collateral loss.
3. `evaluator/contrasts.py` labels positive aggregate differences as supported. It implements no statistical test supporting the pasted report's `p < .001` claims, and its H1 comparison combines graph invalidation with context refresh.
4. `runner/recovery_runner.py` exposes a rehearsal method, instantiates the fake worker directly, and has no module CLI entry point implementing the proposed local-model command.
5. The runner records `opp.prompt` as `prompt_sent` without serializing the packet and plan passed separately to the fake worker. Three opportunities reuse the same carrier without recording a continuing model conversation or action-derived state.
6. The 96 opportunity invocations exclude 32 control invocations from call and token accounting. Time and token ceilings are not checked before every opportunity.
7. The checker delegates to pattern witnesses; control success is substring presence. These do not establish execution of a corrected action.

## Required work

### 1. Honest rehearsal and claims

Mark every existing rehearsal result `synthetic_structural_fixture`; empirical hypotheses must be `NOT_EVALUATED`. Retain original evidence and append a correction register explaining the unsupported significance claims and forced baseline loss. Do not silently rewrite historical evidence.

Split scripted fault injection from the worker interface. Scripts may deliberately emit wrong actions to exercise auditing, but cannot count as policy efficacy observations. A context-driven fake worker must receive only the same public task and serialized context as a real worker: no policy label, expected answer, hidden witness, or checker object. Policy metadata stays in the orchestrator.

### 2. Fair correction policies

All arms receive the identical source-change event and access to identical current authoritative sources under the same budget.

| Arm | Treatment |
| --- | --- |
| Append-only | Append the correction notice while preserving old carriers. |
| Graph invalidation | Invalidate unsupported graph descendants; retain existing carriers. |
| Graph plus refresh | Apply graph invalidation and rebuild or validate carriers against the current source frontier. |
| Full reset | Clear derived memory and rebuild from V2 **and all unchanged authorized sources**. |

If a destructive wipe-only arm is useful, label it a separate diagnostic. It cannot substitute for full reset or establish selective-preservation superiority. Support alternatives must survive when independently sufficient; conjunctive dependencies must fail when a required input is revoked. Specify these semantics in fixtures and replay tests.

### 3. Executable action evidence

Each episode needs a hermetic action environment: an API simulator, permission evaluator, configuration consumer, or cache-generation validator. Workers emit a structured action or executable artifact; independent checking executes it against frozen environment state.

Record stale action, corrected action, abstention, invalid output, and execution error separately. Merely mentioning the V2 pattern is insufficient. Include reference corrected actions and counterexamples: quoted correction followed by a stale action, both versions in prose, fabricated success text, malformed action, and valid alternate implementation. Checkers must accept semantically valid alternatives.

Keep hidden assertions and reference solutions out of model inputs. Public source documentation is identical across arms.

### 4. Explicit continuation and exposure

Choose and preregister one estimand: repeated independent opportunities from frozen carriers, or a genuine continuing trajectory. Do not call the former longitudinal recovery. For continuing trajectories, define how each response/action updates conversation, plans, caches, and state before the next opportunity; freeze the feedback policy and prohibit hidden checker feedback.

Persist the exact ordered messages and tool results sent to the backend, packet content, cached plans, truncation decisions, source frontier, and state transitions for every opportunity. Derive stale exposure from actual serialized content and provenance, not a producer Boolean or node list alone. Preserve the rule of two consecutive correct opportunities without stale exposure for sustained recovery; incomplete trajectories are censored, never silently counted as failures or successes.

### 5. A working, protocol-driven runner

Implement and document actual CLI entry points for validation, network-disabled rehearsal, and separately gated real execution. Unknown flags and unsupported backends must fail nonzero. The selected protocol must control corpus, policy set, schedule, backend, prompt construction, continuation semantics, and limits; write resolved configuration and input hashes into evidence.

Implement the real adapter behind dependency injection and test it using a captured-request fake transport. The offline readiness workflow must deny network access and prove zero real calls. Record raw requests/responses, backend/model identity, settings, timing, usage provenance, errors, and retries. Report unavailable usage as unknown, not fabricated constants.

Enforce call, elapsed-time, and token limits before every dispatch, including controls and retries. Reserve completion allowance, set per-request timeouts bounded by remaining time, and stop when the remaining budget cannot safely admit a request. Record cancellation and partial completion. A 96-opportunity schedule plus separate controls requires 128 initial invocations, before retries; alternatively include controls in each structured response and preregister that design. Submit a revised budget proposal rather than silently exceeding the parent budget.

### 6. Analysis that matches the question

H1 compares graph invalidation with append-only; H2 compares graph plus refresh with graph invalidation. H3 compares selective refresh with fair full reset on control preservation and rebuilding cost, with corrected-task performance reported alongside it. Do not assume full reset loses controls.

Use the episode as the paired unit; three opportunities are correlated observations, not three independent replications. With eight authored episodes, report paired differences, per-episode trajectories, uncertainty appropriate to the small sample, and family-level limitations. Predeclare estimands, interval/test procedure if used, multiplicity handling, and support thresholds before observing real outcomes. No inferential claims from deterministic rehearsal. Zero differences and inconclusive findings are valid outcomes.

### 7. Independent evidence audit

Snapshot protocol, episodes, environment/checker definitions, sources, and implementation identifiers in the run bundle. Audit from those frozen inputs rather than mutable current registries. Reconstruct schedule, exposure, action effects, controls, budgets, trajectories, and contrasts from raw records. Integrity hashes alone do not establish semantic validity or an external signature.

Extend rehashed mutation tests to reject hidden-answer leakage, policy-conditioned worker outputs, unfair reset source deletion, an unsent packet recorded as exposure, forged control outcomes, omitted control costs, over-budget retries, mismatched protocol/corpus, duplicated opportunity IDs, invented significance, and altered continuation state. Include positive controls for alternate valid actions, surviving independent support, censored trajectories, and tied policy performance.

## Acceptance and handoff

Deliver updated code, frozen v1.1 protocol, claim-correction register, executable witnesses, network-denied rehearsal, independently reconstructed audit, and mutation results. Existing 21 tests must continue passing or have documented replacements where their assertions encode invalid assumptions. Add tests for the defects above; test count itself is not a readiness gate.

Readiness verdict may be `RECOVERY_BEHAVIORAL_READY_FOR_EXECUTION_REVIEW` only when all requirements pass. The handoff must include the actual tested command, exact model/backend, request count including controls/retries, token/time budget, stopping rules, and expected evidence paths. Leave efficacy hypotheses unevaluated and real executions at zero. A subsequent execution decision is required before running the model study.
