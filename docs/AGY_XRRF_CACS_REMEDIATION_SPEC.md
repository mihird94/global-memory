# Antigravity Remediation Spec: XRRF and CACS Patent Hardening

**Owner:** Mihir Deshpande
**Executor:** Google Antigravity (`agy`)
**Date:** 2026-09-21
**Status:** Mandatory remediation
**Supersedes completion claim:** 2026-09-21 Antigravity Technical Audit & Hardening Completion Report
**Source workspace:** `/Users/mihirdeshpande/projects/learning/agent_memory/_research/`
**Prior specification:** `/Users/mihirdeshpande/projects/global-memory/docs/AGY_XRRF_CACS_PATENT_HARDENING_SPEC.md`

## 1. Objective

Repair the invalid or unsupported portions of the XRRF/CACS patent-hardening package. The previous execution reproduced the original baselines correctly but did not satisfy the hardened-experiment, privacy, CACS robustness, prior-art, or counsel-package acceptance gates.

Do not file, publish, contact counsel, or present the current package as counsel-ready. Preserve every existing artifact. Put remediation work under:

```text
_research/patent_hardening/remediation/
  evidence/
  experiments/
  prior_art/
  reports/
  corrected_idfs/
  tests/
```

Do not overwrite the original research or first-pass hardening artifacts.

## 2. Mandatory status correction

Before any new experimentation:

1. Create `remediation/reports/INVALIDATED_CLAIMS_REGISTER.md`.
2. Mark the following documents as superseded by independent audit in the register:
   - `reports/COUNSEL_EXECUTIVE_BRIEF.md`
   - `reports/TECHNICAL_EVIDENCE_REPORT.md`
   - `corrected_idfs/IDF_01_XRRF_COUNSEL_DRAFT.md`
   - `corrected_idfs/IDF_02_CACS_COUNSEL_DRAFT.md`
   - `prior_art/SEED_PRIOR_ART_SEARCH.md`
   - the prior `all acceptance gates passed` conclusion.
3. Do not edit those documents in place. Generate replacement versions only under `remediation/`.

The invalidated-claims register must include the original statement, defect, affected artifacts, required repair, and replacement evidence reference.

## 3. Verified defects that must be repaired

### 3.1 XRRF relevance evaluation is invalid

The scaled campaign currently counts any nonempty retrieval as a hit:

```python
if res["content"] is not None and not res["abstain"]:
    hits += 1
```

It does not compare the retrieved item to `target_uuid`. The reported scaled `100% recall` is invalid.

The generated query text and randomly assigned target UUID are also not semantically grounded. A query cannot be considered labeled merely because it contains a `target_uuid` field.

### 3.2 XRRF privacy metrics are unsupported or misreported

- `access_pattern_inference_accuracy` is hard-coded to `0.28`; no attacker produces it.
- `metadata_transfer_ratio` is calculated as metadata bytes divided by winning-content bytes. A value of `22.12` means metadata is 22.12 times the winning content, not a 22.12x reduction.
- identifier linkability only compares token-set overlap across artificial epochs and ignores within-epoch reuse, rank patterns, query text, node identity, timing, and traffic volume.
- the implemented opaque token is used as the bearer fetch handle; there is no separately issued coordinator authorization ticket with audience, expiry, nonce, object, and replay semantics.

### 3.3 CACS robustness is overstated

The prior 25%-coverage/100%-accuracy result is a single seeded synthetic case. Independent 20-seed testing with 25% anchor coverage and 95% anchor accuracy found:

| Sybil agents / 10 | Mean CACS accuracy | Worst observed seed |
|---:|---:|---:|
| 2 | 95.54% | 94.0% |
| 3 | 97.22% | 95.8% |
| 4 | 98.14% | 97.2% |
| 5 | 94.19% | 3.4% |
| 6 | 1.39% | 0.8% |

The method is conditionally useful, unstable near the inversion boundary, and fails when partial anchor evidence is overwhelmed.

### 3.4 CACS system mechanisms are incomplete

- attestation is modeled as Boolean fields, not cryptographically verified evidence;
- the lifecycle accepts arbitrary transitions instead of enforcing a transition graph;
- the lifecycle is not bi-temporal;
- anchor reliability is supplied as an input rather than estimated and calibrated from independent evidence;
- the previous 27-cell grid omitted most dimensions required by the original specification.

### 3.5 Prior-art records contain factual errors

At minimum correct:

- US7984039B2: IBM, not Microsoft;
- US11366814B2: Elsevier, not Cisco;
- US8190546B2: original assignee AT&T, current assignee Google, not University of Illinois;
- US20200327582A1: original assignee Yandex Europe AG, not Appen.

