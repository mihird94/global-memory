# Common-Cause-Aware Contestable Promotion (CCP) — Phase 0 Research Harness

Hermetic, local-first experimental testbed for evaluating multi-tier memory gating, causal provenance independence, and contestable projections across collaborative scopes.

## Architecture

### 1. Collaborative Scopes
```text
private → task → project → team → organization
```

### 2. Append-Only Temporal Validity
All projection validity transitions are recorded in `ccp_projection_validity_events`:
- **Creation** emits an `activate` event with `effective_at` governing semantic validity.
- **Contest** emits `invalidate` events for the contested projection and all active descendants in the derivation DAG atomically.
- Existing projection records in `ccp_scope_projections` are **never updated** (`UPDATE` is forbidden).
- Active status is derived exclusively from the ordered event stream at query time (`as_of`).

### 3. Causal Provenance & Common-Cause Awareness
Rather than relying on agent-trust scores or Sybil-vulnerable claim counts, promotion decisions evaluate causal provenance DAGs:
- One authoritative verified source qualifies alone.
- Multiple claims sharing the same underlying origin root count as a single evidentiary lineage.
- LLM inference echoes and source laundering are rejected for collaborative scopes.
- Metamorphic invariants guarantee that agent renaming, evidence reordering, or redundant echoes do not perturb decisions.

### 4. Disclosure Transforms
- `share_verbatim`: clean verified statements projected directly.
- `share_redacted`: sensitive secrets or local filesystem paths replaced with canonical placeholders.
- `share_aggregate`: operational details abstracted into high-level lessons/rules.

## Evaluation & Benchmark Reporting

To run the reproducible synthetic seeded robustness evaluation:

```bash
PYTHONPATH=.:tools .venv/bin/python -m research_harness.ccp.robustness_report
```

The emitted JSON report captures complete environment provenance (`git_commit`, `policy_version`, `python_version`), per-seed baseline metrics across fixed pseudo-random seeds (`42, 123, 999`), and aggregate summary intervals (mean, min, max).

## Scientific & Research Limitations

1. **Synthetic Scenarios, Not Real Traces**: The evaluation scenarios are synthetically generated for robustness and adversarial testing. They do not represent real multi-agent team conversational traces.
2. **Rule-Based Adjudication, Not Empirical Human Model**: Ground-truth labels and promotion gates are rule-based specifications, not an empirical model of human consensus.
3. **In-Memory SQLite, Not Distributed Consensus**: The current harness operates on in-memory SQLite and does not model network partitions, Byzantine consensus, or distributed clocks.
4. **Simulated Scope Boundaries**: Scope tiers represent semantic filtering boundaries within the memory engine, not cryptographically enforced access control boundaries.
5. **No Novelty or Patentability Claims**: This harness is an internal research prototype designed to explore agent memory mechanics safely.
