# Research Brief — Contestable Shared Memory Gating

## Context

GMS/Mbrain is a private, local-first personal memory system and a controlled research testbed for multi-agent memory and context engineering. The objective is to turn useful mechanisms into falsifiable research artifacts; it is not to claim novelty, patentability, or ownership without separate prior-art, disclosure, and counsel review.

Never place employer-confidential, proprietary, customer, or non-public work details in this repository or in research artifacts generated from this brief.

## Research portfolio

### A. Contestable Adaptive Gating for Shared Memory (CAG)

**Problem.** A fact useful to one person or agent is not automatically safe or useful for a team. Existing memory stores often expose a binary write/share choice with limited recourse.

**Hypothesis.** A promotion policy that separately models expected downstream reuse, evidence quality, scope/authority, sensitivity, and reversibility can outperform always-share, never-share, recency-only, and similarity-only baselines on useful shared recall while reducing inappropriate disclosure and future correction cost.

**Actions.** `retain_private`, `share_verbatim`, `share_redacted`, `share_aggregate`, `request_corroboration`, `reject`.

**Required properties.** Every decision carries evidence references, rationale, intended scope/TTL, an owner contest path, and a reversible prior state. This is not an agent-trust score.

### B. Counterfactual Context Value (CCV)

**Problem.** Salience at write time is a poor proxy for usefulness to a future agent.

**Hypothesis.** Estimate a memory's value from the difference it makes to a future bounded task: success, clarification turns, unsafe-action avoidance, and token cost when the item is present versus withheld. Use that signal only as one gated input, never as unreviewed truth.

**Experiment.** Freeze task traces, make counterfactual context packets, measure task outcome, abstention correctness, time-to-correct-action, and privacy/disclosure cost. Compare against recency, embedding similarity, manual importance, and an oracle label where feasible.

### C. Provenance-Preserving Shareable Memory Capsules (PSMC)

**Problem.** Team summaries often sever a claim from its authority, source scope, uncertainty, and revocation conditions.

**Hypothesis.** A compact capsule containing claim, evidence digest, authority/scope, effective time, disclosure tier, and revocation/contest pointer retains more safe decision utility per token than a free-text summary.

**Experiment.** Compare free-text summaries, extracted facts, and capsules for source verification success, stale-action rate, handoff fidelity, token use, and correction propagation after a source changes.

### D. Independent-Evidence Promotion for Contamination Resistance (IEPCR)

**Problem.** A false or overgeneralized memory can spread across agents through copying, extraction, and repeated retrieval without genuinely independent support.

**Hypothesis.** Promote a candidate only when its support satisfies an evidence-lineage diversity rule (rather than counting repeated agent mentions) and keep single-lineage material private, qualified, or pending corroboration.

**Experiment.** Inject copied, paraphrased, stale, and contradictory evidence into a multi-agent simulation; measure false-promotion rate, useful-recall loss, correction latency, and attack success under Sybil-like repetition.

### E. Scope-Gradient Memory (SGM)

**Problem.** Memory is not just private versus team-wide. Useful sharing often needs progressive disclosure: private, task, project, team, organization.

**Hypothesis.** A policy that chooses the minimum sufficient disclosure scope, with automatic expiration and upgrade only after evidence/use thresholds, has lower disclosure regret at equivalent task utility than a fixed team store.

**Experiment.** Construct tasks where evidence is useful at one scope but harmful or irrelevant at wider scopes; measure correct-scope precision, downstream utility, revocation effectiveness, and operator contest burden.

## Shared evaluation contract

- Separate retrieval accuracy, actionability, privacy/disclosure violations, stale leakage, correction/revocation propagation, contest burden, latency, token cost, and operator understanding. Do not collapse these into one trust score.
- Use synthetic data only for contract/security tests; supplement it with consented, non-sensitive, independently labeled scenarios before drawing substantive conclusions.
- Preserve temporal splits and ensure no source lineage crosses train/test boundaries.
- Pre-register baselines, thresholds, and negative results. Record why a memory was gated, not merely its outcome.
- Treat all patent/prior-art discussion as a research-risk checklist, not legal advice or a conclusion of novelty.

## Antigravity task

Select the top two directions for the next GMS experiment. For each, return a mechanism diagram, explicit state/action model, falsifiable hypotheses, baselines, consent-safe dataset design, evaluation matrix, ablations, anticipated failure modes, prior-art overlap categories, and a minimum viable prototype that fits GMS's local-first architecture. Rank the portfolio by research value, feasibility, and distinctiveness, while clearly separating direct evidence from inference.