Verify every bibliographic field against the patent record and save source URLs plus access dates.

## 4. Workstream A: remediation provenance

### A1. Freeze both generations

Create SHA-256 manifests for:

1. original `_research/` patent artifacts;
2. first-pass `_research/patent_hardening/` artifacts;
3. remediation artifacts.

Record code, dataset, command, seed, environment, raw output, and report-generator hashes for every new quantitative claim.

### A2. Reproduction package

Add:

```bash
python -m remediation.reproduce_audit_findings --output <run-directory>
```

It must reproduce:

- the invalid XRRF hit-count behavior;
- the hard-coded 0.28 privacy value;
- the metadata-ratio direction;
- the CACS multi-seed instability table;
- the prior-art metadata corrections.

### A3. No self-certification

An implementation function may not decide whether its own acceptance gate passed. Acceptance must be calculated by a separate audit module reading immutable run outputs.

## 5. Workstream B: valid XRRF retrieval evaluation

### B1. Build grounded relevance data

Create a sanitized evaluation dataset with:

- at least 10,000 documents;
- at least 500 test queries;
- deterministic document-to-node placement;
- independently generated query text;
- explicit relevance judgments;
- support for multiple relevant documents;
- no target derived from or selected after observing the retrieval output;
- train/dev/test separation;
- category labels: exact, paraphrase, synonym, collision, negation, temporal, and multi-hop.

Each query record must contain:

```json
{
  "query_id": "...",
  "query": "...",
  "relevant_document_ids": ["..."],
  "category": "...",
  "label_source": "human|rule_fixture|independent_generator",
  "label_rationale": "..."
}
```

Do not use a random UUID as a relevance label.

### B2. Correct metrics

For every method and seed, calculate:

- Recall@1/3/5;
- MRR;
- NDCG@10;
- precision for abstentions;
- abstention rate;
- failure rate;
- p50/p95/p99 algorithm latency;
- p50/p95/p99 end-to-end latency;
- query, metadata, authorization, and content bytes separately.

A hit requires the returned document identifier to belong to `relevant_document_ids`.

### B3. Required baselines

Evaluate:

- local-only oracle routing;
- centralized lexical retrieval;
- centralized dense retrieval;
- RRF only;
- coverage CombSUM;
- calibrated RRF;
- normalized-score fusion;
- weighted RRF;
- learned fusion trained only on the training split;
- random and majority-node baselines.

Report confidence intervals and paired significance tests against the strongest non-oracle baseline.

### B4. Fusion falsification

Explicitly determine whether:

- calibrated RRF beats CombSUM;
- rank contributes after controlling for coverage;
- `k` changes held-out performance;
- cutoff depth changes held-out performance;
- improvements survive new query authors, seeds, and corpora.

If not, remove all RRF-specific performance claims.

## 6. Workstream C: real XRRF privacy and authorization evaluation

### C1. Correct the byte metrics

Report all of:

```text
metadata_bytes_per_query
winning_content_bytes_per_query
non_winning_content_bytes_per_query
total_bytes_per_query
metadata_to_winning_content_ratio
total_to_centralized_transfer_ratio
content_avoided_bytes
```

Never describe a ratio greater than one as a reduction without computing the inverse and clearly naming its denominator.

### C2. Implement actual capability authorization

Use separate objects:

1. opaque result handle returned during ranking;
2. coordinator-issued fetch authorization;
3. node-validated capability ticket.

The capability ticket must bind:

- object handle;
- node/audience;
- query/session identifier;
- issue time and expiry;
- single-use nonce;
- authorization scope;
- protocol version;
- cryptographic authenticator.

Test tampering, wrong node, wrong object, expiry, replay, nonce reuse, cross-session use, and revoked authorization.

Do not label the mechanism cryptographic attestation or authorization if it is only a local dictionary lookup.

### C3. Implement privacy attackers

At minimum implement:

- same-document linkability attacker within an epoch;
- cross-epoch rank-pattern attacker;
- node/domain inference attacker;
- repeated-query intersection attacker;
- passive traffic-volume classifier.

Use held-out attack data and compare against chance, static identifiers, rotating handles, padding, and optional batching. Report ROC-AUC or macro-F1 as appropriate, with confidence intervals.

### C4. Threat-model conclusions

State separately what the protocol protects and does not protect against. A zero token intersection is not proof of unlinkability.

## 7. Workstream D: robust CACS evaluation

### D1. Complete factorial design

Evaluate at least:

