# CCMP — Correction Propagation and Behavioral Recovery

Date: 2026-10-12 (America/Los_Angeles)
Status: next scientific study; offline preparation only
Target: separate `ccmp_recovery/` package beside `ccmp_behavioral/` under `/Users/mihirdeshpande/projects/learning/agent_memory/_research`

## Research question

After a source is corrected or revoked, does its influence disappear from agent actions, or survive through derived summaries, cached context, and unfinished plans?

Measure the distinction between **storage invalidation** and **behavioral recovery**. A graph reporting zero active descendants is a systems property; an agent taking the corrected action is a behavioral outcome. Neither substitutes for the other.

This study is independent of whether procedural memory increases coding success. No novelty, general safety, production readiness, or patent claims are authorized. Preserve null and adverse results.

## Prerequisites and boundaries

Reuse the verified evidence, frozen input, checker, protocol-driven scheduling, budget, and missingness contracts in `CCMP_BEHAVIORAL_V3_EXECUTION_READINESS_SPEC.md`. Complete those shared infrastructure requirements before real recovery experiments. The prior efficacy study need not show positive benefit; its measurement infrastructure must be trustworthy.

Implement a hermetic injected store and sandbox. Do not use private live GMS data, mutate `~/memories`, deploy services, download models, commit, or use a paid API. Existing evidence remains unchanged. Real execution is a separate decision against the concrete schedule and budget produced here; this handoff authorizes offline development and validation only.

## Hypotheses and outcomes

- **H1 — Propagation:** lineage-aware invalidation reduces post-correction wrong actions relative to appending a correction note alone.
- **H2 — Recovery beyond storage:** validating cached packets/plans against source versions reduces persistent wrong actions relative to invalidating the durable graph alone.
- **H3 — Specificity:** dependency-aware correction preserves independently supported useful memories better than deleting an entire context/store.

Primary outcome: proportion of post-correction opportunities where the executed artifact/action violates the corrected authoritative contract. Report successful corrected actions, abstentions, wrong old-rule actions, other errors, and infrastructure failures separately.

Secondary outcomes: steps/time to sustained recovery, stale exposure count, invalidation completeness, useful-memory retention, collateral task failures, source-checking overhead, prompt/tool tokens, and latency. Avoid a composite trust/health score.

Freeze hypotheses, contrasts, task families, source-change schedule, acceptance criteria, analysis, and ceilings before real execution. This first study is exploratory; provide uncertainty and independent family counts without inventing power guarantees.

## Episode design

Each episode has two legitimate source versions, a known change event, a derivation graph, and independent executable action checks:

1. **Acquire:** agent receives or retrieves authoritative version V1 and performs a task where V1 is correct.
2. **Derive:** create a summary/procedure/plan with traceable source ancestry. Record whether each derivative is worker-generated or a fixture; never present authored fixtures as emergent agent behavior.
3. **Change:** inject authoritative V2 or revoke the source at a frozen step. Verify event delivery to the store and the arm-specific correction path.
4. **Continue:** offer three bounded action opportunities where V2 applies. Observe actual retrieved context, plan contents, artifacts, and executable outcomes.

Illustrative synthetic families: API version migration, configuration key retirement, cache generation change, and permission/scope revocation. For each, V1 must be correct before the change and wrong after it; V2 must be accessible identically through authoritative sources in every arm. Never conceal the new requirement solely in one arm's memory.

Include distractors, a safe unchanged control task, a derivative supported by an independent source, and a competing stale paraphrase. Keep same-source copies distinct from independent corroboration. Freeze reference artifacts and correct/incorrect action witnesses for each phase.

Use meaningful applicability: revoke only the affected claim/scope/time. A temporal update must preserve valid historical answers. A total source revocation and a correction to one field are different interventions; report separately.

## Four policies

| Arm | Memory correction mechanism |
|---|---|
| Append-only | Append the authoritative correction; old records/derivatives remain retrievable with their recorded history |
| Graph invalidation | Invalidate corrected claims and affected descendants in durable storage; existing materialized packets/plans remain unchanged |
| Graph plus context refresh | Same graph changes; validate packet/plan source-version dependencies before each new action and refresh or explicitly block stale context |
| Full reset | Clear the episode's agent memory/context and rebuild from authoritative V2 plus unchanged sources |

Every arm receives the same source-change event and access to V2; only correction handling differs. Freeze retrieval/context budgets. Allow safe abstention, but report it separately so “no wrong actions” cannot disguise failure to complete tasks. Full reset is a collateral-loss baseline, not an oracle.

For derivatives with multiple supports, predeclare the dependency rule: conjunctive supports require all prerequisites; independently sufficient alternatives permit retention only when surviving evidence is independently checked. Blindly invalidating every descendant is not automatically optimal.

## Controlled and behavioral tracks

**Structural track:** deterministic fixture graphs and packet caches test propagation contracts, scope/time filters, and preservation of unrelated evidence. No LLM claims or behavioral metrics.

