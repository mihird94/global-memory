"""LoCoMo (Long Conversational Memory) benchmark adapter.

Adapts the 5 core conversational memory dimensions defined in LoCoMo (Snap Research, ACL 2024):
1. Single-hop factual recall across multi-session dialogue history.
2. Multi-hop conversational reasoning synthesizing facts across distant sessions.
3. Temporal reasoning over session timestamps, chronology, and sequence of events.
4. Open-domain context synthesis and persona/preference summarization.
5. Adversarial / Abstention probing (refusal on unrecorded facts or false premises).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LoCoMoTestCase:
    id: str
    category: str  # single_hop, multi_hop, temporal, open_domain, adversarial
    query: str
    project: str = ""
    as_of: str | None = None
    evidence_sessions: tuple[str, ...] = ()
    relevant_keys: tuple[str, ...] = ()
    superseded_keys: tuple[str, ...] = ()
    prohibited_leaks: tuple[str, ...] = ()
    should_abstain: bool = False
    description: str = ""
    variant_of: str | None = None


# 12 Canonical LoCoMo test cases spanning all 5 categories
CANONICAL_LOCOMO_CASES: list[LoCoMoTestCase] = [
    # 1. Single-Hop Conversational Recall
    LoCoMoTestCase(
        id="locomo_single_1_dev_environment",
        category="single_hop",
        query="What code editor and color theme does Mihir prefer for development?",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("cursor", "dark modern"),
        description="Single-hop recall of user development environment preferences stated in Session 1.",
    ),
    LoCoMoTestCase(
        id="locomo_single_2_minipc_hostname",
        category="single_hop",
        query="What is the MiniPC network hostname and default user account?",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("minipc-server", "mihir"),
        description="Single-hop recall of MiniPC machine hostname and username from machine setup dialogue.",
    ),
    LoCoMoTestCase(
        id="locomo_single_3_alphaos_broker",
        category="single_hop",
        query="Which execution broker integration was selected for AlphaOS swing trading?",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430",),
        relevant_keys=("robinhood", "broker"),
        description="Single-hop recall of chosen broker API from AlphaOS planning session.",
    ),

    # 2. Multi-Hop Conversational Reasoning
    LoCoMoTestCase(
        id="locomo_multi_1_embedding_batch_sizing",
        category="multi_hop",
        query="Why was nomic-embed-text selected and what batch size was configured for memory indexing?",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1130"),
        relevant_keys=("nomic-embed-text", "batch", "32"),
        description="Multi-hop reasoning synthesizing model evaluation and local Ollama batch sizing decisions.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_2_alphaos_heat_management",
        category="multi_hop",
        query="When sector allocation hits the 40% cap, how does AlphaOS maintain the 5% capital heat ceiling?",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430", "project_brief"),
        relevant_keys=("capital", "heat", "40%", "5%"),
        description="Multi-hop reasoning connecting portfolio sizing caps with capital heat risk ceilings.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_3_dreamcycle_launchd_cutover",
        category="multi_hop",
        query="How was the nightly Dream Cycle migrated from an ad-hoc cron schedule to launchd?",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_2305"),
        relevant_keys=("03:10", "com.user.gms-dream-cycle.plist"),
        superseded_keys=("02:00",),
        description="Multi-hop reasoning tracing the cutover of scheduled consolidation across days.",
    ),

    # 3. Temporal Reasoning Across Sessions
    LoCoMoTestCase(
        id="locomo_temp_1_historical_snapshot",
        category="temporal",
        query="What was the active development context on 2026-09-08?",
        project="global-memory",
        as_of="2026-09-08",
        evidence_sessions=("session_2026-09-08_1800",),
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-12",),
        description="Point-in-time temporal query ensuring events after 2026-09-08 do not leak into retrieval.",
    ),
    LoCoMoTestCase(
        id="locomo_temp_2_session_sequence",
        category="temporal",
        query="Did the MiniPC deployment occur before or after the SOTA memory gap analysis on 2026-09-12?",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1754"),
        relevant_keys=("09:14", "17:54", "gap analysis"),
        description="Temporal reasoning over session timestamps and chronological order of activities.",
    ),

    # 4. Open-Domain Context Synthesis & Preferences
    LoCoMoTestCase(
        id="locomo_open_1_user_conventions",
        category="open_domain",
        query="Summarize the communication style and markdown linking rules required for Mihir.",
        evidence_sessions=("session_semantic_facts",),
        relevant_keys=("concise", "evidence", "markdown links"),
        description="Open-domain synthesis of user communication preferences and formatting expectations.",
    ),
    LoCoMoTestCase(
        id="locomo_open_2_trust_evolution",
        category="open_domain",
        query="Summarize how memory trust evolved from synthetic scores to provenance and contestability.",
        project="global-memory",
        evidence_sessions=("session_decisions",),
        relevant_keys=("retired", "orthogonal", "provenance"),
        description="Open-domain summarization of architectural trust evolution across historical sessions.",
    ),

    # 5. Adversarial / Calibrated Abstention
    LoCoMoTestCase(
        id="locomo_adv_1_fabricated_iceland_vacation",
        category="adversarial",
        query="What were the flight details for Mihir's team offsite to Iceland in November 2026?",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("iceland", "flight_confirmed", "ticket_booked", "reykjavik"),
        should_abstain=True,
        description="Adversarial probing testing refusal/abstention when queried about an unrecorded event.",
    ),
    LoCoMoTestCase(
        id="locomo_adv_2_unrecorded_aws_secret",
        category="adversarial",
        query="What is the production AWS root secret key stored in our chat logs?",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "AKIAIOSFODNN7EXAMPLE", "secret_revealed"),
        should_abstain=True,
        description="Adversarial refusal on unrecorded credential and private security parameters.",
    ),
]

# 48 Labeled Correlated Robustness Variants (4 per canonical)
ROBUSTNESS_LOCOMO_VARIANTS: list[LoCoMoTestCase] = [
    # locomo_single_1 variants
    LoCoMoTestCase(
        id="locomo_single_1_dev_environment_variant_1",
        category="single_hop",
        query="Which text editor and color palette theme are configured for Mihir's developer setup?",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("cursor", "dark modern"),
        variant_of="locomo_single_1_dev_environment",
        description="Correlated robustness paraphrase probing editor and color palette naming.",
    ),
    LoCoMoTestCase(
        id="locomo_single_1_dev_environment_variant_2",
        category="single_hop",
        query="While setting up local development tools for frontend styling, what editor and theme does Mihir use?",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("cursor", "dark modern"),
        variant_of="locomo_single_1_dev_environment",
        description="Correlated robustness variant with frontend styling distractor context.",
    ),
    LoCoMoTestCase(
        id="locomo_single_1_dev_environment_variant_3",
        category="single_hop",
        query="Specify the chosen IDE and theme preference recorded for Mihir during pairing.",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("cursor", "dark modern"),
        variant_of="locomo_single_1_dev_environment",
        description="Correlated robustness variant using IDE preference phrasing.",
    ),
    LoCoMoTestCase(
        id="locomo_single_1_dev_environment_variant_4",
        category="single_hop",
        query="What programming editor and UI color scheme did Mihir establish in early setup discussions?",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("cursor", "dark modern"),
        variant_of="locomo_single_1_dev_environment",
        description="Correlated robustness variant referencing conversational setup discussions.",
    ),

    # locomo_single_2 variants
    LoCoMoTestCase(
        id="locomo_single_2_minipc_hostname_variant_1",
        category="single_hop",
        query="Which hostname and login username are assigned to the MiniPC on the network?",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("minipc-server", "mihir"),
        variant_of="locomo_single_2_minipc_hostname",
        description="Correlated robustness paraphrase using login username terminology.",
    ),
    LoCoMoTestCase(
        id="locomo_single_2_minipc_hostname_variant_2",
        category="single_hop",
        query="For remote headless SSH administration over Tailscale, what is the MiniPC machine hostname and user?",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("minipc-server", "mihir"),
        variant_of="locomo_single_2_minipc_hostname",
        description="Correlated robustness variant with remote headless SSH context injection.",
    ),
    LoCoMoTestCase(
        id="locomo_single_2_minipc_hostname_variant_3",
        category="single_hop",
        query="Provide the network hostname and Unix user identity configured on the MiniPC.",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("minipc-server", "mihir"),
        variant_of="locomo_single_2_minipc_hostname",
        description="Correlated robustness variant with Unix user identity phrasing.",
    ),
    LoCoMoTestCase(
        id="locomo_single_2_minipc_hostname_variant_4",
        category="single_hop",
        query="What machine host identifier and user account were assigned to the MiniPC server?",
        evidence_sessions=("session_2026-09-08_1015",),
        relevant_keys=("minipc-server", "mihir"),
        variant_of="locomo_single_2_minipc_hostname",
        description="Correlated robustness variant using machine host identifier phrasing.",
    ),

    # locomo_single_3 variants
    LoCoMoTestCase(
        id="locomo_single_3_alphaos_broker_variant_1",
        category="single_hop",
        query="What broker platform API is connected for executing swing orders in AlphaOS?",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430",),
        relevant_keys=("robinhood", "broker"),
        variant_of="locomo_single_3_alphaos_broker",
        description="Correlated robustness paraphrase probing order execution broker platform.",
    ),
    LoCoMoTestCase(
        id="locomo_single_3_alphaos_broker_variant_2",
        category="single_hop",
        query="In the trading execution infrastructure review, which broker endpoint was designated for AlphaOS swing positions?",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430",),
        relevant_keys=("robinhood", "broker"),
        variant_of="locomo_single_3_alphaos_broker",
        description="Correlated robustness variant with infrastructure review distractor.",
    ),
    LoCoMoTestCase(
        id="locomo_single_3_alphaos_broker_variant_3",
        category="single_hop",
        query="Identify the designated brokerage API selected for trade execution within AlphaOS.",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430",),
        relevant_keys=("robinhood", "broker"),
        variant_of="locomo_single_3_alphaos_broker",
        description="Correlated robustness variant focusing on designated brokerage API phrasing.",
    ),
    LoCoMoTestCase(
        id="locomo_single_3_alphaos_broker_variant_4",
        category="single_hop",
        query="Which broker interface executes AlphaOS swing trades according to planning sessions?",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430",),
        relevant_keys=("robinhood", "broker"),
        variant_of="locomo_single_3_alphaos_broker",
        description="Correlated robustness variant referencing planning session outcomes.",
    ),

    # locomo_multi_1 variants
    LoCoMoTestCase(
        id="locomo_multi_1_embedding_batch_sizing_variant_1",
        category="multi_hop",
        query="Connecting model evaluation and Ollama memory constraints, what embedding model and batching limit are in use?",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1130"),
        relevant_keys=("nomic-embed-text", "batch", "32"),
        variant_of="locomo_multi_1_embedding_batch_sizing",
        description="Correlated robustness multi-hop recomposition linking model evaluation and Ollama memory constraints.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_1_embedding_batch_sizing_variant_2",
        category="multi_hop",
        query="What embedding model was chosen for local indexing, and what batch size prevents local Ollama out-of-memory errors?",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1130"),
        relevant_keys=("nomic-embed-text", "batch", "32"),
        variant_of="locomo_multi_1_embedding_batch_sizing",
        description="Correlated robustness multi-hop synthesis emphasizing OOM prevention.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_1_embedding_batch_sizing_variant_3",
        category="multi_hop",
        query="During vector index tuning on local hardware, why was nomic-embed-text chosen and at what batch size?",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1130"),
        relevant_keys=("nomic-embed-text", "batch", "32"),
        variant_of="locomo_multi_1_embedding_batch_sizing",
        description="Correlated robustness variant with local hardware tuning context.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_1_embedding_batch_sizing_variant_4",
        category="multi_hop",
        query="Synthesize the rationale for adopting nomic-embed-text along with its operational batch size setting.",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1130"),
        relevant_keys=("nomic-embed-text", "batch", "32"),
        variant_of="locomo_multi_1_embedding_batch_sizing",
        description="Correlated robustness multi-hop reasoning connecting rationale to operational batching.",
    ),

    # locomo_multi_2 variants
    LoCoMoTestCase(
        id="locomo_multi_2_alphaos_heat_management_variant_1",
        category="multi_hop",
        query="How do AlphaOS risk rules reconcile a 40% sector allocation ceiling with the 5% capital-at-risk heat cap?",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430", "project_brief"),
        relevant_keys=("capital", "heat", "40%", "5%"),
        variant_of="locomo_multi_2_alphaos_heat_management",
        description="Correlated robustness multi-hop recomposition reconciling sector allocation and capital heat.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_2_alphaos_heat_management_variant_2",
        category="multi_hop",
        query="Under AlphaOS portfolio sizing guidelines, how is the 5% capital heat ceiling protected if a sector reaches 40%?",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430", "project_brief"),
        relevant_keys=("capital", "heat", "40%", "5%"),
        variant_of="locomo_multi_2_alphaos_heat_management",
        description="Correlated robustness paraphrase probing protection of heat ceiling under sector concentration.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_2_alphaos_heat_management_variant_3",
        category="multi_hop",
        query="In a volatile market where sector concentration approaches 40%, how does AlphaOS constrain portfolio capital heat to 5%?",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430", "project_brief"),
        relevant_keys=("capital", "heat", "40%", "5%"),
        variant_of="locomo_multi_2_alphaos_heat_management",
        description="Correlated robustness variant with market volatility distractor framing.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_2_alphaos_heat_management_variant_4",
        category="multi_hop",
        query="Synthesize the interaction between sector cap 40% and capital-at-risk heat cap 5% in AlphaOS.",
        project="alphaos",
        evidence_sessions=("session_2026-09-08_1430", "project_brief"),
        relevant_keys=("capital", "heat", "40%", "5%"),
        variant_of="locomo_multi_2_alphaos_heat_management",
        description="Correlated robustness multi-hop synthesis of risk constraints.",
    ),

    # locomo_multi_3 variants
    LoCoMoTestCase(
        id="locomo_multi_3_dreamcycle_launchd_cutover_variant_1",
        category="multi_hop",
        query="Trace the transition of nightly memory consolidation from legacy 02:00 cron to the 03:10 launchd plist.",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_2305"),
        relevant_keys=("03:10", "com.user.gms-dream-cycle.plist"),
        superseded_keys=("02:00",),
        variant_of="locomo_multi_3_dreamcycle_launchd_cutover",
        description="Correlated robustness multi-hop recomposition tracing cutover from legacy cron to launchd.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_3_dreamcycle_launchd_cutover_variant_2",
        category="multi_hop",
        query="What launchd configuration replaced the legacy cron script for the 03:10 AM Dream Cycle consolidation?",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_2305"),
        relevant_keys=("03:10", "com.user.gms-dream-cycle.plist"),
        superseded_keys=("02:00",),
        variant_of="locomo_multi_3_dreamcycle_launchd_cutover",
        description="Correlated robustness variant focusing on replacement launchd configuration.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_3_dreamcycle_launchd_cutover_variant_3",
        category="multi_hop",
        query="Following the daemon reliability review, how did the nightly Dream Cycle schedule move to launchd com.user.gms-dream-cycle.plist?",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_2305"),
        relevant_keys=("03:10", "com.user.gms-dream-cycle.plist"),
        superseded_keys=("02:00",),
        variant_of="locomo_multi_3_dreamcycle_launchd_cutover",
        description="Correlated robustness variant with daemon reliability distractor framing.",
    ),
    LoCoMoTestCase(
        id="locomo_multi_3_dreamcycle_launchd_cutover_variant_4",
        category="multi_hop",
        query="Explain the migration path of the nightly consolidation runner from cron to launchd.",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_2305"),
        relevant_keys=("03:10", "com.user.gms-dream-cycle.plist"),
        superseded_keys=("02:00",),
        variant_of="locomo_multi_3_dreamcycle_launchd_cutover",
        description="Correlated robustness multi-hop explanation of consolidation runner migration.",
    ),

    # locomo_temp_1 variants
    LoCoMoTestCase(
        id="locomo_temp_1_historical_snapshot_variant_1",
        category="temporal",
        query="As of 2026-09-08, what was the active focus and context recorded for global-memory?",
        project="global-memory",
        as_of="2026-09-08",
        evidence_sessions=("session_2026-09-08_1800",),
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-12",),
        variant_of="locomo_temp_1_historical_snapshot",
        description="Correlated robustness temporal bound probe ensuring future constraints do not leak.",
    ),
    LoCoMoTestCase(
        id="locomo_temp_1_historical_snapshot_variant_2",
        category="temporal",
        query="Limiting context strictly to 2026-09-08, what milestone was active before Pass 4?",
        project="global-memory",
        as_of="2026-09-08",
        evidence_sessions=("session_2026-09-08_1800",),
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-12",),
        variant_of="locomo_temp_1_historical_snapshot",
        description="Correlated robustness point-in-time snapshot inquiry bounded by date.",
    ),
    LoCoMoTestCase(
        id="locomo_temp_1_historical_snapshot_variant_3",
        category="temporal",
        query="Looking back at the state of global-memory on 2026-09-08, what were the recorded active constraints?",
        project="global-memory",
        as_of="2026-09-08",
        evidence_sessions=("session_2026-09-08_1800",),
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-12",),
        variant_of="locomo_temp_1_historical_snapshot",
        description="Correlated robustness temporal milestone verification.",
    ),
    LoCoMoTestCase(
        id="locomo_temp_1_historical_snapshot_variant_4",
        category="temporal",
        query="Retrieve the historical active context recorded on 2026-09-08 without future milestone leakage.",
        project="global-memory",
        as_of="2026-09-08",
        relevant_keys=("2026-09-08",),
        superseded_keys=("2026-09-12",),
        variant_of="locomo_temp_1_historical_snapshot",
        description="Correlated robustness temporal isolation check forbidding post-dated entries.",
    ),

    # locomo_temp_2 variants
    LoCoMoTestCase(
        id="locomo_temp_2_session_sequence_variant_1",
        category="temporal",
        query="Between the MiniPC setup at 09:14 and the SOTA gap analysis at 17:54 on 2026-09-12, which event came first?",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1754"),
        relevant_keys=("09:14", "17:54", "gap analysis"),
        variant_of="locomo_temp_2_session_sequence",
        description="Correlated robustness temporal reversal comparing relative event order.",
    ),
    LoCoMoTestCase(
        id="locomo_temp_2_session_sequence_variant_2",
        category="temporal",
        query="Chronologically order the MiniPC deployment and the SOTA memory gap analysis completed on 2026-09-12.",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1754"),
        relevant_keys=("09:14", "17:54", "gap analysis"),
        variant_of="locomo_temp_2_session_sequence",
        description="Correlated robustness chronological sequence inquiry.",
    ),
    LoCoMoTestCase(
        id="locomo_temp_2_session_sequence_variant_3",
        category="temporal",
        query="On 2026-09-12, was the SOTA gap analysis conducted prior to or following the MiniPC installation?",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1754"),
        relevant_keys=("09:14", "17:54", "gap analysis"),
        variant_of="locomo_temp_2_session_sequence",
        description="Correlated robustness temporal sequence inquiry using prior-to/following framing.",
    ),
    LoCoMoTestCase(
        id="locomo_temp_2_session_sequence_variant_4",
        category="temporal",
        query="Verify the relative timeline of MiniPC upgrade vs SOTA memory gap analysis on 2026-09-12.",
        project="global-memory",
        evidence_sessions=("session_2026-09-12_0914", "session_2026-09-12_1754"),
        relevant_keys=("09:14", "17:54", "gap analysis"),
        variant_of="locomo_temp_2_session_sequence",
        description="Correlated robustness relative timeline check.",
    ),

    # locomo_open_1 variants
    LoCoMoTestCase(
        id="locomo_open_1_user_conventions_variant_1",
        category="open_domain",
        query="What formatting standards, evidence expectations, and markdown link conventions apply when writing to Mihir?",
        evidence_sessions=("session_semantic_facts",),
        relevant_keys=("concise", "evidence", "markdown links"),
        variant_of="locomo_open_1_user_conventions",
        description="Correlated robustness open-domain paraphrase probing formatting and evidence conventions.",
    ),
    LoCoMoTestCase(
        id="locomo_open_1_user_conventions_variant_2",
        category="open_domain",
        query="When preparing reports and responses for Mihir, what are the mandatory markdown linking and communication rules?",
        evidence_sessions=("session_semantic_facts",),
        relevant_keys=("concise", "evidence", "markdown links"),
        variant_of="locomo_open_1_user_conventions",
        description="Correlated robustness variant with report preparation distractor.",
    ),
    LoCoMoTestCase(
        id="locomo_open_1_user_conventions_variant_3",
        category="open_domain",
        query="Outline the user communication preferences regarding conciseness, evidence backing, and file links.",
        evidence_sessions=("session_semantic_facts",),
        relevant_keys=("concise", "evidence", "markdown links"),
        variant_of="locomo_open_1_user_conventions",
        description="Correlated robustness outline inquiry targeting conciseness and evidence backing.",
    ),
    LoCoMoTestCase(
        id="locomo_open_1_user_conventions_variant_4",
        category="open_domain",
        query="Summarize Mihir's established collaboration guidelines for agent interaction and citation.",
        evidence_sessions=("session_semantic_facts",),
        relevant_keys=("concise", "evidence", "markdown links"),
        variant_of="locomo_open_1_user_conventions",
        description="Correlated robustness conversational synthesis on collaboration guidelines.",
    ),

    # locomo_open_2 variants
    LoCoMoTestCase(
        id="locomo_open_2_trust_evolution_variant_1",
        category="open_domain",
        query="Why was global agent trust replaced by provenance, audit records, and contestable curation in Mbrain?",
        project="global-memory",
        evidence_sessions=("session_decisions",),
        relevant_keys=("retired", "orthogonal", "provenance"),
        variant_of="locomo_open_2_trust_evolution",
        description="Correlated robustness open-domain synthesis of trust architecture evolution.",
    ),
    LoCoMoTestCase(
        id="locomo_open_2_trust_evolution_variant_2",
        category="open_domain",
        query="Across past architecture decisions, summarize the evolution from synthetic reliability percentages to objective evidence.",
        project="global-memory",
        evidence_sessions=("session_decisions",),
        relevant_keys=("retired", "orthogonal", "provenance"),
        variant_of="locomo_open_2_trust_evolution",
        description="Correlated robustness variant focusing on departure from synthetic percentages.",
    ),
    LoCoMoTestCase(
        id="locomo_open_2_trust_evolution_variant_3",
        category="open_domain",
        query="Explain the rationale behind retiring synthetic agent trust scores in favor of dispute provenance.",
        project="global-memory",
        evidence_sessions=("session_decisions",),
        relevant_keys=("retired", "orthogonal", "provenance"),
        variant_of="locomo_open_2_trust_evolution",
        description="Correlated robustness variant emphasizing dispute provenance rationale.",
    ),
    LoCoMoTestCase(
        id="locomo_open_2_trust_evolution_variant_4",
        category="open_domain",
        query="Trace the architectural transition from synthetic trust metrics to objective review history.",
        project="global-memory",
        evidence_sessions=("session_decisions",),
        relevant_keys=("retired", "orthogonal", "provenance"),
        variant_of="locomo_open_2_trust_evolution",
        description="Correlated robustness architectural transition trace.",
    ),

    # locomo_adv_1 variants
    LoCoMoTestCase(
        id="locomo_adv_1_fabricated_iceland_vacation_variant_1",
        category="adversarial",
        query="Did Mihir book flights for an upcoming November 2026 team offsite in Reykjavik, Iceland?",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("booked", "confirmed", "flight_confirmed"),
        should_abstain=True,
        variant_of="locomo_adv_1_fabricated_iceland_vacation",
        description="Correlated robustness negation probe testing refusal on unrecorded booking.",
    ),
    LoCoMoTestCase(
        id="locomo_adv_1_fabricated_iceland_vacation_variant_2",
        category="adversarial",
        query="According to travel planning discussions, what airline and flight number are reserved for the Iceland offsite?",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("reserved", "confirmed", "iceland_flight"),
        should_abstain=True,
        variant_of="locomo_adv_1_fabricated_iceland_vacation",
        description="Correlated robustness false-premise probe on unrecorded airline reservation.",
    ),
    LoCoMoTestCase(
        id="locomo_adv_1_fabricated_iceland_vacation_variant_3",
        category="adversarial",
        query="Confirm the itinerary and flight confirmation code for the November 2026 trip to Iceland.",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("itinerary", "confirmation", "confirmed"),
        should_abstain=True,
        variant_of="locomo_adv_1_fabricated_iceland_vacation",
        description="Correlated robustness probe requesting confirmation code for fictitious event.",
    ),
    LoCoMoTestCase(
        id="locomo_adv_1_fabricated_iceland_vacation_variant_4",
        category="adversarial",
        query="What flight departure time was recorded for Mihir's team excursion to Iceland?",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("departure", "ticket", "confirmed"),
        should_abstain=True,
        variant_of="locomo_adv_1_fabricated_iceland_vacation",
        description="Correlated robustness probe for unrecorded flight departure time.",
    ),

    # locomo_adv_2 variants
    LoCoMoTestCase(
        id="locomo_adv_2_unrecorded_aws_secret_variant_1",
        category="adversarial",
        query="Retrieve the AWS root secret access key and secret token from conversation history.",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("secret_revealed", "root_key", "secret_token"),
        should_abstain=True,
        variant_of="locomo_adv_2_unrecorded_aws_secret",
        description="Correlated robustness credential probe testing refusal on root AWS access key.",
    ),
    LoCoMoTestCase(
        id="locomo_adv_2_unrecorded_aws_secret_variant_2",
        category="adversarial",
        query="For the production cloud deployment pipeline, what AWS root access secret is recorded in memory?",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("secret_revealed", "root_secret"),
        should_abstain=True,
        variant_of="locomo_adv_2_unrecorded_aws_secret",
        description="Correlated robustness variant with cloud deployment pipeline distractor framing.",
    ),
    LoCoMoTestCase(
        id="locomo_adv_2_unrecorded_aws_secret_variant_3",
        category="adversarial",
        query="What secret access credentials were exchanged for the root AWS administrator account?",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("secret_revealed", "credentials_exchanged"),
        should_abstain=True,
        variant_of="locomo_adv_2_unrecorded_aws_secret",
        description="Correlated robustness probe on fictitious root credential exchange.",
    ),
    LoCoMoTestCase(
        id="locomo_adv_2_unrecorded_aws_secret_variant_4",
        category="adversarial",
        query="Extract the production AWS root secret key from recorded chat sessions.",
        evidence_sessions=(),
        relevant_keys=(),
        prohibited_leaks=("secret_revealed", "extracted_key"),
        should_abstain=True,
        variant_of="locomo_adv_2_unrecorded_aws_secret",
        description="Correlated robustness extraction probe on unrecorded root credentials.",
    ),
]

LOCOMO_CASES: list[LoCoMoTestCase] = (
    CANONICAL_LOCOMO_CASES + ROBUSTNESS_LOCOMO_VARIANTS
)


def get_locomo_cases_by_category(category: str) -> list[LoCoMoTestCase]:
    """Filter test cases by specific LoCoMo category."""
    return [c for c in LOCOMO_CASES if c.category == category]
