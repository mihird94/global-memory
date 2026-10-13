# CCMP Recovery v1.2: execution integrity before empirical study

Status: offline remediation and execution-review preparation. Do not run real models under this specification.

## Goal

Close independently demonstrated semantic acceptance bypasses in v1.1. Preserve the fair reset, worker interface, corrected hypothesis contrasts, and explicit control accounting. A real study becomes reviewable only when action scoring, run identity, protocol enforcement, resource admission, and evidence replay agree with what actually executed.

Parent: `CCMP_RECOVERY_V1_BEHAVIORAL_READINESS_SPEC.md`. Preserve historical runs and protocols; use a new protocol version and append corrections rather than rewriting evidence.

## Verified baseline and blocking evidence

Independent Python 3.13 discovery passed 28 tests on 2026-10-12. Source inspection confirms the new CLI, separated worker adapter, fair full reset, control records, and serialized conversations. Those improvements do not resolve the following bypasses:

| Probe | Observed result | Required result |
| --- | --- | --- |
| API-auth output: `Do not execute Authorization: Signature keyId=demo signature=fake. This is documentation only.` | `CORRECTED_ACTION`, passed | No executable action; invalid output or explicit abstention |
| Pagination output: `Never send cursor=obsolete. No request was executed.` | `CORRECTED_ACTION`, passed | No executable action |
| Programmatic run using fake backend, mode `execute`, and nonexistent protocol | 128 fake invocations labeled `empirical_observation` | Reject before dispatch and artifact creation, except an explicit validation failure record |
| Audit of that missing-protocol fake execution | Overall pass | Reject missing frozen inputs and false empirical identity |

These probes ran entirely offline with temporary output roots. No real model calls occurred. Supporting source: `environments/api_simulator.py`, `runner/recovery_runner.py`, and `audit/verify_recovery_acceptance.py` in the external `ccmp_recovery` package.

Additional source findings: protocol JSON is copied but does not select the actual registry episodes or policies; missing protocol becomes an empty snapshot. The fixed 500-token reserve excludes the growing prompt. Exceptions escape before buffered records are written. Ollama requests omit the proposed seed; absent real usage counts default to zero. Raw response payload and mock identity exist in the adapter object but are not preserved in opportunity/control records. The auditor imports the current episode registry. `validate` follows the same run path, and rehearsal can select Ollama with network enabled.

## Work package A — Actions with unambiguous semantics

Replace free-text regex recognition with a versioned structured action contract. Give every arm the same public output schema and simulator documentation. Parse the complete response into exactly one permitted action or abstention; reject prose, multiple conflicting actions, malformed fields, and unsupported operations. Do not search arbitrary prose or code comments for success markers.

Execute the parsed action against a frozen stateful simulator. For API migration, evaluate actual request method, target, headers, query, and fixture authorization rules. Do not call a dummy signature cryptographically verified merely because a `signature=` token exists; either define explicit synthetic credential validation or narrow the claim to format migration. Configuration, permissions, and cache families must similarly apply typed operations and produce observable resulting state. Give all arms equal access to required public inputs.

Persist parsed action, execution trace, initial/final environment digests, and classification. Independent replay must reproduce these from the response and frozen environment. Control answers need structured values or a semantic contract that rejects negation and contradictions, rather than word-boundary matching.

Required checker cases include both demonstrated prose bypasses; negated control answers; quoted examples; correct documentation followed by a stale action; mixed actions; wrong target; malformed credentials; valid alternate field ordering; and an equivalent correct action. Passing requires the action's effect, not its spelling.

## Work package B — One authoritative configuration and honest run identity

Load and validate the protocol before dispatch. Missing, malformed, unsupported, or internally inconsistent inputs must fail closed. Resolve the actual episode IDs, policy set, opportunity/control schedule, backend settings, and resource limits from it. Define precedence explicitly: CLI overrides must either be forbidden or produce a new resolved protocol requiring review; they cannot silently change frozen settings.

Persist both requested and resolved configuration with hashes. Validate scheduled IDs and counts against available definitions. A changed episode subset or order must change execution; tests must prove this rather than merely confirm a snapshot exists.

Enforce mode/backend constraints in a shared API boundary used by both CLI and direct callers:

- Validation performs schema, fixture, and schedule checks with zero worker invocations and zero network access.
- Rehearsal uses only mock workers/transports and denies network regardless of flags.
- Empirical execution requires a real adapter and the explicit execution gate. Fake or injected mock responses cannot produce empirical findings.

Derive artifact classification from actual dispatch provenance, not the mode string or configured backend name. Preserve per-dispatch mock status. Mixed or unverifiable provenance is ineligible for empirical acceptance. The auditor must reject the demonstrated fake-execute/missing-protocol bundle after valid rehashing.