**Controlled behavioral track:** start from a frozen pre-correction artifact/context snapshot so every arm faces the same established stale belief. If the snapshot is authored, label that explicitly. This isolates recovery mechanisms; it does not demonstrate spontaneous memory poisoning or error formation.

**Natural acquisition extension:** let a worker generate derivatives before correction, then branch the retained snapshot into all arms. Record provenance and initial acquisition success. Report results both over all attempts and among episodes with verified V1 acquisition; do not silently exclude acquisition failures. This extension requires its own proposed budget and is not part of the initial execution ceiling.

Model state is limited to the inspectable context and artifact carrier. Do not claim to remove a belief from model weights. Preserve carried plans deliberately; prevent accidental cross-arm shared mutable state.

## Event, state, and exposure evidence

Retain append-only source events with source ID/version, effective validity, observed time, actor, authority, and affected scope. Store complete pre/post graph and materialized context snapshots, source dependency versions, emitted invalidation events, candidate eligibility, actual exposure IDs/content, exact prompts/responses, worker artifacts, and checker outputs.

Before each action, record the source-version frontier observed by the controller and worker. Distinguish correction delivery delay from failure to respect a delivered correction. An exposure violation and a wrong action are separately measurable.

Storage invalidation must be atomic within the supported local store and fail closed on partial updates. Use injected fault points and control subgraphs. Do not claim distributed transaction guarantees or true concurrent safety unless implemented and independently exercised.

## Recovery and retention definitions

An action is stale only if it follows the superseded rule when V2 is applicable. Judge using executable artifact effects and source contracts, not whether a forbidden string appears in prose.

Define sustained recovery as two consecutive successful corrected actions without stale exposure at the relevant action boundary. The three-opportunity window is bounded: unresolved recovery is right-censored, never assigned zero latency. Report immediate correctness and full trajectories as well; the sustained criterion must not erase early wrong actions.

Measure unrelated task success and retained independently justified memories after correction. Full reset may recover correctness but incur extra retrieval and collateral loss. Qualify graph correctness separately from utility preservation.

## Preparation and proposed execution budget

Offline phase: build four source families with two episodes each; validate reference and near-miss implementations; run structural fault and frozen-context tests; emit the full schedule with network/model calls disabled.

Proposed first behavioral ceiling: **8 episodes × 4 policies × 3 post-correction opportunities = 96 worker calls**, using frozen pre-correction carriers and an already authorized local backend. Include correction/context processing costs. All real smoke calls and retries count against the ceiling. Proposed additional ceilings: 60 minutes end-to-end and 100000 total model tokens, with per-call capacity justified by reference-solution size.

The 96-call proposal is not an execution authorization. Before dispatch, deliver protocol hashes, task/checker snapshots, selected backend/configuration, actual capacity limits, exact CLI command, and enforced budget behavior. Do not inherit or renew previously consumed model-call allowances. If prompt budget cannot accommodate a frozen carrier, resolve the design offline rather than silently truncate it.

## Independent verification

The auditor reconstructs source versions, graph closure, dependency rules, packet freshness, actual exposure, action outcomes, trajectories, retention, and reported estimates from frozen evidence. It must not treat producer flags as proof. Verify complete schedule and distinguish unattempted budget-skipped opportunities from failed actions. Report incomplete trajectories without claiming sustained recovery.

Mutation regressions: forged successful correction with an active stale descendant; stale content in a refreshed packet; altered source effective time; revoked item retrievable by direct ID; destroyed unrelated control; ignored alternative support; false action checker result; missing continuation; altered recovery latency; and entire policy removal with adjusted summaries. Rehash each malicious package and require semantic rejection plus an unmodified positive control.

Analyze paired policies on the same episode/carrier/opportunity and cluster by actual source family. With only four families, treat estimates as exploratory and expose per-family trajectories; do not interpret repetitions as independent clusters. Define the primary contrasts H1/H2/H3 and missingness handling prospectively. Distinguish unsupported from not-evaluated findings.

## Deliverables and stop

Deliver the hermetic recovery package, reference/counterexample corpus, structural and behavioral carrier schemas, protocol-driven runner, independent auditor, semantic mutation tests, frozen exploratory protocol, offline rehearsal, and a reviewable real execution proposal.

Return `INFRASTRUCTURE_PREREQUISITES`, `SOURCE_CHANGE_AND_DEPENDENCY_CONTRACT`, `CARRIER_PROVENANCE`, `REFERENCE_CHECKS`, `STRUCTURAL_FAULT_RESULTS`, `OFFLINE_SCHEDULE`, `AUDIT_MUTATIONS`, `PROPOSED_BACKEND_AND_BUDGET`, and `LIMITATIONS` with evidence paths.

Stop after offline preparation. No real model calls, natural-acquisition extension, efficacy/interaction expansion, live GMS integration, deployment, or commits under this specification.