- anchor accuracy: 50%, 60%, 70%, 80%, 90%, 95%, 99%, 100%;
- anchor coverage: 0%, 10%, 25%, 50%, 75%, 100%;
- anchor count: 0, 1, 2, 3, 5;
- compromised anchors: 0 through all anchors;
- Sybil ratio: 0% through 90% in 10-point steps;
- observation sparsity: 0%, 20%, 40%, 60%, 80%, 90%;
- claim count: 25, 50, 100, 200, 500, 1,000;
- class count: 2, 3, 5, 10;
- independent versus correlated honest errors;
- independent versus colluding adversaries;
- in-domain versus shifted-domain agent quality.

Use at least 20 seeds per central condition and at least 100 seeds around observed phase transitions.

### D2. Required CACS baselines

Compare with:

- majority vote;
- direct anchor acceptance with abstention;
- direct anchor plus majority fallback;
- weighted majority;
- unanchored Dawid-Skene;
- MAP Dawid-Skene;
- gold-seeded Dawid-Skene;
- source-dependency-aware truth discovery;
- adversarial-crowdsourcing method from a cited paper or faithful reference implementation;
- supervised reliability estimation where labels exist.

Do not label a handcrafted heuristic with the name of a literature method.

### D3. Metrics

Report:

- accuracy and macro-F1;
- Brier score and ECE;
- false-promotion and false-rejection rates;
- abstention and coverage;
- catastrophic-inversion frequency;
- mean, standard deviation, confidence interval, minimum, and maximum;
- convergence failure rate and latency.

Highlight multimodal outcomes. A high mean may not conceal catastrophic seeds.

### D4. Narrow the claim to supported regimes

Determine empirically the boundary where CACS remains stable. Claim language must state tested preconditions such as minimum anchor coverage, anchor accuracy, independent evidence, and maximum adversarial ratio. Do not state that inversion is eliminated globally.

## 8. Workstream E: implement the claimed CACS system

### E1. Attestation verifier

Implement and test verifiable evidence, not Boolean placeholders:

- signed agent identity;
- signed code/runtime measurement;
- timestamp/freshness verification;
- nonce and replay protection;
- evidence binding to the exact claim and observation;
- trust-root configuration and revocation.

If hardware-backed attestation is not implemented, call the result `signed software provenance`, not hardware attestation.

### E2. Dynamic anchor reliability

Estimate anchor reliability from independent held-out probes or evidence rather than accepting a caller-supplied accuracy as truth. Prevent evaluation leakage between reliability estimation and tested claims.

### E3. Enforced lifecycle

Implement an explicit transition table. Reject illegal transitions. At minimum:

```text
proposed -> supported | conflicted | insufficient
supported -> promoted | conflicted | insufficient
promoted -> contested | superseded | revoked
conflicted -> supported | insufficient
insufficient -> supported | conflicted
```

Every transition must be append-only and retain actor, rationale, evidence references, previous value, new value, solver version, and concurrency guard.

### E4. True bi-temporal records

Persist:

- valid time: `valid_from`, `valid_to`;
- transaction time: `recorded_at`, `superseded_at`;
- immutable event identifier;
- causal predecessor;
- rollback/supersession reference.

Add tests for retroactive corrections, late evidence, concurrent promotion, contest, and rollback.

## 9. Workstream F: prior-art remediation

### F1. Correct bibliographic records

Verify title, inventors, original assignee, current assignee, priority date, patent family, legal status, independent claims, and relevant passages for every cited reference.

### F2. Search procedure

Record:

- database;
- exact query;
- date;
- filters/classifications;
- results reviewed;
- inclusion/exclusion rationale;
- backward and forward citations;
- patent-family members;
- non-patent literature.

### F3. Element charts

For every claim element, quote or accurately paraphrase the closest reference with pinpoint claim/paragraph/figure citations. Use:

```text
anticipated
likely obvious combination
uncertain
not found in searched references
```

Do not use `novel`, `defensible`, `patentable`, or `strongest defensibility` as technical-audit conclusions.

## 10. Workstream G: test requirements

The remediation suite must include tests that fail against the first-pass hardening implementation.

### XRRF tests

- wrong-document retrieval is not counted as a hit;
- missing target is a failure or explicit abstention;
- multiple relevant documents are handled correctly;
- access-pattern metric changes when attacker predictions change;
- metadata ratio direction is correct;
- rotating handles remain linkable within an epoch and are measured as such;
- authorization rejects tampering, replay, wrong audience, expiry, and cross-session reuse;
- all fusion metrics recompute from raw ranked outputs.

### CACS tests

