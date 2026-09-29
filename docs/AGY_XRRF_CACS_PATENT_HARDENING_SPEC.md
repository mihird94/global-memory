# Antigravity Execution Spec: XRRF and CACS Patent Hardening

**Owner:** Mihir Deshpande
**Executor:** Google Antigravity (`agy`)
**Date:** 2026-09-21
**Status:** Ready for execution
**Source workspace:** `/Users/mihirdeshpande/projects/learning/agent_memory/_research/`

## 1. Mission

Convert the current XRRF and CACS research artifacts into an evidence-grounded patent-counsel package. Do not file, publish, contact counsel, or make public disclosures. Produce corrected technical disclosures, reproducible experiments, claim-to-evidence matrices, and a prior-art differentiation package.

The work must distinguish:

1. implemented and reproduced facts;
2. simulated results;
3. hypotheses requiring experiments;
4. proposed claim language;
5. legal conclusions reserved for patent counsel.

This is a technical and evidentiary hardening project, not legal advice.

## 2. Current artifacts

Primary inputs:

- `_research/IDF_01_XRRF_FEDERATED_MEMORY.md`
- `_research/IDF_02_CACS_AUTONOMOUS_CONSENSUS.md`
- `_research/DEEP_DIVE_XRRF_AND_CACS.md`
- `_research/EMPIRICAL_VERIFICATION_REPORT.md`
- `_research/01_xrrf_federated_memory/`
- `_research/03_cacs_unsupervised_consensus/`
- `_research/data/hard_xrrf_eval_set.json`
- `_research/data/hard_cacs_eval_set.json`
- `_research/ablation_results/`
- `_research/mac_conf/`
- `_research/papers/`

Preserve existing files. Put all new work under:

```text
_research/patent_hardening/
  README.md
  evidence/
  experiments/
  prior_art/
  claims/
  reports/
  corrected_idfs/
```

Do not overwrite the original IDFs or benchmark outputs.

## 3. Non-negotiable evidence policy

- Never describe simulated nodes as physical devices.
- Never call a metric independent if it is computed from a definition that makes the result true by construction.
- Never use `proves`, `eliminates`, `perfect`, `zero leakage`, `production`, `ready to file`, or `breakthrough` unless a cited artifact directly supports the exact scope.
- Every quantitative claim must link to a command, input-data hash, code hash, raw output, environment record, and aggregation script.
- Record random seeds and report mean, standard deviation, confidence interval, minimum, and maximum when randomness exists.
- Separate algorithm-only latency from transport, serialization, storage, and end-to-end latency.
- Mark unpublished legal opinions as `Counsel review required`.
- Do not manufacture organization adoption, commercial value, production use, patent-committee approval, or EB-1 evidence.
- Do not include real secrets, credentials, personal contact data, medical data, or financial identifiers in public-facing datasets.

## 4. Baseline facts to reproduce first

Before changing code, reproduce and save the following current results.

### 4.1 XRRF baseline

Expected on the checked-in 50-query simulated dataset:

| Method | Expected Recall@1 |
|---|---:|
| Calibrated XRRF | 78% (39/50) |
| Uncalibrated RRF | 50% (25/50) |
| CombSUM | 78% (39/50) |
| Borda | 50% (25/50) |

Also verify:

- all tested `k` values from 1 to 200 currently produce 78%;
- all tested candidate depths from 1 to 10 currently produce 78%;
- synonym/paraphrase Recall@1 is 50%;
- metadata at `L=5` is approximately 130.12 bytes/query.

Interpretation constraint: the existing benchmark shows that coverage calibration improves this dataset, but does not establish that RRF, `k=40..60`, or cutoff depth creates the improvement.

### 4.2 CACS baseline

Expected current synthetic results:

| Sybil ratio | Unanchored EM | Anchored CACS |
|---:|---:|---:|
| 40% | ~1.67% | ~98.67% |
| 50% | ~0.67% | ~99.0% |
| 60% | ~0.67% | ~99.0% |
| 70% | ~0.67% | ~99.67% |

Expected current 50-item hard-set result:

- majority vote: 0%;
- unanchored EM: 0%;
- anchored CACS: 100%;
- algorithm-only runtime: approximately 0.65 ms.

