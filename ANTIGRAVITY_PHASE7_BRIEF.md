You are working in:
- /home/mihir/projects/global-memory

Task:
Implement a bounded Phase 7 slice for raw episodic reconstruction.

Goals:
1. Add an MCP-visible way to list episodic sources with enough metadata to select a source deterministically.
2. Add a fast summary path for a single episodic source.
3. Add a deep reconstruction path that returns the full raw episodic text for a selected source.
4. Add focused unittest coverage for the new behavior.

Implementation target:
- Primary file: tools/memory_mcp_server.py
- Tests: tests/test_memory.py

Suggested API shape:
- `mem_list_episodes`
  - Optional filters such as `limit`
  - Return source path, date if derivable, type (`history` or `journal`), and a simple size/line-count field
- `mem_get_episode`
  - Accept either `date` or `source`
  - `mode` must support `summary` and `deep`
  - `summary` should return a compact deterministic representation with metadata plus a bounded excerpt
  - `deep` should return metadata plus the full raw text

Constraints:
- Do not revert unrelated changes.
- Be surgical and keep the API small.
- Preserve existing MCP tool behavior.
- Do not add an LLM dependency for summarization.
- Use deterministic logic only.
- Keep output JSON serializable.
- If your environment exposes local coding skills, use a `python-testing-patterns` mindset for the tests.

Validation:
- Run `/home/mihir/projects/global-memory/.venv/bin/python -m unittest discover -s /home/mihir/projects/global-memory/tests -v`
- Run `/home/mihir/projects/global-memory/.venv/bin/python -m py_compile /home/mihir/projects/global-memory/tools/memory_mcp_server.py`

Deliverables:
- Make the code changes.
- Run the validations.
- Print a concise summary listing:
  1. exact files changed
  2. exact behavior added
  3. validation commands run and whether they passed
  4. any residual risk