- multi-seed catastrophic inversion is detected;
- incomplete anchor coverage is measured separately from accuracy;
- compromised and disagreeing anchors trigger abstention where configured;
- illegal lifecycle transitions fail;
- valid and transaction times behave independently;
- false-promotion rate recomputes from saved predictions;
- calibration metrics recompute from saved posterior vectors;
- no ground truth leaks into solver configuration outside explicit training/probe partitions.

### Prior-art tests

- patent identifiers map to verified titles and assignees;
- all URLs resolve;
- every element chart has a pinpoint source or is marked `not found`.

## 11. Replacement deliverables

Create:

1. `remediation/reports/INVALIDATED_CLAIMS_REGISTER.md`
2. `remediation/evidence/REMEDIATION_MANIFEST.json`
3. `remediation/reports/XRRF_VALID_EVALUATION.md`
4. `remediation/reports/XRRF_PRIVACY_ATTACK_REPORT.md`
5. `remediation/reports/CACS_ROBUSTNESS_REPORT.md`
6. `remediation/reports/CACS_PHASE_BOUNDARY_REPORT.md`
7. `remediation/reports/KNOWN_LIMITATIONS_AND_FAILURES_V2.md`
8. `remediation/prior_art/VERIFIED_PRIOR_ART_SEARCH.md`
9. `remediation/prior_art/XRRF_ELEMENT_CHART_V2.md`
10. `remediation/prior_art/CACS_ELEMENT_CHART_V2.md`
11. `remediation/corrected_idfs/IDF_01_XRRF_COUNSEL_DRAFT_V2.md`
12. `remediation/corrected_idfs/IDF_02_CACS_COUNSEL_DRAFT_V2.md`
13. `remediation/reports/COUNSEL_EXECUTIVE_BRIEF_V2.md`
14. `remediation/reports/INDEPENDENT_GATE_AUDIT.md`
15. runnable test and experiment code plus immutable raw outputs.

## 12. Acceptance gates

### XRRF gates

- No metric counts arbitrary nonempty retrieval as relevant.
- Query relevance labels are inspectable and grounded.
- No privacy metric is hard-coded.
- Metadata byte ratios are correctly named and interpreted.
- Linkability includes within-epoch and side-channel attacks.
- Capability authorization is a distinct validated protocol object.
- Results include uncertainty and strongest-baseline comparisons.

### CACS gates

- At least 20 seeds per central condition and 100 near phase boundaries.
- Catastrophic-inversion frequency is reported.
- Full required factor coverage is present or every omitted factor is an open gate.
- Direct-anchor, anchor-plus-fallback, and faithful literature baselines are present.
- Attestation is implemented evidence or correctly labeled as a simulation.
- Lifecycle transition enforcement and bi-temporal persistence are tested.
- Claims are limited to empirically stable regimes.

### Prior-art gates

- Bibliographic facts are verified.
- Search history and pinpoint references are inspectable.
- No technical report makes a legal patentability conclusion.

### Counsel-package gates

- Every quantitative statement resolves to raw predictions or transport traces.
- Superseded numbers are absent or explicitly identified as invalidated.
- Negative results and boundary conditions appear beside positive results.
- Counsel drafts do not say `proven`, `defensible`, `perfect`, `zero leakage`, or `ready to file`.

## 13. Completion rule

Do not report `all gates passed` based on the implementation's own assertions or on test count alone. Create `INDEPENDENT_GATE_AUDIT.md` that evaluates each gate against immutable evidence.

If any gate is unmet, report:

```text
Status: REMEDIATION INCOMPLETE
Unmet gate:
Evidence missing:
Risk created:
Exact next action:
```

Only the owner or a separate reviewing agent may accept the final gate audit.

## 14. Required final response

Return:

1. defects reproduced;
2. fixes implemented;
3. exact files changed or created;
4. test commands and results;
5. valid XRRF retrieval results;
6. measured privacy-attack results;
7. CACS stable and unstable operating regions;
8. corrected prior-art facts;
9. claims removed or narrowed;
10. unmet gates;
11. the single highest-value next action.

## 15. Copy/paste Antigravity prompt

```text
Open and execute the remediation specification at:
/Users/mihirdeshpande/projects/global-memory/docs/AGY_XRRF_CACS_REMEDIATION_SPEC.md

Source workspace:
/Users/mihirdeshpande/projects/learning/agent_memory/_research/

The previous hardening completion report was independently audited and is not accepted. Preserve all original and first-pass artifacts. Put all new work under `_research/patent_hardening/remediation/`. Begin by reproducing every defect in Section 3 and creating the invalidated-claims register. Do not publish, file, contact counsel, or describe the package as counsel-ready. Do not self-certify acceptance: generate immutable evidence and an independent gate-audit artifact, then report every unmet gate explicitly.
```
