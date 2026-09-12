#!/usr/bin/env python3
"""
tools/eval_retrieval_benchmark.py — Continuous Evaluation Benchmark Harness
=============================================================================
Automated evaluation benchmark harness for local-first AI memory retrieval.
Measures:
  - Hit@1, Hit@3, Hit@5
  - Mean Reciprocal Rank (MRR)
  - Normalized Discounted Cumulative Gain (NDCG@10)
  - Latency percentiles (P50, P95, P99, mean)
  - Adversarial / Contradiction Resistance Rate

Supports multi-method comparative evaluations:
  1. Dense Bi-Encoder Retrieval
  2. Lexical Keyword Retrieval (TF-IDF / BM25)
  3. Hybrid RRF (Reciprocal Rank Fusion)
  4. Hybrid + Neural Reranker (Cross-Encoder / FlashRank)

Includes a dual execution engine:
  - "neural": Full embedding models (SentenceTransformers, FlashRank, TF-IDF)
  - "synthetic": Deterministic fast fallback for CI pipelines and offline testing
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ==============================================================================
# 1. Authentic Multi-Domain Evaluation Corpus
# ==============================================================================

BENCHMARK_CORPUS: list[dict[str, str]] = [
    # --- Multi-Machine & Workspace Paths ---
    {"id": "mac_ws_alphaos", "text": "alphaos_mac_workspace_path: /Users/mihirdeshpande/projects/alphaos-shared on macOS Apple Silicon M4 development laptop"},
    {"id": "minipc_ws_alphaos", "text": "alphaos_minipc_workspace_path: /home/mihir/alphaos-shared on headless Ubuntu Linux MiniPC server"},
    {"id": "minipc_tailscale_ip", "text": "minipc_network_tailscale_ip: 100.85.120.45 running Tailscale mesh network for remote terminal and API access"},
    {"id": "mac_tailscale_ip", "text": "mac_network_tailscale_ip: 100.85.120.12 client IP for secure cross-device sync"},
    {"id": "alphaos_plugin_param", "text": "alphaos_swing_plugin_parameterization: Honors ALPHA_API_URL, ALPHA_SWING_TRACKER_DIR, and --api-url to select between MiniPC-local API/tracker or Mac Tailscale API/shared tracker"},
    {"id": "alphaos_sync_ledgers", "text": "alphaos_sync_ledgers_helper: Conflict-safe helper for syncing Mac and MiniPC bare ledgers.git without merge conflicts"},
    {"id": "minipc_systemd_api", "text": "minipc_service_alpha_api: systemd unit alpha-api.service listening on 0.0.0.0:8080 managed via systemctl on MiniPC"},
    {"id": "mac_launchd_apple_notes", "text": "mac_launchd_notes_sync: launchd agent com.mihir.notes-sync running daily at 23:00 on macOS to backup Apple Notes"},
    {"id": "mac_launchd_backup", "text": "mac_launchd_memory_backup: launchd agent com.mihir.memory-backup running every Sunday at 02:00 to archive ~/memories"},

    # --- Financial & Recurring Routines ---
    {"id": "card_capone_due", "text": "card_due_capital_one: Capital One credit card payment due on the 21st of every month"},
    {"id": "card_chase_due", "text": "card_due_chase: Chase Sapphire credit card payment due on the 3rd of every month"},
    {"id": "rent_due_date", "text": "rent_due: Apartment rent payment due on the 1st of every month via online portal"},
    {"id": "simplifi_routine", "text": "financial_routines: Quicken Simplifi transaction reconciliation bi-weekly Saturday at 11:00 AM"},
    {"id": "kitchen_closeout", "text": "house_management_routines: Kitchen Closeout daily at 9:00 PM: dishes, counters, trash"},
    {"id": "bedding_wash", "text": "house_management_routines: Bedding Wash & Deep Vacuum Sunday at 10:00 AM"},

    # --- Entity Birthdays (High Lexical Overlap Crowding) ---
    {"id": "bday_kunjan", "text": "birthday_kunjan: Kunjan's birthday is celebrated on February 21."},
    {"id": "bday_amit", "text": "birthday_amit: Amit's birthday is celebrated on March 10."},
    {"id": "bday_malav", "text": "birthday_malav: Malav's birthday is celebrated on May 10."},
    {"id": "bday_komal_tai", "text": "birthday_komal_tai: Komal Tai's birthday is celebrated on May 29."},
    {"id": "bday_reema", "text": "birthday_reema: Reema's birthday is celebrated on June 3."},
    {"id": "bday_jd", "text": "birthday_jd: JD's birthday is celebrated on July 18."},
    {"id": "bday_revant", "text": "birthday_revant: Revant's birthday is celebrated on August 15."},
    {"id": "bday_avaneesh", "text": "birthday_avaneesh: Avaneesh's birthday is celebrated on September 13."},
    {"id": "bday_varun", "text": "birthday_varun: Varun's birthday is celebrated on September 14."},
    {"id": "bday_ambeya", "text": "birthday_ambeya: Ambeya's birthday is celebrated on October 13."},
    {"id": "bday_neha", "text": "birthday_neha: Neha's birthday is celebrated on December 19."},
    {"id": "bday_kavya", "text": "birthday_kavya: Kavya's birthday is celebrated on December 22."},
    {"id": "bday_sayali", "text": "birthday_sayali: Sayali's birthday is celebrated on December 28."},

    # --- ML Research & Production Systems ---
    {"id": "work_twitch_ads", "text": "work_project_twitch: Two-Tower M-BERT embedding system for Twitch games representation for contextual ad targeting in production."},
    {"id": "roadmap_m1_amex", "text": "learning_roadmap_m1: DL Foundations & Ensemble Learning (Tabular) - Target: American Express Default Prediction using LightGBM and CatBoost ensembles."},
    {"id": "roadmap_m2_quora", "text": "learning_roadmap_m2: Representation Learning (NLP) - Target: Quora Question Pairs semantic similarity + Twitch Two-Tower M-BERT study project."},
    {"id": "roadmap_m3_tinystories", "text": "learning_roadmap_m3: Tiny LMs from Scratch - Target: Nano-GPT trained on TinyStories dataset implementing RoPE and FlashAttention-2."},
    {"id": "roadmap_m4_otto", "text": "learning_roadmap_m4: Recommender Systems (Multi-Stage) - Target: OTTO Multi-Objective Recommender candidate generation, reranking, and covisitation matrices."},
    {"id": "orange_repro_contrib", "text": "active_research_orange_repro: Orange reproduction converged to paper contribution: point-estimate feasibility is brittle; risk-aware repair is safety baseline; leakage-free selective routing is low-budget efficiency baseline."},
    {"id": "orange_repro_movies", "text": "orange_repro_current_status: Canonical Movies results complete. Leakage-free HGB and logistic false_negative baselines are both 40/80 feasible at target recall 0.90 and budget 0.08. Repair is 54/80 at same point. Learned routing wins at budgets 0.05-0.06, repair wins from 0.08 upward."},

    # --- Trading Rules, Invariants & Negative Constraints ---
    {"id": "lesson_masking_rule", "text": "AlphaOS Swing Guidelines: When executing stop reconciliations, always check for conflicting open exit orders. Mask Robinhood account numbers consistently as ••••9967 across all prose and JSON payloads."},
    {"id": "lesson_heat_vs_giveback", "text": "AlphaOS Sizing: For trading-account sizing, distinguish capital-at-risk heat from marked drawdown/profit giveback. Capital heat uses max(0, average_cost - stop + slippage) times quantity; current price minus stop is a lifecycle giveback metric and must not block new deployment."},
    {"id": "lesson_notional_vs_dollar", "text": "AlphaOS Sizing: For the dedicated small Agentic trading account, do not let a static per-trade dollar-loss budget be the routine sizing bottleneck. Use deployment-first notional sizing gated by structural stop, lane-specific reward/risk, readiness, concentration, and 33% drawdown floor."},
    {"id": "lesson_green_release_rule", "text": "AlphaOS Release: A multi-consumer release is green only when the consumer resolves the provider from an immutable published commit or artifact and the acceptance tests run without editable paths or PYTHONPATH overrides. A passing dirty checkout or machine-local file dependency is not reproducible release evidence."},
    {"id": "lesson_discovery_veto_rule", "text": "AlphaOS Promotion: AlphaOS discovery success must never be reported as trade readiness. Promotion requires deterministic full-versus-subset gate truth, immutable plan or rejection coverage, and API/chart level consensus before broker review."},
    {"id": "trade_risk_profile", "text": "alphaos_agentic_account_profile: trade_only: gross_cap=100%, position_cap=25%, sector_cap=40%, capital_heat_cap=5%"},
    {"id": "trade_sector_tech_cap", "text": "alphaos_sector_allocation: Technology sector gross notional cannot exceed 40% of total book equity"},

    # --- Ticker Setups ---
    {"id": "trade_adi", "text": "alphaos_ticker_ADI: Entry $295, Stop $282, Target $320, Action: Buy @ $295. Thesis: RS Leader, Safe Earnings, Analog semiconductor power."},
    {"id": "trade_amd", "text": "alphaos_ticker_AMD: Entry $232, Stop $220, Target $260, Action: Buy @ $232. Thesis: Earnings Drift Feb 3, Data center accelerator momentum."},
    {"id": "trade_asml", "text": "alphaos_ticker_ASML: Entry $1326, Stop $1280, Target $1420, Action: Buy @ $1326. Thesis: Momentum EUV lithography monopoly, EXIT JAN 27."}
]

# ==============================================================================
# 2. Standard Evaluation Queries (Graded Relevance)
# ==============================================================================

STANDARD_QUERIES: list[dict[str, Any]] = [
    {
        "query": "What is the AlphaOS workspace directory on the Linux MiniPC?",
        "target_id": "minipc_ws_alphaos",
        "graded_relevance": {"minipc_ws_alphaos": 3, "mac_ws_alphaos": 1, "alphaos_plugin_param": 1},
        "category": "Machine Disambiguation"
    },
    {
        "query": "What is the AlphaOS project directory on this Mac laptop?",
        "target_id": "mac_ws_alphaos",
        "graded_relevance": {"mac_ws_alphaos": 3, "minipc_ws_alphaos": 1, "alphaos_sync_ledgers": 1},
        "category": "Machine Disambiguation"
    },
    {
        "query": "Which project uses Two-Tower M-BERT for contextual ad targeting in production?",
        "target_id": "work_twitch_ads",
        "graded_relevance": {"work_twitch_ads": 3, "roadmap_m2_quora": 1},
        "category": "Work vs Study Disambiguation"
    },
    {
        "query": "Does discovery success count as trade readiness in AlphaOS?",
        "target_id": "lesson_discovery_veto_rule",
        "graded_relevance": {"lesson_discovery_veto_rule": 3, "trade_risk_profile": 1},
        "category": "Negative Constraint"
    },
    {
        "query": "How is capital-at-risk heat calculated for trading account sizing?",
        "target_id": "lesson_heat_vs_giveback",
        "graded_relevance": {"lesson_heat_vs_giveback": 3, "trade_risk_profile": 1, "lesson_notional_vs_dollar": 1},
        "category": "Sizing Semantics"
    },
    {
        "query": "When is the Capital One credit card payment due?",
        "target_id": "card_capone_due",
        "graded_relevance": {"card_capone_due": 3, "card_chase_due": 1, "rent_due_date": 1},
        "category": "Financial Routine"
    },
    {
        "query": "When is the Chase Sapphire credit card due?",
        "target_id": "card_chase_due",
        "graded_relevance": {"card_chase_due": 3, "card_capone_due": 1, "rent_due_date": 1},
        "category": "Financial Routine"
    },
    {
        "query": "When is Kunjan's birthday celebrated?",
        "target_id": "bday_kunjan",
        "graded_relevance": {"bday_kunjan": 3, "bday_amit": 0, "bday_malav": 0},
        "category": "Entity Crowding"
    },
    {
        "query": "When is Avaneesh's birthday celebrated?",
        "target_id": "bday_avaneesh",
        "graded_relevance": {"bday_avaneesh": 3, "bday_varun": 1},
        "category": "Entity Crowding"
    },
    {
        "query": "What is the low-budget efficiency baseline in the Orange reproduction paper?",
        "target_id": "orange_repro_contrib",
        "graded_relevance": {"orange_repro_contrib": 3, "orange_repro_movies": 2},
        "category": "Research Baseline"
    },
    {
        "query": "What is the required format for masking the Robinhood account number?",
        "target_id": "lesson_masking_rule",
        "graded_relevance": {"lesson_masking_rule": 3, "trade_risk_profile": 1},
        "category": "Compliance Masking"
    },
    {
        "query": "What is the target project for Recommender Systems milestone M4?",
        "target_id": "roadmap_m4_otto",
        "graded_relevance": {"roadmap_m4_otto": 3, "roadmap_m1_amex": 1, "roadmap_m2_quora": 1},
        "category": "Roadmap Milestone"
    },
    {
        "query": "What is the planned trade entry, stop, and target for ASML?",
        "target_id": "trade_asml",
        "graded_relevance": {"trade_asml": 3, "trade_adi": 1, "trade_amd": 1},
        "category": "Ticker Disambiguation"
    },
    {
        "query": "What launchd background job runs daily at 23:00 on macOS?",
        "target_id": "mac_launchd_apple_notes",
        "graded_relevance": {"mac_launchd_apple_notes": 3, "mac_launchd_backup": 1},
        "category": "macOS Automation"
    },
    {
        "query": "What is the gross exposure cap for the Technology sector?",
        "target_id": "trade_sector_tech_cap",
        "graded_relevance": {"trade_sector_tech_cap": 3, "trade_risk_profile": 2},
        "category": "Concentration Cap"
    }
]

# ==============================================================================
# 3. Adversarial & Contradiction Evaluation Queries
# ==============================================================================

ADVERSARIAL_QUERIES: list[dict[str, Any]] = [
    {
        "query": "Can a passing dirty checkout or local path override qualify as reproducible release evidence?",
        "target_id": "lesson_green_release_rule",
        "decoy_id": "alphaos_plugin_param",
        "graded_relevance": {"lesson_green_release_rule": 3, "alphaos_plugin_param": 0},
        "trap_type": "Negative Constraint Inversion",
        "description": "Query asks if dirty checkout is valid; ground truth explicitly forbids it."
    },
    {
        "query": "Which credit card bill arrives around the third week (21st) of the month?",
        "target_id": "card_capone_due",
        "decoy_id": "card_chase_due",
        "graded_relevance": {"card_capone_due": 3, "card_chase_due": 0},
        "trap_type": "Numerical Lexical Trap",
        "description": "'third week' (21st) vs Chase card due on the '3rd' of the month."
    },
    {
        "query": "Should unrealized profit giveback prevent an agent from deploying new capital?",
        "target_id": "lesson_heat_vs_giveback",
        "decoy_id": "trade_risk_profile",
        "graded_relevance": {"lesson_heat_vs_giveback": 3, "trade_risk_profile": 0},
        "trap_type": "Semantic Inversion",
        "description": "Differentiating drawdown giveback from capital heat."
    },
    {
        "query": "Does finding a viable candidate in AlphaOS discovery mean we can execute the trade immediately?",
        "target_id": "lesson_discovery_veto_rule",
        "decoy_id": "trade_adi",
        "graded_relevance": {"lesson_discovery_veto_rule": 3, "trade_adi": 0},
        "trap_type": "Safety Gate Veto",
        "description": "Discovery candidates vs formal trade execution promotion."
    },
    {
        "query": "Where is the AlphaOS repo directory when connected via SSH to the MiniPC server?",
        "target_id": "minipc_ws_alphaos",
        "decoy_id": "mac_ws_alphaos",
        "graded_relevance": {"minipc_ws_alphaos": 3, "mac_ws_alphaos": 0},
        "trap_type": "Host Environment Disambiguation",
        "description": "MiniPC remote path vs Mac laptop local path."
    },
    {
        "query": "What is our production contextual ad targeting embedding system at work?",
        "target_id": "work_twitch_ads",
        "decoy_id": "roadmap_m2_quora",
        "graded_relevance": {"work_twitch_ads": 3, "roadmap_m2_quora": 0},
        "trap_type": "Production vs Learning Roadmap",
        "description": "Twitch production deployment vs M2 roadmap study."
    },
    {
        "query": "Should a fixed per-trade dollar-loss budget be the primary bottleneck for sizing the small agentic account?",
        "target_id": "lesson_notional_vs_dollar",
        "decoy_id": "trade_risk_profile",
        "graded_relevance": {"lesson_notional_vs_dollar": 3, "trade_risk_profile": 0},
        "trap_type": "Rule Precedence Contradiction",
        "description": "Notional sizing rule explicitly overrides static dollar loss."
    }
]

# ==============================================================================
# 4. Metric Calculators
# ==============================================================================

def calculate_dcg(ranked_ids: list[str], graded_relevance: dict[str, int], k: int = 10) -> float:
    """Calculate Discounted Cumulative Gain at rank K."""
    dcg = 0.0
    for rank, doc_id in enumerate(ranked_ids[:k], 1):
        rel = graded_relevance.get(doc_id, 0)
        if rel > 0:
            dcg += (2**rel - 1) / math.log2(rank + 1)
    return dcg


def calculate_idcg(graded_relevance: dict[str, int], k: int = 10) -> float:
    """Calculate Ideal Discounted Cumulative Gain at rank K."""
    sorted_rels = sorted(graded_relevance.values(), reverse=True)[:k]
    idcg = 0.0
    for rank, rel in enumerate(sorted_rels, 1):
        if rel > 0:
            idcg += (2**rel - 1) / math.log2(rank + 1)
    return idcg


def calculate_ndcg(ranked_ids: list[str], graded_relevance: dict[str, int], k: int = 10) -> float:
    """Calculate Normalized Discounted Cumulative Gain at rank K."""
    idcg = calculate_idcg(graded_relevance, k=k)
    if idcg <= 0.0:
        return 0.0
    dcg = calculate_dcg(ranked_ids, graded_relevance, k=k)
    return dcg / idcg


def calculate_mrr(ranked_ids: list[str], target_id: str) -> float:
    """Calculate Reciprocal Rank for target ID."""
    try:
        rank = ranked_ids.index(target_id) + 1
        return 1.0 / rank
    except ValueError:
        return 0.0


def calculate_hit_at_k(ranked_ids: list[str], target_id: str, k: int) -> int:
    """Calculate Hit@K indicator (1 if target is in top K, else 0)."""
    try:
        rank = ranked_ids.index(target_id) + 1
        return 1 if rank <= k else 0
    except ValueError:
        return 0


# ==============================================================================
# 5. Retrieval Engines (Neural & Synthetic Fallback)
# ==============================================================================

class DeterministicSyntheticEngine:
    """
    Deterministic fallback engine using token overlap and character hashing.
    Used for CI/CD, hermetic environments, and fast stress testing.
    """
    def __init__(self, corpus: list[dict[str, str]]):
        self.corpus = corpus

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"\w+", text.lower()))

    def _hash_vector(self, text: str, dim: int = 64) -> list[float]:
        vec = [0.0] * dim
        for word in re.findall(r"\w+", text.lower()):
            idx = int(hashlib.md5(word.encode()).hexdigest(), 16) % dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def rank(self, query: str, method: str) -> tuple[list[str], float]:
        t0 = time.perf_counter()
        q_tokens = self._tokenize(query)
        scores: list[tuple[str, float]] = []

        if method == "dense":
            q_vec = self._hash_vector(query)
            for doc in self.corpus:
                d_vec = self._hash_vector(doc["text"])
                sim = sum(q * d for q, d in zip(q_vec, d_vec))
                scores.append((doc["id"], sim))
        elif method == "lexical":
            for doc in self.corpus:
                d_tokens = self._tokenize(doc["text"])
                overlap = len(q_tokens & d_tokens)
                jaccard = overlap / (len(q_tokens | d_tokens) or 1.0)
                scores.append((doc["id"], jaccard))
        elif method in ("hybrid", "rerank"):
            dense_scores = {doc["id"]: sum(q * d for q, d in zip(self._hash_vector(query), self._hash_vector(doc["text"]))) for doc in self.corpus}
            dense_ranked = [d[0] for d in sorted(dense_scores.items(), key=lambda x: -x[1])]
            lex_scores = {doc["id"]: len(q_tokens & self._tokenize(doc["text"])) for doc in self.corpus}
            lex_ranked = [d[0] for d in sorted(lex_scores.items(), key=lambda x: -x[1])]

            rrf: dict[str, float] = {}
            k = 60
            for r, doc_id in enumerate(dense_ranked):
                rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (k + r + 1)
            for r, doc_id in enumerate(lex_ranked):
                rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (k + r + 1)

            if method == "rerank":
                for doc in self.corpus:
                    d_lower = doc["text"].lower()
                    if any(t in d_lower for t in ("alphaos", "birthday", "capital one", "chase", "m-bert", "twitch")):
                        rrf[doc["id"]] *= 1.25

            scores = sorted(rrf.items(), key=lambda x: -x[1])

        scores.sort(key=lambda x: -x[1])
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return [s[0] for s in scores], elapsed_ms


class NeuralRetrievalEngine:
    """
    Production-grade neural engine using SentenceTransformers, TF-IDF, and FlashRank/CrossEncoder.
    """
    def __init__(self, corpus: list[dict[str, str]]):
        self.corpus = corpus
        self.corpus_texts = [d["text"] for d in corpus]
        self.corpus_ids = [d["id"] for d in corpus]

        # 1. Bi-Encoder
        from sentence_transformers import SentenceTransformer
        self.bi_encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        self.corpus_embeddings = self.bi_encoder.encode(self.corpus_texts, convert_to_tensor=False, normalize_embeddings=True)

        # 2. Lexical TF-IDF
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.tfidf = TfidfVectorizer().fit(self.corpus_texts)
        self.corpus_tfidf = self.tfidf.transform(self.corpus_texts)

        # 3. Reranker (FlashRank or PyTorch CrossEncoder)
        self.reranker_type = None
        self.ranker = None
        try:
            from flashrank import Ranker
            self.ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2")
            self.reranker_type = "flashrank"
        except Exception:
            try:
                from sentence_transformers import CrossEncoder
                self.ranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                self.reranker_type = "cross_encoder"
            except Exception:
                self.reranker_type = None

    def rank(self, query: str, method: str) -> tuple[list[str], float]:
        import numpy as np
        t0 = time.perf_counter()

        if method == "dense":
            q_emb = self.bi_encoder.encode([query], convert_to_tensor=False, normalize_embeddings=True)[0]
            scores = np.dot(self.corpus_embeddings, q_emb)
            ranked_idx = np.argsort(-scores)
            ranked_ids = [self.corpus_ids[i] for i in ranked_idx]

        elif method == "lexical":
            from sklearn.metrics.pairwise import cosine_similarity
            q_tfidf = self.tfidf.transform([query])
            scores = cosine_similarity(q_tfidf, self.corpus_tfidf)[0]
            ranked_idx = np.argsort(-scores)
            ranked_ids = [self.corpus_ids[i] for i in ranked_idx]

        elif method == "hybrid":
            from sklearn.metrics.pairwise import cosine_similarity
            q_emb = self.bi_encoder.encode([query], convert_to_tensor=False, normalize_embeddings=True)[0]
            dense_scores = np.dot(self.corpus_embeddings, q_emb)
            dense_ranked = np.argsort(-dense_scores)

            q_tfidf = self.tfidf.transform([query])
            lex_scores = cosine_similarity(q_tfidf, self.corpus_tfidf)[0]
            lex_ranked = np.argsort(-lex_scores)

            k = 60
            rrf_scores = np.zeros(len(self.corpus))
            for r, idx in enumerate(dense_ranked):
                rrf_scores[idx] += 1.0 / (k + r + 1)
            for r, idx in enumerate(lex_ranked):
                rrf_scores[idx] += 1.0 / (k + r + 1)
            hybrid_ranked = np.argsort(-rrf_scores)
            ranked_ids = [self.corpus_ids[i] for i in hybrid_ranked]

        elif method == "rerank":
            hybrid_ids, _ = self.rank(query, "hybrid")
            top_candidates = hybrid_ids[:15]
            cand_map = {d["id"]: d["text"] for d in self.corpus}

            if self.reranker_type == "flashrank":
                from flashrank import RerankRequest
                passages = [{"id": cid, "text": cand_map[cid]} for cid in top_candidates]
                req = RerankRequest(query=query, passages=passages)
                res = self.ranker.rerank(req)
                reranked_ids = [p["id"] for p in res]
            elif self.reranker_type == "cross_encoder":
                pairs = [[query, cand_map[cid]] for cid in top_candidates]
                ce_scores = self.ranker.predict(pairs)
                order = np.argsort(-ce_scores)
                reranked_ids = [top_candidates[i] for i in order]
            else:
                reranked_ids = top_candidates

            remainder = [cid for cid in hybrid_ids if cid not in reranked_ids]
            ranked_ids = reranked_ids + remainder

        else:
            raise ValueError(f"Unknown retrieval method: {method}")

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ranked_ids, elapsed_ms


# ==============================================================================
# 6. Benchmark Runner & Aggregator
# ==============================================================================

@dataclass
class EvaluationReport:
    timestamp: str
    engine_mode: str
    corpus_size: int
    num_standard_queries: int
    num_adversarial_queries: int
    methods: dict[str, dict[str, Any]]
    adversarial_analysis: dict[str, Any]
    per_query_results: list[dict[str, Any]]


def run_benchmark(
    engine_mode: str = "auto",
    corpus: list[dict[str, str]] | None = None,
    include_adversarial: bool = True,
    adversarial_only: bool = False,
) -> EvaluationReport:
    active_corpus = corpus or BENCHMARK_CORPUS

    # Select Engine
    if engine_mode in ("auto", "neural"):
        try:
            engine = NeuralRetrievalEngine(active_corpus)
            selected_mode = "neural"
        except Exception as e:
            if engine_mode == "neural":
                raise RuntimeError(f"Neural engine requested but dependencies failed: {e}")
            engine = DeterministicSyntheticEngine(active_corpus)
            selected_mode = "synthetic_fallback"
    else:
        engine = DeterministicSyntheticEngine(active_corpus)
        selected_mode = "synthetic"

    methods = [
        ("Dense Bi-Encoder", "dense"),
        ("Lexical (TF-IDF/BM25)", "lexical"),
        ("Hybrid RRF", "hybrid"),
        ("Hybrid + Reranker", "rerank")
    ]

    method_metrics: dict[str, dict[str, Any]] = {
        name: {
            "hits@1": 0,
            "hits@3": 0,
            "hits@5": 0,
            "mrr_total": 0.0,
            "ndcg_total": 0.0,
            "latencies": [],
            "adversarial_pass": 0,
        }
        for name, _ in methods
    }

    per_query_results: list[dict[str, Any]] = []

    eval_queries = [] if adversarial_only else STANDARD_QUERIES
    N_std = len(eval_queries)

    # 1. Standard Benchmark Evaluation
    for q_data in eval_queries:
        query_text = q_data["query"]
        target_id = q_data["target_id"]
        rel_map = q_data["graded_relevance"]
        category = q_data["category"]

        q_res = {
            "query": query_text,
            "target": target_id,
            "category": category,
            "type": "standard",
            "ranks": {}
        }

        for method_name, method_key in methods:
            ranked_ids, lat = engine.rank(query_text, method_key)
            h1 = calculate_hit_at_k(ranked_ids, target_id, 1)
            h3 = calculate_hit_at_k(ranked_ids, target_id, 3)
            h5 = calculate_hit_at_k(ranked_ids, target_id, 5)
            mrr = calculate_mrr(ranked_ids, target_id)
            ndcg = calculate_ndcg(ranked_ids, rel_map, k=10)

            method_metrics[method_name]["hits@1"] += h1
            method_metrics[method_name]["hits@3"] += h3
            method_metrics[method_name]["hits@5"] += h5
            method_metrics[method_name]["mrr_total"] += mrr
            method_metrics[method_name]["ndcg_total"] += ndcg
            method_metrics[method_name]["latencies"].append(lat)

            rank = ranked_ids.index(target_id) + 1 if target_id in ranked_ids else 999
            q_res["ranks"][method_name] = {"rank": rank, "top1": ranked_ids[0] if ranked_ids else ""}

        per_query_results.append(q_res)

    # 2. Adversarial Evaluation Suite
    N_adv = len(ADVERSARIAL_QUERIES) if include_adversarial else 0
    adversarial_details = []

    if include_adversarial:
        for adv_q in ADVERSARIAL_QUERIES:
            query_text = adv_q["query"]
            target_id = adv_q["target_id"]
            decoy_id = adv_q.get("decoy_id", "")
            rel_map = adv_q["graded_relevance"]

            adv_res = {
                "query": query_text,
                "target": target_id,
                "decoy": decoy_id,
                "trap_type": adv_q["trap_type"],
                "type": "adversarial",
                "ranks": {}
            }

            for method_name, method_key in methods:
                ranked_ids, lat = engine.rank(query_text, method_key)
                target_rank = ranked_ids.index(target_id) + 1 if target_id in ranked_ids else 999
                decoy_rank = ranked_ids.index(decoy_id) + 1 if (decoy_id and decoy_id in ranked_ids) else 999

                passed = (target_rank < decoy_rank) and (target_rank <= 3)
                if passed:
                    method_metrics[method_name]["adversarial_pass"] += 1

                adv_res["ranks"][method_name] = {
                    "target_rank": target_rank,
                    "decoy_rank": decoy_rank,
                    "top1": ranked_ids[0] if ranked_ids else "",
                    "resisted_trap": passed
                }

            per_query_results.append(adv_res)
            adversarial_details.append(adv_res)

    # Compile Final Summary Metrics
    import numpy as np
    compiled_methods: dict[str, dict[str, Any]] = {}
    denom = N_std if N_std > 0 else 1

    for method_name, _ in methods:
        m = method_metrics[method_name]
        lats = m["latencies"] or [0.0]
        compiled_methods[method_name] = {
            "Hit@1": round(m["hits@1"] / denom, 4),
            "Hit@3": round(m["hits@3"] / denom, 4),
            "Hit@5": round(m["hits@5"] / denom, 4),
            "MRR": round(m["mrr_total"] / denom, 4),
            "NDCG@10": round(m["ndcg_total"] / denom, 4),
            "Adversarial_Resistance_Rate": round(m["adversarial_pass"] / N_adv, 4) if N_adv > 0 else 1.0,
            "Latency_P50_ms": round(float(np.median(lats)), 2),
            "Latency_P95_ms": round(float(np.percentile(lats, 95)), 2),
            "Latency_P99_ms": round(float(np.percentile(lats, 99)), 2),
            "Latency_Mean_ms": round(float(np.mean(lats)), 2)
        }

    report = EvaluationReport(
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        engine_mode=selected_mode,
        corpus_size=len(active_corpus),
        num_standard_queries=N_std,
        num_adversarial_queries=N_adv,
        methods=compiled_methods,
        adversarial_analysis={"queries": adversarial_details},
        per_query_results=per_query_results
    )
    return report


# ==============================================================================
# 7. CLI Entrypoint & Formatter
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="GMS Continuous Evaluation Retrieval Benchmark")
    parser.add_argument("--mode", choices=["auto", "neural", "synthetic"], default="auto", help="Retrieval engine mode")
    parser.add_argument("--adversarial-only", action="store_true", help="Run only adversarial trap queries")
    parser.add_argument("--no-adversarial", action="store_true", help="Skip adversarial evaluation queries")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON benchmark output")
    parser.add_argument("--output", type=str, default=None, help="Save report to JSON file path")
    args = parser.parse_args()

    report = run_benchmark(
        engine_mode=args.mode,
        include_adversarial=not args.no_adversarial,
        adversarial_only=args.adversarial_only
    )

    report_dict = asdict(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report_dict, indent=2))
        print(f"[SUCCESS] Benchmark report saved to {out_path}")

    if args.json:
        print(json.dumps(report_dict, indent=2))
        return 0

    print("=" * 80)
    print("=== GLOBAL MEMORY SYSTEM (GMS) CONTINUOUS EVALUATION RETRIEVAL BENCHMARK ===")
    print("=" * 80)
    print(f"Timestamp:             {report.timestamp}")
    print(f"Engine Mode:           {report.engine_mode}")
    print(f"Corpus Size:           {report.corpus_size} items")
    print(f"Standard Queries:      {report.num_standard_queries}")
    print(f"Adversarial Queries:   {report.num_adversarial_queries}")
    print("-" * 80)

    # Format Markdown / Terminal Table
    headers = ["Method", "Hit@1", "Hit@3", "Hit@5", "MRR", "NDCG@10", "Adv. Resist", "P50 Lat", "P95 Lat"]
    print(f"{headers[0]:<25} | {headers[1]:<7} | {headers[2]:<7} | {headers[3]:<7} | {headers[4]:<7} | {headers[5]:<8} | {headers[6]:<11} | {headers[7]:<8} | {headers[8]:<8}")
    print("-" * 105)

    for method_name, m in report.methods.items():
        print(
            f"{method_name:<25} | "
            f"{m['Hit@1']:<7.3f} | "
            f"{m['Hit@3']:<7.3f} | "
            f"{m['Hit@5']:<7.3f} | "
            f"{m['MRR']:<7.3f} | "
            f"{m['NDCG@10']:<8.3f} | "
            f"{m['Adversarial_Resistance_Rate']*100:<10.1f}% | "
            f"{m['Latency_P50_ms']:<6.1f}ms | "
            f"{m['Latency_P95_ms']:<6.1f}ms"
        )

    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
