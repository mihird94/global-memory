# Optional memory research workspace

This workspace contains experimental CCP promotion/contest mechanisms, authored benchmark adapters, retrieval tuning experiments, research specifications, tests, and historical evidence. It is separate from the production memory runtime in `tools/` and `desktop/`.

Production GMS does not import this package. Research may call product retrieval code as a system under test; product code must never import research code. No experiment is installed into the CLI, MCP server, Dream Cycle, or deployment services. Operational retrieval, model-harvesting checks, and task-resumption diagnostics remain product features.

## Run separately

From the repository root, create a dedicated research environment and install the product's required runtime dependencies plus the optional dependencies listed in `eval/requirements.txt`. No installer or model download runs automatically. Existing development environments can also run these commands:

```bash
# Product regression suite (default pytest excludes research)
.venv/bin/python -m pytest

# Research regression suite, explicitly selected
PYTHONPATH=.:tools .venv/bin/python -m pytest research_harness/tests

# Fixture-only benchmark adapters; results are not official benchmark scores
PYTHONPATH=.:tools .venv/bin/python -m research_harness.eval.cli run --no-export

# Synthetic CCP robustness study
PYTHONPATH=.:tools .venv/bin/python -m research_harness.ccp.robustness_report --help
```

Research outputs belong in `research_harness/reports/`; benchmark exports default there. CCP output paths are explicit CLI arguments. The research CLI has no live-memory mode. Never point experiments at `~/memories`; use synthetic fixtures or explicitly prepared disposable test roots. These are code-level boundaries, not an operating-system sandbox for arbitrary Python.

## Layout and migration

- `ccp/`: previously `research/ccp/`; import namespace is `research_harness.ccp`.
- `eval/`: previously top-level `eval/`; import namespace is `research_harness.eval`.
- `tests/`: independent research tests, previously mixed into `tests/`.
- `docs/`: CCMP specifications and research briefs.
- `reports/`: historical evaluation runs and independent CCMP audit artifacts, preserved without rewriting their recorded paths or results.

`brain eval-lab` now returns migration instructions without importing or running experiments. Run the explicit research CLI instead. `research/` in the product repository is a literature archive only. External CCMP packages under `projects/learning/agent_memory/_research/` remain separate and are not copied into production GMS.

This is an optional workspace in the same Git repository, not a new Git repository. Pushes/deployments still require their own instruction; runtime services have no dependency on this workspace and can run with it absent.
