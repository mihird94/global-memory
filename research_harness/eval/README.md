# Brain Memory Evaluation Lab

This package contains **Brain-local evaluation adapters**. It borrows ability
categories from LongMemEval, LoCoMo, and MemoryAgentBench, but it does not bundle or run
official public datasets.

The current deterministic suite contains:

- **LongMemEval adapter**: 12 canonical long-horizon cases plus 48 labeled query robustness variants across 5 core abilities (factual extraction, multi-session reasoning, temporal reasoning, knowledge update, calibrated abstention).
- **LoCoMo adapter**: 12 canonical long conversational memory cases plus 48 labeled variants across 5 categories (single-hop recall, multi-hop reasoning, temporal sequence, open-domain summarization, adversarial abstention).
- **MemoryAgentBench adapter**: 5 canonical lifecycle/robustness cases plus 15 labeled variants (selective forgetting, out-of-order ingestion, contradiction resistance).
- **Context-bundle continuation checks**: 2 context-bundle structure checks that evaluate resume bundle generation.

Use these cases for fast regression feedback. Do not publish their pass rates as
official LongMemEval, LoCoMo, or MemoryAgentBench scores.

## Commands

```bash
PYTHONPATH=.:tools .venv/bin/python -m research_harness.eval.cli run
PYTHONPATH=.:tools .venv/bin/python -m research_harness.eval.cli run --suite locomo
PYTHONPATH=.:tools .venv/bin/python -m research_harness.eval.cli run --suite longmemeval
PYTHONPATH=.:tools .venv/bin/python -m research_harness.eval.cli ablate
```

The ablation runs only genuinely isolated retrieval lanes. Dense retrieval uses
deterministic query embeddings against stored SQLite vectors so it remains
repeatable; graph retrieval uses real fixture triples. The reranked strategy
executes the planner's real, lazy FlashRank ONNX cross-encoder path. Install its
optional runtime with `pip install -r research_harness/eval/requirements.txt`. If a dependency or
cached model is absent, the strategy is reported as unavailable rather than
silently substituted.

Reports generated before `2026-09-13T08:54:22Z` predate strict lane isolation
and must not be used for method comparisons. The latest report with
`official_public_benchmark: false` and per-strategy `available` fields is the
authoritative local baseline.
