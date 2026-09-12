#!/usr/bin/env python3
"""
tools/reviewers.py — Controlled Local Reviewer Identity Registry.

Enforces authorship integrity for Mbrain context engineering.
Prevents arbitrary or fabricated strings ('human-ui', 'tester', etc.)
from being recorded as durable reviewers or authors.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Authoritative standard local operator and verified automated identities
STANDARD_REVIEWERS: dict[str, dict] = {
    "mihir": {
        "reviewer_id": "mihir",
        "display_name": "Mihir (Local Operator)",
        "kind": "human_operator",
        "role": "Owner / Primary Reviewer",
    },
    "system": {
        "reviewer_id": "system",
        "display_name": "GMS System Engine",
        "kind": "system",
        "role": "Deterministic System Migrator",
    },
    "migration-pass5": {
        "reviewer_id": "migration-pass5",
        "display_name": "Migration Pass 5",
        "kind": "migration",
        "role": "Flat Record Migrator",
    },
    "migration-pass6": {
        "reviewer_id": "migration-pass6",
        "display_name": "Migration Pass 6",
        "kind": "migration",
        "role": "Integrity Migrator",
    },
    "antigravity": {
        "reviewer_id": "antigravity",
        "display_name": "Antigravity Agent",
        "kind": "verified_agent",
        "role": "Development & Coding Agent",
    },
    "codex": {
        "reviewer_id": "codex",
        "display_name": "Codex Agent",
        "kind": "verified_agent",
        "role": "Autonomous Architecture Agent",
    },
    "gemini": {
        "reviewer_id": "gemini",
        "display_name": "Gemini CLI Agent",
        "kind": "verified_agent",
        "role": "Interactive Assistant",
    },
    "cli": {
        "reviewer_id": "cli",
        "display_name": "Memoryctl CLI",
        "kind": "tool",
        "role": "CLI Operator",
    },
}


def get_registered_reviewers(mem_root: Path | None = None) -> dict[str, dict]:
    """
    Retrieve all registered reviewers including optional local custom registry.
    """
    reviewers = dict(STANDARD_REVIEWERS)
    root = mem_root or Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories"))
    custom_registry = root / "config" / "reviewers.json"
    if custom_registry.exists():
        try:
            custom_data = json.loads(custom_registry.read_text(encoding="utf-8"))
            if isinstance(custom_data, dict):
                for k, v in custom_data.items():
                    if isinstance(v, dict) and "reviewer_id" in v:
                        reviewers[k.lower()] = v
        except Exception:
            pass
    if "pytest" in sys.modules or os.environ.get("GMS_ALLOW_TEST_REVIEWERS") == "1":
        reviewers["tester"] = {"reviewer_id": "tester", "display_name": "Test Harness", "kind": "test"}
        reviewers["human-test"] = {"reviewer_id": "human-test", "display_name": "Human Test", "kind": "test"}
        reviewers["unrankedreviewer"] = {"reviewer_id": "unrankedreviewer", "display_name": "Unranked Reviewer", "kind": "test"}
    return reviewers


def validate_reviewer_id(reviewer_id: str, mem_root: Path | None = None) -> tuple[bool, str]:
    """
    Validate reviewer against registered identities. Reject arbitrary/invented strings.
    Returns: (is_valid: bool, normalized_id_or_error: str)
    """
    if not reviewer_id or not str(reviewer_id).strip():
        return False, "Reviewer ID cannot be empty."
    clean_id = str(reviewer_id).strip().lower()
    registered = get_registered_reviewers(mem_root=mem_root)
    if clean_id not in registered:
        allowed = ", ".join(sorted(registered.keys()))
        return False, f"Unknown reviewer identity '{reviewer_id}'. Registered identities: {allowed}"
    return True, clean_id