Interpretation constraint: the designated `sandbox_runner` currently supplies the correct answer for every hard-set claim while the solver fixes the anchor confusion matrix at 98% diagonal accuracy. This benchmark does not demonstrate autonomous truth discovery without a near-oracle.

## 5. Workstream A: reproducibility and provenance

### A1. Freeze the baseline

Create a machine-readable manifest containing:

- SHA-256 for all IDFs, papers, code, datasets, mocks, and reports;
- creation and modification timestamps;
- Python, NumPy, SQLite, OS, and hardware versions;
- exact reproduction commands;
- stdout/stderr captures;
- seeds;
- elapsed wall time and algorithm-only time.

### A2. Build a single read-only reproduction command

Add a command that runs both baselines without mutating canonical reports:

```bash
python -m patent_hardening.reproduce --output <new-run-directory>
```

Every run directory must be immutable-by-convention and named with UTC timestamp plus the code-manifest hash.

### A3. Add tests

Tests must verify:

- result schemas;
- deterministic seeded reproduction;
- no source artifact overwrite;
- hash correctness;
- raw-output retention;
- metric calculations;
- redaction of sensitive corpus values.

## 6. Workstream B: XRRF technical hardening

### B1. Correct the terminology and privacy model

Replace `Privacy Leakage Index = 0.00` with at least four explicit metrics:

1. **Non-Winning Content Exposure Ratio** — bytes of non-winning document content transmitted divided by winning content bytes.
2. **Metadata Transfer Ratio** — metadata bytes divided by winning content bytes.
3. **Identifier Linkability** — ability to correlate the same item across repeated queries.
4. **Access-Pattern Inference Accuracy** — adversary accuracy when predicting document/domain presence from rank metadata.

Document the adversaries:

- honest-but-curious coordinator;
- malicious coordinator;
- compromised child node;
- passive network observer;
- colluding nodes.

### B2. Implement protocol features needed for a narrow systems claim

Implement behind feature flags:

- rotating opaque result identifiers or scoped capability tokens;
- authenticated requests and responses;
- replay protection;
- fetch authorization limited to the selected object;
- coordinator timeout and partial quorum;
- duplicate-identifier and multi-host ownership handling;
- explicit abstention when evidence is insufficient;
- structured protocol telemetry separating query, rank metadata, fetch request, and content bytes.

Do not claim cryptographic privacy unless the threat-model tests support it.

### B3. Decouple the fusion signals

Evaluate at minimum:

- RRF only;
- coverage only / CombSUM;
- weighted RRF;
- calibrated RRF;
- normalized score fusion where comparable;
- learned fusion trained only on a training split;
- oracle upper bound.

Prevent tie-breaking artifacts by specifying deterministic tie rules and reporting tied-score frequency.

### B4. Build a credible evaluation

Minimum evaluation design:

- 10,000 or more sanitized documents;
- 500 or more queries;
- independently authored query set;
- train/dev/test separation for any tuned parameter;
- exact, paraphrase, synonym, negation, temporal, collision, and multi-hop categories;
- at least five random seeds where sampling is used;
- sparse, dense, and graph-capable local retrievers;
- fleet sizes 2, 4, 8, 16, and 32;
- packet loss, node timeout, stale index, duplicate item, and malicious-node cases;
- measured network/serialization/storage latency, not only fusion-loop time.

Report Recall@1/3/5, MRR, NDCG@10, abstention accuracy, p50/p95/p99 latency, total bytes, metadata bytes, and privacy-attack results.

### B5. Required XRRF falsification tests

Try to disprove the proposed invention:

- If CombSUM continues to match XRRF, do not claim an RRF-specific advantage.
- If `k` has no effect, remove the `40 <= k <= 60` claim.
- If `L=1` matches deeper cutoffs, do not claim a cutoff Pareto frontier.
- If identifiers remain linkable, do not claim zero metadata leakage.
- If centralized retrieval wins at equivalent privacy/compute cost, document it.

## 7. Workstream C: CACS technical hardening

### C1. Separate attestation from correctness

Model independently:

- identity authenticity;
- code/runtime integrity;
- input freshness;
- evidence provenance;
- task-specific historical correctness;
- current claim correctness.

An attested execution must not automatically receive a fixed 98% correctness assumption.

### C2. Add critical baselines

Compare CACS against:

- majority vote;
- directly trust the anchor;
- weighted majority using known anchor accuracy;
- unanchored Dawid–Skene;
- MAP Dawid–Skene;
- gold-claim-seeded Dawid–Skene;
- a source-dependency-aware truth-discovery baseline;
- an adversarial-crowdsourcing baseline;
- abstain unless independently verified.

The essential question is whether CACS beats simply accepting the trusted verifier's answer.

### C3. Required sensitivity grid

Run a factorial evaluation over:

- anchor accuracy: 50%, 60%, 70%, 80%, 90%, 95%, 99%, 100%;
- anchor coverage: 0%, 10%, 25%, 50%, 75%, 100%;
- anchor count: 0, 1, 2, 3, 5;
- anchor correlation: independent, shared upstream source, identical implementation;
- compromised anchors: 0 through all anchors;
- Sybil ratio: 0% through 90%;
- observation sparsity: 0% through 90%;
- claim count: 25, 50, 100, 200, 500, 1,000;
- class cardinality: 2, 3, 5, 10;
- distribution shift and changing agent quality.

Report accuracy, macro-F1, Brier score, expected calibration error, false-promotion rate, false-rejection rate, abstention rate, convergence failures, and latency.

### C4. Implement safe promotion semantics

Prototype a provenance-aware claim lifecycle:

```text
proposed -> supported | conflicted | insufficient
supported -> promoted
promoted -> superseded | contested | revoked
```

Each transition must retain:

- source assertions;
- evidence references;
- solver/version manifest;
- rationale;
- posterior and calibration metadata;
- actor;
- event and observation time;
- prior value;
- rollback path.

Fail closed when anchor provenance is missing, stale, correlated, or disputed.

### C5. Required CACS falsification tests

- Deliberately corrupt the anchor.
- Give the anchor partial coverage.
- Make independent anchors disagree.
- Create correlated honest-agent failures.
- Create Sybils that adapt to golden probes.
- Shift claim domains after estimating agent quality.
- Compare against `trust anchor directly`.
- Test whether the posterior is calibrated, not only accurate.

Do not use `eliminates label inversion` unless the statement is explicitly bounded to tested conditions.

## 8. Workstream D: prior-art and claim differentiation

This is a technical search, not a freedom-to-operate opinion or patentability opinion.

### D1. Seed references

At minimum analyze:

- US7984039B2 — merging results in distributed information retrieval;
- US9996589B2 — holistic federated ranking;
- US11366814B2 — federated search with independently ranked endpoints;
- US8190546B2 — dependency-aware truth discovery;
- US20200327582A1 — Dawid–Skene in crowdsourced task-result determination;
- Dawid and Skene (1979);
- Kleindessner and Awasthi (2018), *Crowdsourcing with Arbitrary Adversaries*;
- Traganitis and Giannakis (2021), *Detecting Adversaries in Crowdsourcing*;
- established federated-search and rank-fusion literature.

Search backward citations, forward citations, patent families, continuations, and non-patent literature. Record search queries and search date.

### D2. Produce element charts

For each proposed independent claim, create:

| Claim element | Implemented artifact | Experimental evidence | Closest reference | Difference | Technical effect | Risk |
|---|---|---|---|---|---|---|

Risk values: `anticipated`, `likely obvious combination`, `uncertain`, or `potentially differentiating`. Do not state `novel` or `patentable`; reserve that judgment for counsel.

### D3. Claim strategy

Prepare three claim scopes for counsel:

- **Broad:** conceptual system boundary, clearly marked high risk.
- **Medium:** concrete protocol or ledger mechanics.
- **Narrow:** fully implemented combination whose claimed technical effect is directly reproduced.

Preferred XRRF center:

> Heterogeneous constrained nodes returning privacy-budgeted rank metadata under scoped unlinkable identifiers, followed by quorum-bounded fusion and cryptographically limited single-object fetch.

Preferred CACS center, only if implemented:

> Evidence- and attestation-scoped claim promotion with dynamic anchor reliability, correlation controls, calibrated abstention, and reversible bi-temporal state transitions.

Do not center claims on RRF or anchored Dawid–Skene alone.

## 9. Workstream E: corrected counsel package

Create, without overwriting originals:

1. `corrected_idfs/IDF_01_XRRF_COUNSEL_DRAFT.md`
2. `corrected_idfs/IDF_02_CACS_COUNSEL_DRAFT.md`
3. `reports/TECHNICAL_EVIDENCE_REPORT.md`
4. `reports/KNOWN_LIMITATIONS_AND_NEGATIVE_RESULTS.md`
5. `prior_art/XRRF_ELEMENT_CHART.md`
6. `prior_art/CACS_ELEMENT_CHART.md`
7. `claims/XRRF_CLAIM_CONCEPTS.md`
8. `claims/CACS_CLAIM_CONCEPTS.md`
9. `evidence/INVENTION_TIMELINE_TEMPLATE.md`
10. `evidence/INVENTORSHIP_QUESTIONNAIRE.md`
11. `evidence/ARTIFACT_MANIFEST.json`
12. `reports/COUNSEL_EXECUTIVE_BRIEF.md`

The IDFs must:

- use the actual date, not `Q1 2026`;
- keep assignee and inventorship explicitly unresolved unless owner-provided evidence resolves them;
- say `simulated` wherever applicable;
- distinguish current evidence from proposed future embodiments;
- include negative results;
- cite artifact hashes;
- avoid EB-1 advocacy and invented corporate-adoption claims.

## 10. Acceptance gates

The project is complete only when all gates pass.

### Evidence gates

- Every reported number is reproducible from a saved run.
- Every run has code, data, environment, command, seed, and hash provenance.
- Negative and null results are retained.
- No sensitive data appears in distributable datasets or reports.

### XRRF gates

- The contribution of rank, confidence, cutoff, and fetch policy is separately identified.
- Privacy claims cover metadata and linkability, not only content bytes.
- At least one real networked multi-process or multi-device prototype run exists, or all claims remain explicitly simulation-only.
- No claim depends on `k=40..60` unless a held-out evaluation demonstrates the effect.

### CACS gates

- The hard benchmark no longer assumes an always-correct, full-coverage anchor without labeling that condition.
- Anchor accuracy, coverage, correlation, and compromise are evaluated.
- CACS is compared with direct anchor acceptance.
- False-promotion and calibration results accompany accuracy.
- Promotion fails closed under insufficient or disputed evidence.

### Counsel-package gates

- Claim-to-evidence and claim-to-prior-art charts exist.
- Broad claims are clearly labeled high risk.
- Technical effect is described as a concrete system improvement.
- No document claims legal patentability or filing readiness.

## 11. Execution order

Execute in this order:

1. inventory and hash artifacts;
2. reproduce baseline without code changes;
3. issue a discrepancy register;
4. implement test and experiment infrastructure;
5. harden XRRF and run its evaluation;
6. harden CACS and run its evaluation;
7. conduct prior-art differentiation;
8. draft corrected IDFs and claim concepts;
9. run an independent evidence audit;
10. produce the counsel executive brief.

Stop and report rather than guessing if:

- assignee or inventor identity is unclear;
- an original artifact would need to be overwritten;
- a claimed result cannot be reproduced;
- secrets or personal data are discovered;
- external publication or filing would be required;
- a legal conclusion is necessary.

## 12. Required final response from Antigravity

Return:

1. concise verdict for XRRF and CACS;
2. exact files created or changed;
3. commands executed;
4. test and experiment results;
5. unsupported claims removed or narrowed;
6. strongest remaining differentiators;
7. unresolved prior-art and evidence risks;
8. counsel decisions required;
9. the single highest-value next action.

Do not report completion if any acceptance gate remains unmet. Report the remaining gate and the evidence needed to close it.

## 13. Copy/paste Antigravity prompt

```text
Open and execute the specification at:
/Users/mihirdeshpande/projects/global-memory/docs/AGY_XRRF_CACS_PATENT_HARDENING_SPEC.md

The source research workspace is:
/Users/mihirdeshpande/projects/learning/agent_memory/_research/

Follow the execution order and evidence policy exactly. Preserve every original artifact and place new outputs only under `_research/patent_hardening/`. Begin by reproducing the untouched baselines and issuing a discrepancy register. Do not publish, file, contact counsel, invent organizational adoption claims, or make legal conclusions. Do not call the task complete until every acceptance gate is satisfied; otherwise return the unmet gates and the evidence required.
```
