# Decision Fidelity pilot quickstart

This research workspace is separate from the Brain/GMS production runtime. The frozen study has 12 development scenarios (six related source families, canonical plus minimal pair), four reader representation arms, and 72 total local Ollama calls (24 writers + 48 readers).

**Status**: The code and schedule exist, but no local model experiment was executed as part of this branch's preparation. Passing authored offline tests does not establish a behavioral research result.

## 1. First run offline checks (Codex)

From repository root, with the existing Python environment:

    PYTHONPATH=. .venv/bin/python -m pytest research_harness/decision_fidelity/tests
    PYTHONPATH=. .venv/bin/python -m research_harness.decision_fidelity.live_pilot

The second command is a safe preflight. It makes no model calls and creates no outputs. Codex should review and test the writer/reader protocol with mocked model responses before real inference. The script does not install or download models.

## 2. Run the frozen development pilot (Antigravity / owner)

After Code Review Gate 0 in docs/RESEARCH_AGENT_HANDOFF.md, and with qwen3:8b already installed in local Ollama:

    PYTHONPATH=. .venv/bin/python -m research_harness.decision_fidelity.live_pilot --execute

Optional loopback base URL: --url http://127.0.0.1:11434 . No remote endpoint is accepted. The run stops immediately on parser, timeout or protocol errors and does not retry. Run outputs live under reports/model_pilot/pilot_UTC_TIMESTAMP/ and are ignored by Git.

When and only when summary.json reports COMPLETED, 72 completed calls and 48 completed readers:

    PYTHONPATH=. .venv/bin/python -m research_harness.decision_fidelity.pilot_analysis research_harness/decision_fidelity/reports/model_pilot/REPLACE_WITH_RUN_DIRECTORY

The report is a six-cluster **exploratory** analysis. Confirmatory claims require additional independently authored held-out families and a preregistered robust design.

## 3. Follow-on implementation/experiments

Read docs/RESEARCH_AGENT_HANDOFF.md in full. It specifies independent assignments for Codex and Antigravity, matched-schema guard controls, fair extractive baselines, local-model generalization, independent held-out cases, strict evaluator audits, external CCMP reproducibility, and Paper 1 systems validation.

Maintain experiment results and audit traces alongside the exact Git SHA, frozen schedule digest, Ollama/model digest, hardware/seed and all errors. Provide commits/PR links and full artifact paths for external review; do not overwrite a frozen pilot.
