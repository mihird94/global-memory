"""
harvest_fixtures.py — Evaluation Fixtures Corpus for Pass 5 Context Harvesting
=============================================================================
Provides test fixtures covering the 10 scenarios defined in MBRAIN_PASS_5_CONTEXT_HARVESTING_SPEC.md §12:
1. explicit user decision with rationale
2. decision with no rationale (must fail validation)
3. technical fact derived from test output
4. stale project-state update
5. superseded decision
6. two agents disagreeing
7. secret embedded in nested evidence (must be rejected)
8. duplicate wording under different keys
9. same key with meaningful update
10. irrelevant conversational noise
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict

SOURCE_REF = "episodic/history/2026-09-08.md#sec-1"
SOURCE_TEXT = (
    "2026-09-08 [10:00] - Mihir: We must retire global agent trust in Mbrain. "
    "A single score collapses task domain, evidence quality, and failure severity into false certainty. "
    "Instead, show separate provenance, recency, disputes, and task-scoped outcomes. "
    "All 160 pytest tests pass in 10.91 seconds. SQLite connection uses WAL mode and busy_timeout=5000. "
    "Codex: AlphaOS sizing requires fresh broker positions and protective stops before emitting quantity. "
    "Antigravity: Sizing should also allow discretionary override under high conviction. "
    "Mihir: No, never override safety floors without fresh broker positions. "
    "Project global-memory milestone M4 is active as of 2026-09-08. "
    "Note: API key sk-live-99238481923849182391283912839128 was refreshed. "
    "Conversation: Had tea and walked the dog around the park."
)
SOURCE_HASH = hashlib.sha256(SOURCE_TEXT.encode("utf-8")).hexdigest()

HARVEST_EVAL_CORPUS: Dict[str, Dict[str, Any]] = {
    # 1. Explicit user decision with rationale (MUST PASS)
    "1_user_decision_with_rationale": {
        "scenario": "explicit user decision with rationale",
        "should_validate": True,
        "should_auto_promote": False,  # Decisions never auto-promote
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "mbrain.agent_trust_architecture",
            "statement": "Do not use a global agent trust or reliability score in Mbrain.",
            "rationale": "A single score collapses unrelated dimensions and creates false certainty.",
            "implications": [
                "Show provenance, recency, contributions, disputes, and outcomes separately.",
                "Evaluate claims and tasks rather than agent identity."
            ],
            "scope": {
                "level": "project",
                "project": "global-memory",
                "workstream": "mbrain",
                "applies_to": ["desktop-ui", "dream-cycle", "context-packets"]
            },
            "provenance": {
                "observed_agents": ["Mihir", "Codex"],
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z",
                "prompt_version": "context-harvest-v1",
                "provider": "antigravity",
                "model": "Gemini 3.5 Flash"
            },
            "evidence": [
                {"type": "user_instruction", "ref": SOURCE_REF, "excerpt_hash": f"sha256:{SOURCE_HASH}"}
            ],
            "freshness": {
                "effective_at": "2026-09-08T18:00:00Z",
                "review_after": None,
                "supersedes": []
            },
            "review": {
                "status": "proposed",
                "requires_human": True,
                "reasons": ["architectural decision extracted by LLM"]
            }
        }
    },

    # 2. Decision with no rationale (MUST FAIL VALIDATION)
    "2_decision_without_rationale": {
        "scenario": "decision with no rationale",
        "should_validate": False,
        "expected_error": "rationale",
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "mbrain.bad_decision",
            "statement": "Do not use global agent trust.",
            "rationale": "",  # Missing rationale
            "implications": ["Do something differently"],
            "scope": {"project": "global-memory"},
            "provenance": {
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z"
            },
            "evidence": [{"type": "source_document", "ref": SOURCE_REF}]
        }
    },

    # 3. Technical fact derived from test output (VALID)
    "3_technical_fact_from_tests": {
        "scenario": "technical fact derived from test output",
        "should_validate": True,
        "should_auto_promote": False,  # LLM extracted fact stays proposed
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "fact",
            "key": "tests.full_suite_status",
            "statement": "All 160 pytest test suites pass in 10.91 seconds on Python 3.13.",
            "scope": {
                "level": "project",
                "project": "global-memory",
                "workstream": "testing"
            },
            "provenance": {
                "observed_agents": ["Codex"],
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z",
                "prompt_version": "context-harvest-v1"
            },
            "evidence": [
                {"type": "test_output", "ref": SOURCE_REF, "excerpt_hash": f"sha256:{SOURCE_HASH}"}
            ]
        }
    },

    # 4. Stale project-state update (VALID RECORD, REQUIRING REVIEW)
    "4_stale_project_state": {
        "scenario": "stale project-state update",
        "should_validate": True,
        "should_auto_promote": False,
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "project_state",
            "key": "global-memory.project_state",
            "statement": "Milestone M4 active; task handoff completed.",
            "project": "global-memory",
            "effective_at": "2026-08-01T00:00:00Z",  # Stale date
            "verification_status": "partially_verified",
            "scope": {"project": "global-memory"},
            "provenance": {
                "extractor": "DreamCycle-ollama",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z"
            }
        }
    },

    # 5. Superseded decision (VALID, EXPLICIT SUPERSEDING)
    "5_superseded_decision": {
        "scenario": "superseded decision",
        "should_validate": True,
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "mbrain.trust_computation",
            "statement": "Replace Dawid-Skene beta-binomial trust model with claim-level provenance audit.",
            "rationale": "Beta-binomial trust across disparate domains produces misleading unified confidence.",
            "implications": ["Disable run_beta_binomial_trust_calibration by default."],
            "scope": {"project": "global-memory", "workstream": "dream-cycle"},
            "provenance": {
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z"
            },
            "evidence": [{"type": "source_document", "ref": SOURCE_REF}],
            "freshness": {
                "supersedes": ["mbrain.legacy_dawid_skene_calibration"]
            }
        }
    },

    # 6. Two agents disagreeing (OBSERVATION WITH DISPUTE)
    "6_agents_disagreeing": {
        "scenario": "two agents disagreeing",
        "should_validate": True,
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "observation",
            "key": "alphaos.sizing_dispute",
            "statement": "Codex and Antigravity disagree on whether discretionary override is permitted on sizing safety floors.",
            "uncertainty": "User explicitly ruled against overriding safety floors; awaiting codified policy.",
            "scope": {"project": "alphaos"},
            "provenance": {
                "observed_agents": ["Codex", "Antigravity", "Mihir"],
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z"
            },
            "review": {
                "status": "proposed",
                "requires_human": True,
                "reasons": ["unresolved dispute between agents"]
            }
        }
    },

    # 7. Secret embedded in nested evidence (MUST BE REJECTED)
    "7_secret_embedded_in_payload": {
        "scenario": "secret embedded in nested evidence",
        "should_validate": False,
        "expected_error": "secret",
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "fact",
            "key": "infra.api_key_update",
            "statement": "Updated production API key credentials.",
            "scope": {"project": "infra"},
            "provenance": {
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z"
            },
            "evidence": [
                {
                    "type": "source_document",
                    "ref": SOURCE_REF,
                    "note": "Note: API key sk-live-99238481923849182391283912839128 was refreshed"
                }
            ]
        }
    },

    # 8. Duplicate wording under different keys (VALID SCHEMA, STAGING DEDUPE IDENTIFIER)
    "8_duplicate_wording_variant": {
        "scenario": "duplicate wording under different keys",
        "should_validate": True,
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "mbrain.agent_trust_policy_alt",
            "statement": "Do not use a global agent trust or reliability score in Mbrain.",
            "rationale": "A single score collapses unrelated dimensions and creates false certainty.",
            "implications": [
                "Show provenance, recency, contributions, disputes, and outcomes separately."
            ],
            "scope": {"project": "global-memory"},
            "provenance": {
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z"
            },
            "evidence": [{"type": "source_document", "ref": SOURCE_REF}]
        }
    },

    # 9. Same key with meaningful update (VALID SCHEMA)
    "9_same_key_meaningful_update": {
        "scenario": "same key with meaningful update",
        "should_validate": True,
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "mbrain.agent_trust_architecture",
            "statement": "Do not use a global agent trust or reliability score in Mbrain, and reject synthetic proxy metrics.",
            "rationale": "A single score collapses unrelated dimensions into false certainty; proxy names like health score reintroduce the same defect.",
            "implications": [
                "Show provenance, recency, contributions, disputes, and outcomes separately.",
                "Explicitly forbid synthetic composite scores in UI and context packets."
            ],
            "scope": {
                "level": "project",
                "project": "global-memory",
                "workstream": "mbrain",
                "applies_to": ["desktop-ui", "dream-cycle", "context-packets"]
            },
            "provenance": {
                "observed_agents": ["Mihir", "Codex"],
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:30:00Z",
                "prompt_version": "context-harvest-v1"
            },
            "evidence": [{"type": "source_document", "ref": SOURCE_REF}]
        }
    },

    # 10. Irrelevant conversational noise (INVALID FOR DURABLE RECORD)
    "10_conversational_noise": {
        "scenario": "irrelevant conversational noise",
        "should_validate": False,
        "expected_error": "rationale",
        "record": {
            "schema_version": "gms-context-record-v1",
            "record_type": "decision",
            "key": "personal.tea_and_walk",
            "statement": "Had tea and walked the dog around the park.",
            "rationale": "Had tea and walked the dog around the park.",  # Identical to statement!
            "implications": [],  # Empty implications
            "scope": {"level": "personal"},
            "provenance": {
                "extractor": "DreamCycle-antigravity",
                "source_refs": [SOURCE_REF],
                "source_hashes": [f"sha256:{SOURCE_HASH}"],
                "extracted_at": "2026-09-08T18:00:00Z"
            }
        }
    }
}

GOLD_HARVEST_CORPUS = [
    {
        "id": "gold_1_architecture_decision",
        "description": "Architectural decision extraction with rationale, constraints, and negative noise control",
        "excerpt": (
            "2026-09-08 [10:00] - Mihir: We must retire global agent trust in Mbrain. "
            "A single score collapses task domain, evidence quality, and failure severity into false certainty. "
            "Instead, show separate provenance, recency, disputes, and task-scoped outcomes. "
            "SQLite connection must use WAL mode and busy_timeout=5000 to prevent database lockouts. "
            "Note: API key sk-live-99238481923849182391283912839128 was refreshed. "
            "Personal: Had tea and walked the dog around the park."
        ),
        "expected_candidates": [
            {
                "key_pattern": r"(agent_trust|trust_architecture|retire_global_trust)",
                "expected_type": "decision",
                "required_keywords": ["retire", "trust"],
                "rationale_keywords": ["collapses", "certainty"],
            },
            {
                "key_pattern": r"(sqlite|wal_mode|busy_timeout)",
                "expected_type": "procedure",
                "required_keywords": ["wal", "busy_timeout"],
            }
        ],
        "prohibited_extracts": ["sk-live-99238481923849182391283912839128", "walked the dog", "tea"],
        "expected_triples": [
            ("agent trust", "retired_in", "mbrain"),
            ("sqlite", "uses", "wal mode"),
        ]
    },
    {
        "id": "gold_2_operational_procedure",
        "description": "Operational CLI workflow and environment precondition extraction",
        "excerpt": (
            "2026-10-12: Resolved AlphaOS workspace path migration. "
            "When developing AlphaOS swing components on macOS arm64, always point the active workspace to "
            "~/projects/alphaos-swing/ rather than legacy home scratch. "
            "Precondition: ensure Robinhood credentials are loaded via environment variables before running scan. "
            "Conversation: Discussed dinner options with family."
        ),
        "expected_candidates": [
            {
                "key_pattern": r"(alphaos_workspace|workspace_path|alphaos_mac)",
                "expected_type": "procedure",
                "required_keywords": ["alphaos", "workspace"],
            }
        ],
        "prohibited_extracts": ["dinner options", "family"],
        "expected_triples": [
            ("alphaos workspace", "located_at", "~/projects/alphaos-swing/"),
        ]
    },
    {
        "id": "gold_3_quantitative_policy",
        "description": "Quantitative risk policy with downstream trade enforcement",
        "excerpt": (
            "2026-10-13 [14:00]: Enforced AlphaOS protective stop invariant. "
            "Never emit order quantities or size additions without fresh broker positions and protective trailing stops. "
            "Rationale: Unchecked discretionary sizing causes unmanaged portfolio heat and drawdown risk. "
            "Downstream rule: Trading controller must reject order tickets that lack registered stop orders."
        ),
        "expected_candidates": [
            {
                "key_pattern": r"(alphaos_stop|protective_stop|sizing_policy|order_sizing)",
                "expected_type": "policy",
                "required_keywords": ["stop", "size", "order"],
                "rationale_keywords": ["heat", "drawdown", "risk"],
            }
        ],
        "prohibited_extracts": [],
        "expected_triples": [
            ("alphaos order sizing", "requires", "protective stops"),
        ]
    }
]