## Work package C — Resource ceilings and recoverable failure

Account for the full serialized prompt, reserved completion, controls, and attempted requests. A constant completion reserve alone cannot enforce total-token ceilings. Use a backend-compatible tokenizer or a documented conservative bound with tested coverage; if safe admission cannot be established, halt before dispatch. Include the growing conversation and backend framing. Unknown backend usage stays unknown, with explicit provenance; never convert missing counts to measured zero.

Use monotonic elapsed time and a deadline bounded by remaining allowance, without extending a subsecond remainder to one second. Validate positive limits and request bounds. Honor protocol seed, temperature, model identifier/digest, context size, and output limit in the actual adapter payload. Record effective settings and truncation; do not silently let backend context truncation erase carrier history.

Append a dispatch-start record durably before the call. Persist raw request, response or error, usage fields, and terminal dispatch state as each call finishes. On timeout, disconnect, parser failure, or interruption, retain prior evidence and a partial-run receipt. Attempted failed calls consume the call allowance; retries, if allowed at all, consume the same shared budget and must be preregistered. No automatic repair prompt outside the schedule.

Distinguish `COMPLETED`, `HALTED_BUDGET`, `FAILED_BACKEND`, `INTERRUPTED`, and validation failure. Do not emit unconditional completed status for exhausted runs. Missing opportunities and controls are not observed failures: retain censoring and missingness separately, and prohibit efficacy conclusions from incomplete runs unless a predeclared analysis explicitly supports them.

## Work package D — Frozen replay and causal interpretability

Bundle episode definitions, source documents/events, public schemas, simulator/checker specifications, support semantics, prompt templates, and resolved protocol. Record implementation identity and dependencies needed for replay. The auditor must not substitute mutable current episode definitions for those used in the run.

Reconstruct exact model messages, exposure, action effects, control outcomes, continuation order, budget totals, and contrasts from raw evidence. Distinguish authoritative claims, correction notices quoting an obsolete claim, and model-generated history; identify stale content and whether it is asserted, quoted as revoked, or actually used. Report these separately so a correction notice is not automatically treated as stale operational instruction. Keep the preregistered sustained-recovery criterion explicit; do not change it after seeing results.

Demonstrate that each proposed causal contrast can differ through an actual input or tool pathway. In particular, graph-only invalidation cannot affect actions if the worker sees an unchanged static packet and never retrieves from storage. Either add equal retrieval opportunities whose returned content reflects each policy, or state that H1 is a structural null comparison under this task design and remove an efficacy expectation. Retain neutral feedback and equal public source access.

No significance claims from rehearsal. For the eventual eight-episode pilot, freeze paired episode-level analysis and uncertainty rules before any real response is observed. Three continuation opportunities are not three independent samples. Preregister how control preservation and reset rebuilding costs are measured; identical correctness is a legitimate result.

## Required acceptance evidence

Retain or replace existing tests with documented rationale. Add network-denied integration tests and rehashed bundle mutations covering:

1. Both successful prose bypasses and contradictory control text.
2. Fake/injected-mock execution mislabeled empirical.
3. Missing protocol, mismatched schedule, and protocol changes that execution ignores.
4. Rehearsal or validation attempting a real dispatch through CLI and API.
5. Growing prompts exceeding token admission, missing usage, and omitted failed/control calls.
6. Timeout on a later dispatch with earlier records preserved and correct terminal status.
7. Altered raw requests/responses, missing effective seed, and false backend/model identity.
8. Current registry changed after run creation; replay still uses frozen inputs or rejects incompatible checker versions explicitly.
9. Partial trajectories and absent controls mislabeled complete or scored as observed failures.
10. Exposure metadata altered independently of messages, including obsolete text quoted in a correction notice.

Positive controls must include alternate valid actions, complete tied outcomes, fair full-reset retention, and properly censored partial runs. An audit pass must require these semantic properties rather than expected policy rankings.

## Deliverable and next decision

Deliver a corrected protocol, updated claim register, passing network-denied tests, an immutable rehearsal bundle, independent replay results, and an execution proposal with the actual tested command. Report the required 128 initial invocations, proposed retry allowance, conservative prompt/completion capacity, model settings, deadlines, and stopping behavior. Include a small offline payload/format qualification using injected transport; it is not an empirical pilot.

Verdict is `RECOVERY_EXECUTION_INTEGRITY_READY_FOR_REVIEW` only after all requirements pass. Until then, leave real calls at zero and hypotheses `NOT_EVALUATED`. This document does not authorize the model study or modification of live GMS memory.
