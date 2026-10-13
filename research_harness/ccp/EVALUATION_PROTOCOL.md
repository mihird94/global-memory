# Common-Cause-Aware Contestable Promotion (CCP) — Evaluation Protocol Specification

**Document Version:** 1.0.0
**Status:** Research Specification
**Scope:** `research/ccp/` Experimental Testbed

---

## 1. Executive Summary & Epistemic Framing

The Common-Cause-Aware Contestable Promotion (CCP) framework is an experimental research harness designed to investigate safe memory promotion mechanisms across hierarchical collaboration scopes (`private → task → project → team → organization`).

To maintain scientific integrity and prevent false empirical confidence:
1. **Research Boundary:** CCP Phase 0 is strictly a hermetic research harness. It is **not** integrated into production Global Memory System (GMS), live vector retrieval, agent tool execution, or persistent user memory.
2. **Epistemic Honesty:** All metrics generated within Phase 0 are strictly characterized as **synthetic seeded robustness evaluation**, never as held-out empirical validation.
3. **No Legal or Patentability Claims:** This specification does not claim novel patentability or legal finality; it establishes formal experimental controls for verifiable multi-agent memory research.

---

## 2. Three-Tier Evaluation Framework

To eliminate metric ambiguity and methodological confounding, CCP defines three distinct tiers of evaluation:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Tier 1: Calibration (Development Fixtures)                             │
│ - Single-scenario unit tests & fixed fixtures                          │
│ - Internal logic verification & edge-case proofs                       │
│ - Permitted Claim: "Harness functions correctly on unit test cases"    │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Tier 2: Synthetic Seeded Robustness                                    │
│ - Multi-seed stochastic perturbations (seeds: 42, 123, 999)            │
│ - Metamorphic transformations, parrot attacks, laundering injection     │
│ - Output: Standardized JSON Report with deterministic identity hash    │
│ - Permitted Claim: "Synthetic seeded robustness evaluation"            │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Tier 3: Independent Held-Out Evaluation (Future Protocol)              │
│ - Frozen external datasets authored by independent researchers         │
│ - Pre-registered hypothesis & zero policy tuning post-freeze           │
│ - Blinded multi-annotator adjudication (Cohen's Kappa ≥ 0.80)          │
│ - Permitted Claim: "Held-out empirical validation"                     │
└────────────────────────────────────────────────────────────────────────┘
```

### Tier 1: Calibration (Development Fixtures)
- **Objective:** Verify schema constraints, SQLite triggers, causal graph traversal algorithms, and cycle prevention.
- **Corpus:** Static scenario definitions in `research/ccp/corpus.py`.
- **Reporting Rule:** Quoting calibration metrics as benchmark performance is strictly forbidden.

### Tier 2: Synthetic Seeded Robustness
- **Objective:** Quantify policy behavior under systematic perturbations, common-cause rumor propagation, and adversarial source laundering.
- **Harness:** `research/ccp/seeded_synthetic_robustness.py` and `research/ccp/robustness_report.py`.
- **Experimental Protocol:**
  - Evaluated across fixed seeds (default: `42`, `123`, `999`) with 26 balanced scenario variants per seed.
  - Generates a cryptographically anchored `report_identity_hash` covering code provenance, test suite provenance, runtime version, seeds, and aggregate metrics.
  - Baselines tested:
    - `B0_AlwaysShare`: Naive sharing baseline.
    - `B1_StaticRegexDLP`: Pattern-only redaction baseline.
    - `B2_DistinctAgentCount`: Count-based agent consensus (vulnerable to Sybil/parrot attacks).
    - `B3_CCPGate`: Full causal-provenance contestable promotion gate.
- **Reporting Invariant:** Quoted numbers must directly match the output of `python -m research_harness.ccp.robustness_report`.

### Tier 3: Independent Held-Out Evaluation (Future Protocol)
- **Objective:** Genuinely test generalizability across unseen real-world multi-agent collaboration traces.
- **Pre-Registration Requirements:**
  1. **Disjoint Authoring:** Scenarios and ground-truth labels must be authored by individuals who have not contributed to CCP heuristic rules.
  2. **Cryptographic Freezing:** The dataset file must be serialized according to `research/ccp/fixtures/independent_eval_schema.json` and its SHA-256 digest recorded before running any evaluation.
  3. **Blinded Adjudication:** Ground truth must be adjudicated by at least 2 independent raters with inter-rater agreement (Cohen's Kappa) $\ge 0.80$.
  4. **Zero-Tuning Policy:** Policy rules in `research/ccp/engine.py` must not be altered after dataset unblinding.

---

## 3. Mathematical Metric Formulations

All metrics must report both explicit counts (numerators and denominators) and normalized rates to eliminate reporting opacity.

### 3.1 Classification Metrics
Let $TP$, $FP$, $TN$, $FN$ denote true positives, false positives, true negatives, and false negatives for safe wider-scope promotion:

$$\text{Precision} = \frac{TP}{TP + FP}$$

$$\text{Recall} = \frac{TP}{TP + FN}$$

$$\text{False Promotion Rate (FPR)} = \frac{FP}{FP + TN}$$

$$\text{False Rejection Rate (FRR)} = \frac{FN}{FN + TP}$$

### 3.2 Security and Safety Rates

$$\text{Privacy Violation Rate} = \frac{\sum \text{Unredacted Secrets in Shared Projections}}{\text{Total Shared Projections}}$$

$$\text{Source Laundering Success Rate} = \frac{\sum \text{Laundered Rumors Promoted to Team/Org}}{\text{Total Laundered Candidates Evaluated}}$$

$$\text{Echo Parrot Attack Success Rate} = \frac{\sum \text{Parroted Hallucinations Promoted}}{\text{Total Parroted Candidates Evaluated}}$$

$$\text{Stale Leakage Rate} = \frac{\sum \text{Expired Candidates Promoted}}{\text{Total Expired Candidates Evaluated}}$$

$$\text{Transitive Invalidation Completeness} = \frac{\sum \text{Invalidated Active Descendants}}{\text{Total Active Descendants at Contest Time}}$$

### 3.3 Bootstrap Confidence Intervals
For sample metrics, empirical non-parametric bootstrap confidence intervals (default: $B = 1000$ iterations, $95\%$ interval) are calculated:

$$\theta^*_b = \frac{1}{N} \sum_{i=1}^N x^*_{b,i}, \quad b = 1, \dots, B$$

$$\text{CI}_{95\%} = \left[ \theta^*_{\lfloor 0.025 B \rfloor}, \; \theta^*_{\lceil 0.975 B \rceil} \right]$$

---

## 4. Scope Monotonicity & Privacy Non-Interference Contract

### 4.1 Scope Monotonicity
Promotion is strictly upward:
$$\text{private} < \text{task} < \text{project} < \text{team} < \text{organization}$$

- Candidates with $\text{target\_scope} \le \text{source\_scope}$ must fail closed as `reject_promotion`.
- Child derivations must satisfy $\text{target\_scope}_{\text{child}} \ge \text{target\_scope}_{\text{parent}}$.
- Derivations cannot form cycles; self-loops and directed loops are rejected at insertion time.

### 4.2 Privacy Non-Interference
Information projected to collaborative scopes must preserve zero-leakage across all eight channels:
1. `ccp_scope_projections.projected_statement`
2. `ccp_scope_projections.metadata_json`
3. `ccp_promotion_receipts.deterministic_rationale`
4. `ccp_promotion_receipts.evidence_roots_json`
5. `ccp_projection_validity_events.rationale`
6. `ccp_contest_events.rationale`
7. `ccp_reversal_events` audit metadata
8. `ccp_promotion_receipts.evidence_graph_digest`

Any presence of synthetic tokens matching `SECRET_REGEX` or `LOCAL_PATH_REGEX` in collaborative tiers constitutes a critical safety failure.

---

## 5. Threats to Validity & Disclosures

1. **Template Reliance:** Synthetic scenarios represent stylized operational patterns, not natural human conversational dialogue.
2. **Scope Simulation:** Scopes are model abstractions enforced via database records, not hardware-enforced or cryptographic enclaves.
3. **Deterministic Heuristics:** Current policy uses deterministic structural rules rather than probabilistic neural adjudication.
