"""LongMemEval benchmark adapter.

Adapts the 5 core abilities defined in LongMemEval (ICLR 2025):
1. Factual Extraction
2. Multi-Session Reasoning
3. Temporal Reasoning
4. Knowledge Updates & Supersession
5. Calibrated Abstention
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LongMemEvalTestCase:
    id: str
    ability: str  # factual_extraction, multi_session_reasoning, temporal_reasoning, knowledge_update, abstention
    query: str
    project: str = ""
    as_of: str | None = None
    relevant_keys: tuple[str, ...] = ()
    superseded_keys: tuple[str, ...] = ()
    prohibited_leaks: tuple[str, ...] = ()
    should_abstain: bool = False
    description: str = ""
    variant_of: str | None = None


# 12 Canonical benchmark cases spanning all 5 abilities
CANONICAL_LONGMEMEVAL_CASES: list[LongMemEvalTestCase] = [
    # 1. Factual Extraction
    LongMemEvalTestCase(
        id="lme_fact_1_sqlite_concurrency",
        ability="factual_extraction",
        query="What SQLite settings govern database concurrency in GMS?",
        project="global-memory",
        relevant_keys=("wal", "busy_timeout", "concurrency"),
        description="Extract specific operational parameters governing database concurrency.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_2_dream_cycle_schedule",
        ability="factual_extraction",
        query="What is the scheduled launchd time for nightly Dream Cycle?",
        project="global-memory",
        relevant_keys=("03:10", "dream_cycle"),
        superseded_keys=("02:00",),
        description="Extract current Dream Cycle scheduled execution time.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_3_tailscale_ip",
        ability="factual_extraction",
        query="What is the MiniPC Tailscale IP address?",
        relevant_keys=("100.85.120.45", "minipc"),
        description="Extract specific machine network address from environment configuration.",
    ),

    # 2. Multi-Session Reasoning
    LongMemEvalTestCase(
        id="lme_multi_1_agent_trust_retirement",
        ability="multi_session_reasoning",
        query="Why was global agent trust retired in Mbrain and what replaced it?",
        project="global-memory",
        relevant_keys=("retired", "collapses", "orthogonal", "provenance"),
        description="Synthesize rationale across architecture spec, convention docs, and claims ledger.",
    ),
    LongMemEvalTestCase(
        id="lme_multi_2_alphaos_sizing",
        ability="multi_session_reasoning",
        query="How does AlphaOS distinguish capital-at-risk heat from marked profit giveback?",
        project="alphaos",
        relevant_keys=("capital", "heat", "giveback", "sizing"),
        description="Reason across sizing guidelines and risk management procedures.",
    ),

    # 3. Temporal Reasoning
    LongMemEvalTestCase(
        id="lme_temp_1_historical_context",
        ability="temporal_reasoning",
        query="What was the active context on 2026-09-08?",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"),
        description="Point-in-time query ensuring future events do not leak into historical view.",
    ),
    LongMemEvalTestCase(
        id="lme_temp_2_pass3_milestone",
        ability="temporal_reasoning",
        query="What was implemented in Mbrain UX Pass 3?",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("projects", "workspace", "pass 3"),
        superseded_keys=("pass 7", "pass 8"),
        description="Verify milestone retrieval bounded by historical timeframe.",
    ),

    # 4. Knowledge Updates & Supersession
    LongMemEvalTestCase(
        id="lme_update_1_alphaos_plugin_version",
        ability="knowledge_update",
        query="What is the active canonical plugin version for AlphaOS?",
        project="alphaos",
        relevant_keys=("0.2.0+codex.20260723182357", "alphaos.swing.plugin.version"),
        superseded_keys=("0.2.0+codex.20260723175253",),
        description="Verify newer version supersedes older conflicting version without collision leak.",
    ),
    LongMemEvalTestCase(
        id="lme_update_2_dream_cycle_schedule_update",
        ability="knowledge_update",
        query="Scheduled time for nightly memory consolidation",
        project="global-memory",
        relevant_keys=("03:10",),
        superseded_keys=("02:00",),
        description="Verify 03:10 schedule is active and 02:00 legacy schedule is marked superseded.",
    ),

    # 5. Calibrated Abstention
    LongMemEvalTestCase(
        id="lme_abstain_1_unknown_cryptocurrency",
        ability="abstention",
        query="What is the configured Ethereum staking validator private key?",
        project="global-memory",
        relevant_keys=(),
        prohibited_leaks=("mnemonic", "private_key", "0x"),
        should_abstain=True,
        description="System must abstain on unrecorded, non-existent private keys.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_2_unrecorded_flight_number",
        ability="abstention",
        query="What was the flight number for Mihir's trip to Tokyo in 2024?",
        relevant_keys=(),
        prohibited_leaks=("reservation", "confirmed", "booking"),
        should_abstain=True,
        description="System must abstain when evidence is completely missing rather than hallucinating.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_3_opaque_status_actionability",
        ability="abstention",
        query="Execute car stickers status next action",
        project="global-memory",
        relevant_keys=("car_stickers_status",),
        prohibited_leaks=("execute", "active_truth"),
        should_abstain=True,
        description="System must abstain from taking action when an entity status is opaque/archived.",
    ),
]

# 48 Labeled Correlated Robustness Variants (4 per canonical)
ROBUSTNESS_LONGMEMEVAL_VARIANTS: list[LongMemEvalTestCase] = [
    # lme_fact_1 variants
    LongMemEvalTestCase(
        id="lme_fact_1_sqlite_concurrency_variant_1",
        ability="factual_extraction",
        query="Which SQLite PRAGMA directives and concurrency configurations are required in GMS?",
        project="global-memory",
        relevant_keys=("wal", "busy_timeout", "concurrency"),
        variant_of="lme_fact_1_sqlite_concurrency",
        description="Correlated robustness paraphrase probing exact PRAGMA configuration terminology.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_1_sqlite_concurrency_variant_2",
        ability="factual_extraction",
        query="For multi-agent database access, what WAL and busy timeout settings does GMS mandate?",
        project="global-memory",
        relevant_keys=("wal", "busy_timeout", "concurrency"),
        variant_of="lme_fact_1_sqlite_concurrency",
        description="Correlated robustness variant with multi-agent operational context injection.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_1_sqlite_concurrency_variant_3",
        ability="factual_extraction",
        query="Identify the SQLite parameters governing concurrent writer safety in global-memory.",
        project="global-memory",
        relevant_keys=("wal", "busy_timeout", "concurrency"),
        variant_of="lme_fact_1_sqlite_concurrency",
        description="Correlated robustness variant focusing on writer safety phrasing.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_1_sqlite_concurrency_variant_4",
        ability="factual_extraction",
        query="What settings ensure database concurrency safety without locking errors in SQLite?",
        project="global-memory",
        relevant_keys=("wal", "busy_timeout", "concurrency"),
        variant_of="lme_fact_1_sqlite_concurrency",
        description="Correlated robustness variant probing locking error mitigation.",
    ),

    # lme_fact_2 variants
    LongMemEvalTestCase(
        id="lme_fact_2_dream_cycle_schedule_variant_1",
        ability="factual_extraction",
        query="At what local time is the nightly Dream Cycle scheduled via launchd?",
        project="global-memory",
        relevant_keys=("03:10", "dream_cycle"),
        superseded_keys=("02:00",),
        variant_of="lme_fact_2_dream_cycle_schedule",
        description="Correlated robustness variant probing launchd execution timing.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_2_dream_cycle_schedule_variant_2",
        ability="factual_extraction",
        query="What is the automated execution schedule configured for nightly memory consolidation?",
        project="global-memory",
        relevant_keys=("03:10", "dream_cycle"),
        superseded_keys=("02:00",),
        variant_of="lme_fact_2_dream_cycle_schedule",
        description="Correlated robustness paraphrase emphasizing memory consolidation.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_2_dream_cycle_schedule_variant_3",
        ability="factual_extraction",
        query="When does the launchd service com.user.gms-dream-cycle.plist run consolidation each night?",
        project="global-memory",
        relevant_keys=("03:10", "dream_cycle"),
        superseded_keys=("02:00",),
        variant_of="lme_fact_2_dream_cycle_schedule",
        description="Correlated robustness variant injecting exact plist identifier.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_2_dream_cycle_schedule_variant_4",
        ability="factual_extraction",
        query="Specify the active scheduled time for the nightly Dream Cycle daemon job.",
        project="global-memory",
        relevant_keys=("03:10", "dream_cycle"),
        superseded_keys=("02:00",),
        variant_of="lme_fact_2_dream_cycle_schedule",
        description="Correlated robustness variant probing daemon scheduling.",
    ),

    # lme_fact_3 variants
    LongMemEvalTestCase(
        id="lme_fact_3_tailscale_ip_variant_1",
        ability="factual_extraction",
        query="What IP address is assigned to the MiniPC on the Tailscale private network?",
        relevant_keys=("100.85.120.45", "minipc"),
        variant_of="lme_fact_3_tailscale_ip",
        description="Correlated robustness paraphrase highlighting private network context.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_3_tailscale_ip_variant_2",
        ability="factual_extraction",
        query="Provide the Tailscale VPN IP for connecting to the MiniPC host.",
        relevant_keys=("100.85.120.45", "minipc"),
        variant_of="lme_fact_3_tailscale_ip",
        description="Correlated robustness variant with VPN host connectivity phrasing.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_3_tailscale_ip_variant_3",
        ability="factual_extraction",
        query="Which network address reaches the MiniPC node over Tailscale?",
        relevant_keys=("100.85.120.45", "minipc"),
        variant_of="lme_fact_3_tailscale_ip",
        description="Correlated robustness variant using node reachability terminology.",
    ),
    LongMemEvalTestCase(
        id="lme_fact_3_tailscale_ip_variant_4",
        ability="factual_extraction",
        query="For remote SSH administration, what is the MiniPC's Tailscale IP address?",
        relevant_keys=("100.85.120.45", "minipc"),
        variant_of="lme_fact_3_tailscale_ip",
        description="Correlated robustness variant with SSH distractor phrasing.",
    ),

    # lme_multi_1 variants
    LongMemEvalTestCase(
        id="lme_multi_1_agent_trust_retirement_variant_1",
        ability="multi_session_reasoning",
        query="Why did Mbrain retire single-dimension agent trust scores, and how is reliability verified instead?",
        project="global-memory",
        relevant_keys=("retired", "collapses", "orthogonal", "provenance"),
        variant_of="lme_multi_1_agent_trust_retirement",
        description="Correlated robustness multi-hop synthesis probing the replacement verification mechanism.",
    ),
    LongMemEvalTestCase(
        id="lme_multi_1_agent_trust_retirement_variant_2",
        ability="multi_session_reasoning",
        query="What architectural reasons led to abandoning synthetic trust numbers in favor of provenance?",
        project="global-memory",
        relevant_keys=("retired", "collapses", "orthogonal", "provenance"),
        variant_of="lme_multi_1_agent_trust_retirement",
        description="Correlated robustness variant probing architectural rationale for provenance over synthetic numbers.",
    ),
    LongMemEvalTestCase(
        id="lme_multi_1_agent_trust_retirement_variant_3",
        ability="multi_session_reasoning",
        query="Explain why global agent trust percentages were replaced with dispute records and review history.",
        project="global-memory",
        relevant_keys=("retired", "collapses", "orthogonal", "provenance"),
        variant_of="lme_multi_1_agent_trust_retirement",
        description="Correlated robustness variant highlighting review history and dispute records.",
    ),
    LongMemEvalTestCase(
        id="lme_multi_1_agent_trust_retirement_variant_4",
        ability="multi_session_reasoning",
        query="Synthesize the rationale for retiring synthetic agent scores across conventions and claims.",
        project="global-memory",
        relevant_keys=("retired", "collapses", "orthogonal", "provenance"),
        variant_of="lme_multi_1_agent_trust_retirement",
        description="Correlated robustness multi-hop synthesis across conventions and claims.",
    ),

    # lme_multi_2 variants
    LongMemEvalTestCase(
        id="lme_multi_2_alphaos_sizing_variant_1",
        ability="multi_session_reasoning",
        query="In AlphaOS portfolio sizing, what is the distinction between capital heat and profit giveback?",
        project="alphaos",
        relevant_keys=("capital", "heat", "giveback", "sizing"),
        variant_of="lme_multi_2_alphaos_sizing",
        description="Correlated robustness variant probing portfolio sizing distinctions.",
    ),
    LongMemEvalTestCase(
        id="lme_multi_2_alphaos_sizing_variant_2",
        ability="multi_session_reasoning",
        query="How do AlphaOS risk rules separate open profit giveback from capital-at-risk heat?",
        project="alphaos",
        relevant_keys=("capital", "heat", "giveback", "sizing"),
        variant_of="lme_multi_2_alphaos_sizing",
        description="Correlated robustness paraphrase contrasting open profit giveback and capital heat.",
    ),
    LongMemEvalTestCase(
        id="lme_multi_2_alphaos_sizing_variant_3",
        ability="multi_session_reasoning",
        query="Explain how capital-at-risk heat is treated differently from unrealized gain giveback in AlphaOS.",
        project="alphaos",
        relevant_keys=("capital", "heat", "giveback", "sizing"),
        variant_of="lme_multi_2_alphaos_sizing",
        description="Correlated robustness variant using unrealized gain terminology.",
    ),
    LongMemEvalTestCase(
        id="lme_multi_2_alphaos_sizing_variant_4",
        ability="multi_session_reasoning",
        query="Under AlphaOS risk guidelines, how does position sizing distinguish capital heat from giveback?",
        project="alphaos",
        relevant_keys=("capital", "heat", "giveback", "sizing"),
        variant_of="lme_multi_2_alphaos_sizing",
        description="Correlated robustness multi-hop synthesis of risk guidelines and position sizing.",
    ),

    # lme_temp_1 variants
    LongMemEvalTestCase(
        id="lme_temp_1_historical_context_variant_1",
        ability="temporal_reasoning",
        query="As of 2026-09-08, what was the active context and constraint state for global-memory?",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"),
        variant_of="lme_temp_1_historical_context",
        description="Correlated robustness temporal bound probe ensuring future constraints do not leak.",
    ),
    LongMemEvalTestCase(
        id="lme_temp_1_historical_context_variant_2",
        ability="temporal_reasoning",
        query="Limiting retrieval to the historical snapshot on 2026-09-08, what was the active project focus?",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"),
        variant_of="lme_temp_1_historical_context",
        description="Correlated robustness point-in-time snapshot inquiry.",
    ),
    LongMemEvalTestCase(
        id="lme_temp_1_historical_context_variant_3",
        ability="temporal_reasoning",
        query="What milestones and active constraints were recorded as of 2026-09-08?",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"),
        variant_of="lme_temp_1_historical_context",
        description="Correlated robustness temporal milestone verification.",
    ),
    LongMemEvalTestCase(
        id="lme_temp_1_historical_context_variant_4",
        ability="temporal_reasoning",
        query="Retrieve the point-in-time active context for 2026-09-08 without post-dated leakage.",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"),
        variant_of="lme_temp_1_historical_context",
        description="Correlated robustness temporal isolation check forbidding post-dated entries.",
    ),

    # lme_temp_2 variants
    LongMemEvalTestCase(
        id="lme_temp_2_pass3_milestone_variant_1",
        ability="temporal_reasoning",
        query="On 2026-09-08, what UI and workspace capabilities were delivered in Mbrain Pass 3?",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("projects", "workspace", "pass 3"),
        superseded_keys=("pass 7", "pass 8"),
        variant_of="lme_temp_2_pass3_milestone",
        description="Correlated robustness temporal query probing workspace deliverables.",
    ),
    LongMemEvalTestCase(
        id="lme_temp_2_pass3_milestone_variant_2",
        ability="temporal_reasoning",
        query="What did Pass 3 accomplish for project context navigation on 2026-09-08?",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("projects", "workspace", "pass 3"),
        superseded_keys=("pass 7", "pass 8"),
        variant_of="lme_temp_2_pass3_milestone",
        description="Correlated robustness variant probing context navigation achievements.",
    ),
    LongMemEvalTestCase(
        id="lme_temp_2_pass3_milestone_variant_3",
        ability="temporal_reasoning",
        query="As of 2026-09-08, describe the workspace layout implemented during Mbrain Pass 3.",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("projects", "workspace", "pass 3"),
        superseded_keys=("pass 7", "pass 8"),
        variant_of="lme_temp_2_pass3_milestone",
        description="Correlated robustness variant targeting the 3-column layout description.",
    ),
    LongMemEvalTestCase(
        id="lme_temp_2_pass3_milestone_variant_4",
        ability="temporal_reasoning",
        query="Which milestone delivered the 3-column Projects Context Workspace on 2026-09-08?",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("projects", "workspace", "pass 3"),
        superseded_keys=("pass 7", "pass 8"),
        variant_of="lme_temp_2_pass3_milestone",
        description="Correlated robustness temporal milestone attribution check.",
    ),

    # lme_update_1 variants
    LongMemEvalTestCase(
        id="lme_update_1_alphaos_plugin_version_variant_1",
        ability="knowledge_update",
        query="Which canonical plugin release version is currently active for AlphaOS swing workflows?",
        project="alphaos",
        relevant_keys=("0.2.0+codex.20260723182357", "alphaos.swing.plugin.version"),
        superseded_keys=("0.2.0+codex.20260723175253",),
        variant_of="lme_update_1_alphaos_plugin_version",
        description="Correlated robustness paraphrase probing active swing plugin release version.",
    ),
    LongMemEvalTestCase(
        id="lme_update_1_alphaos_plugin_version_variant_2",
        ability="knowledge_update",
        query="What is the verified AlphaOS swing plugin version, superseding older commit builds?",
        project="alphaos",
        relevant_keys=("0.2.0+codex.20260723182357", "alphaos.swing.plugin.version"),
        superseded_keys=("0.2.0+codex.20260723175253",),
        variant_of="lme_update_1_alphaos_plugin_version",
        description="Correlated robustness variant checking supersession of older commit builds.",
    ),
    LongMemEvalTestCase(
        id="lme_update_1_alphaos_plugin_version_variant_3",
        ability="knowledge_update",
        query="Retrieve the active canonical plugin version for AlphaOS without leaking the older build.",
        project="alphaos",
        relevant_keys=("0.2.0+codex.20260723182357", "alphaos.swing.plugin.version"),
        superseded_keys=("0.2.0+codex.20260723175253",),
        variant_of="lme_update_1_alphaos_plugin_version",
        description="Correlated robustness variant verifying zero stale leakage.",
    ),
    LongMemEvalTestCase(
        id="lme_update_1_alphaos_plugin_version_variant_4",
        ability="knowledge_update",
        query="Under active decisions, what version string defines the current AlphaOS plugin release?",
        project="alphaos",
        relevant_keys=("0.2.0+codex.20260723182357", "alphaos.swing.plugin.version"),
        superseded_keys=("0.2.0+codex.20260723175253",),
        variant_of="lme_update_1_alphaos_plugin_version",
        description="Correlated robustness variant referencing active decisions for plugin version.",
    ),

    # lme_update_2 variants
    LongMemEvalTestCase(
        id="lme_update_2_dream_cycle_schedule_update_variant_1",
        ability="knowledge_update",
        query="What is the updated active launchd schedule for nightly memory consolidation?",
        project="global-memory",
        relevant_keys=("03:10",),
        superseded_keys=("02:00",),
        variant_of="lme_update_2_dream_cycle_schedule_update",
        description="Correlated robustness paraphrase targeting updated consolidation schedule.",
    ),
    LongMemEvalTestCase(
        id="lme_update_2_dream_cycle_schedule_update_variant_2",
        ability="knowledge_update",
        query="Verify the current consolidation time, confirming the 02:00 legacy schedule is superseded.",
        project="global-memory",
        relevant_keys=("03:10",),
        superseded_keys=("02:00",),
        variant_of="lme_update_2_dream_cycle_schedule_update",
        description="Correlated robustness variant confirming supersession of 02:00 legacy schedule.",
    ),
    LongMemEvalTestCase(
        id="lme_update_2_dream_cycle_schedule_update_variant_3",
        ability="knowledge_update",
        query="At what time does the active nightly consolidation job execute following the schedule update?",
        project="global-memory",
        relevant_keys=("03:10",),
        superseded_keys=("02:00",),
        variant_of="lme_update_2_dream_cycle_schedule_update",
        description="Correlated robustness variant probing post-update execution time.",
    ),
    LongMemEvalTestCase(
        id="lme_update_2_dream_cycle_schedule_update_variant_4",
        ability="knowledge_update",
        query="Retrieve the active 03:10 consolidation schedule without treating 02:00 as current truth.",
        project="global-memory",
        relevant_keys=("03:10",),
        superseded_keys=("02:00",),
        variant_of="lme_update_2_dream_cycle_schedule_update",
        description="Correlated robustness variant preventing stale 02:00 truth leakage.",
    ),

    # lme_abstain_1 variants
    LongMemEvalTestCase(
        id="lme_abstain_1_unknown_cryptocurrency_variant_1",
        ability="abstention",
        query="What is the private validator mnemonic key for Ethereum staking?",
        project="global-memory",
        relevant_keys=(),
        prohibited_leaks=("mnemonic", "private_key", "0x"),
        should_abstain=True,
        variant_of="lme_abstain_1_unknown_cryptocurrency",
        description="Correlated robustness adversarial probe for non-existent mnemonic credentials.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_1_unknown_cryptocurrency_variant_2",
        ability="abstention",
        query="Retrieve the Ethereum staking private key credentials recorded in system memory.",
        project="global-memory",
        relevant_keys=(),
        prohibited_leaks=("credentials", "private_key"),
        should_abstain=True,
        variant_of="lme_abstain_1_unknown_cryptocurrency",
        description="Correlated robustness probe for unrecorded staking credentials.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_1_unknown_cryptocurrency_variant_3",
        ability="abstention",
        query="Confirm the secret keystore password for Ethereum validator nodes.",
        project="global-memory",
        relevant_keys=(),
        prohibited_leaks=("password", "keystore"),
        should_abstain=True,
        variant_of="lme_abstain_1_unknown_cryptocurrency",
        description="Correlated robustness false-premise probe on secret keystore password.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_1_unknown_cryptocurrency_variant_4",
        ability="abstention",
        query="What private key was generated for Ethereum proof-of-stake validation?",
        project="global-memory",
        relevant_keys=(),
        prohibited_leaks=("private_key", "secret"),
        should_abstain=True,
        variant_of="lme_abstain_1_unknown_cryptocurrency",
        description="Correlated robustness probe on unrecorded proof-of-stake keys.",
    ),

    # lme_abstain_2 variants
    LongMemEvalTestCase(
        id="lme_abstain_2_unrecorded_flight_number_variant_1",
        ability="abstention",
        query="What flight reservation code was confirmed for Mihir's trip to Tokyo in 2024?",
        relevant_keys=(),
        prohibited_leaks=("reservation", "confirmed", "booking"),
        should_abstain=True,
        variant_of="lme_abstain_2_unrecorded_flight_number",
        description="Correlated robustness probe on unrecorded flight reservation code.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_2_unrecorded_flight_number_variant_2",
        ability="abstention",
        query="Provide the flight number and departure gate for the 2024 Tokyo flight.",
        relevant_keys=(),
        prohibited_leaks=("flight_number", "gate"),
        should_abstain=True,
        variant_of="lme_abstain_2_unrecorded_flight_number",
        description="Correlated robustness probe for unrecorded flight number and gate.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_2_unrecorded_flight_number_variant_3",
        ability="abstention",
        query="Which airline carried Mihir to Tokyo during the 2024 vacation?",
        relevant_keys=(),
        prohibited_leaks=("airline", "ticket"),
        should_abstain=True,
        variant_of="lme_abstain_2_unrecorded_flight_number",
        description="Correlated robustness inquiry on unrecorded carrier.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_2_unrecorded_flight_number_variant_4",
        ability="abstention",
        query="Extract the booked airline and flight itinerary for Mihir's 2024 travel to Tokyo.",
        relevant_keys=(),
        prohibited_leaks=("itinerary", "ticket"),
        should_abstain=True,
        variant_of="lme_abstain_2_unrecorded_flight_number",
        description="Correlated robustness probe on unrecorded flight itinerary.",
    ),

    # lme_abstain_3 variants
    LongMemEvalTestCase(
        id="lme_abstain_3_opaque_status_actionability_variant_1",
        ability="abstention",
        query="Execute the next operational step for car stickers status.",
        project="global-memory",
        relevant_keys=("car_stickers_status",),
        prohibited_leaks=("execute", "active_truth"),
        should_abstain=True,
        variant_of="lme_abstain_3_opaque_status_actionability",
        description="Correlated robustness probe attempting execution on archived/opaque status.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_3_opaque_status_actionability_variant_2",
        ability="abstention",
        query="What immediate action should be taken based on the car stickers record?",
        project="global-memory",
        relevant_keys=("car_stickers_status",),
        prohibited_leaks=("action_taken", "proceed"),
        should_abstain=True,
        variant_of="lme_abstain_3_opaque_status_actionability",
        description="Correlated robustness inquiry testing actionability rejection on archived status.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_3_opaque_status_actionability_variant_3",
        ability="abstention",
        query="Treat car stickers status as an active actionable directive and proceed.",
        project="global-memory",
        relevant_keys=("car_stickers_status",),
        prohibited_leaks=("active_directive", "proceed"),
        should_abstain=True,
        variant_of="lme_abstain_3_opaque_status_actionability",
        description="Correlated robustness adversarial probe requesting active treatment of archived status.",
    ),
    LongMemEvalTestCase(
        id="lme_abstain_3_opaque_status_actionability_variant_4",
        ability="abstention",
        query="Trigger execution of the next task associated with car stickers status.",
        project="global-memory",
        relevant_keys=("car_stickers_status",),
        prohibited_leaks=("trigger", "execute"),
        should_abstain=True,
        variant_of="lme_abstain_3_opaque_status_actionability",
        description="Correlated robustness probe attempting task trigger from archived state.",
    ),
]

LONGMEMEVAL_CASES: list[LongMemEvalTestCase] = (
    CANONICAL_LONGMEMEVAL_CASES + ROBUSTNESS_LONGMEMEVAL_VARIANTS
)


def get_cases_by_ability(ability: str) -> list[LongMemEvalTestCase]:
    """Filter test cases by specific LongMemEval ability."""
    return [c for c in LONGMEMEVAL_CASES if c.ability == ability]
