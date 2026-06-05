You are working in:
- /home/mihir/projects/global-memory

Task:
Implement a bounded Phase 8 evaluation-harness foundation for GMS.

Goals:
1. Add a small deterministic local evaluation harness that exercises core GMS behaviors from the roadmap.
2. Cover at least these scenario categories:
   - knowledge update / overwrite behavior
   - quarantine / rejection behavior
   - episodic recall behavior
   - abstention / clean error behavior when data is missing
3. Produce machine-readable results with pass/fail per scenario and an aggregate summary.
4. Add focused tests for the harness itself.

Implementation target:
- Prefer a new tool or script under `tools/`
- Add corresponding tests under `tests/`

Suggested shape:
- A script such as `tools/gms_eval.py`
- A callable function that runs a deterministic suite inside a temporary `MEMORY_ROOT`
- JSON output with:
  - scenario name
  - category
  - passed
  - details
  - totals summary

Constraints:
- Do not revert unrelated changes.
- Be surgical.
- Do not introduce network requirements.
- Do not rely on Ollama or FAISS being reachable for the harness to pass.
- Reuse the existing MCP tool functions where practical instead of duplicating business logic.
- Keep the first pass small and defensible; this is a foundation, not the final benchmark program.
- If your environment exposes local coding skills, use a `python-testing-patterns` mindset.

Validation:
- Run `/home/mihir/projects/global-memory/.venv/bin/python -m unittest discover -s /home/mihir/projects/global-memory/tests -v`
- Run `/home/mihir/projects/global-memory/.venv/bin/python -m py_compile /home/mihir/projects/global-memory/tools/memory_mcp_server.py /home/mihir/projects/global-memory/tools/gms_eval.py`

Deliverables:
- Make the code changes.
- Run the validations.
- Print a concise summary listing:
  1. exact files changed
  2. exact harness behaviors added
  3. validation commands run and whether they passed
  4. any residual risk
