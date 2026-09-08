#!/usr/bin/env bash
# post_session_harvest.sh — Automated Post-Session Micro-Consolidation Hook
# Usage:
#   ./post_session_harvest.sh "Session summary..." [agent_name]
set -euo pipefail

SUMMARY="${1:-Session completed}"
AGENT="${2:-${USER:-agent}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Portable Python resolver
if [[ -n "${PYTHON_BIN:-}" && -x "${PYTHON_BIN}" ]]; then
  PYTHON="${PYTHON_BIN}"
elif [[ -x "${SCRIPT_DIR}/../.venv/bin/python" ]]; then
  PYTHON="${SCRIPT_DIR}/../.venv/bin/python"
elif [[ -n "${CONDA_PREFIX:-}" && -x "${CONDA_PREFIX}/bin/python" ]]; then
  PYTHON="${CONDA_PREFIX}/bin/python"
else
  PYTHON="python3"
fi

exec "${PYTHON}" "${SCRIPT_DIR}/harvest.py" --agent "${AGENT}" --summary "${SUMMARY}" "$@"
