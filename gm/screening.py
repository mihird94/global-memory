"""Zero-PyTorch, zero-Presidio privacy screener (Deterministic L1 + Chunked GLiNER ONNX + Sliding MiniLM ONNX)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from .store import parse_frontmatter

SCANNER_VERSION = "1.0.0-v4"

HARD_BLOCK_ENTITIES = frozenset({"SECRET_CREDENTIAL", "ORG_DENYLIST", "INTERNAL_IP", "PROMPT_OVERRIDE"})
PII_ENTITIES = frozenset(
    {
        "PERSON",
        "STREET_ADDRESS",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SSN",
        "CREDIT_CARD",
        "IBAN_CODE",
        "IP_ADDRESS",
        "CUSTOMER_ID",
    }
)
DEFAULT_DENYLIST_TERMS: tuple[str, ...] = (
    "Project Helios",
    "Project Chimera",
    "AcqTarget-Northstar",
)
LOOPBACK_IPS = frozenset({"127.0.0.1", "::1", "0.0.0.0"})
FAMOUS_AUTHORS = frozenset({"martin fowler", "martin fowler's", "robert c. martin", "robert c. martin's", "martin"})

_SECRET_REGEXES: list[tuple[str, re.Pattern[str]]] = [
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GITHUB_PAT", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("OPENAI_OR_OPENROUTER_KEY", re.compile(r"\bsk-(?:or-v1-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{16,}\b")),
    ("PRIVATE_KEY_BLOCK", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    (
        "DB_URI_WITH_PASSWORD",
        re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^:\s/]+:[^@\s]+@[^\s]+"),
    ),
    ("JWT_TOKEN", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b")),
]
_ASSIGN_SECRET_RE = re.compile(
    r"(?i)\b(?:[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)\s*[:=]\s*[\"']([A-Za-z0-9+/=._-]{16,})[\"']"
)
_TAILSCALE_IP_RE = re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")
_RFC1918_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
_OVERRIDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\b(?:SYSTEM[_\s]+OVERRIDE|REVIEWER[_\s]+DIRECTIVE|SAFETY_FILTER_BYPASS|AUDIT_BYPASS|COMPLIANCE_OVERRIDE)\b"),
    re.compile(r"(?i)\bpolicy_override\s*:"),
    re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|preceding)\s+(?:system\s+)?instructions\b"),
    re.compile(r"(?i)\bskip\s+all\s+(?:safety\s+classifiers|privacy\s+checks)\b"),
]

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CUST_RE = re.compile(r"\bCUST-\d{4,10}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b")
_CARD_RE = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
_US_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)[-.\s]?|\b\d{3}[-.\s])\d{3}[-.\s]\d{4}\b")
_INTL_PHONE_RE = re.compile(r"(?<!\w)\+\d{1,3}(?:[-.\s]\d{2,4}){2,4}\b")
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")


@dataclass(frozen=True)
class SpanFinding:
    entity_type: str
    start: int
    end: int
    score: float
    layer: str
    rule: str


@dataclass(frozen=True)
class ScreenResult:
    action: str  # "allow" | "redact_and_review" | "block"
    entity_types: list[str]
    hard_block_rules: list[str]
    p_post_scrub: float
    chunks: int
    latency_ms: float
    scrubbed_body: str
    rules_hash: str
    scanner_version: str


def default_models_dir() -> Path:
    env = os.environ.get("BRAIN_SCREEN_MODELS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".local" / "share" / "brain" / "models").resolve()


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _luhn_ok(raw: str) -> bool:
    digits = [int(c) for c in raw if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    for idx, d in enumerate(reversed(digits)):
        if idx % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    cleaned = re.sub(r"\s+", "", raw).upper()
    if len(cleaned) < 15 or len(cleaned) > 34:
        return False
    rearranged = cleaned[4:] + cleaned[:4]
    num_str = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    rem = 0
    for ch in num_str:
        rem = (rem * 10 + int(ch)) % 97
    return rem == 1


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / np.sum(e)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -25.0, 25.0)))


def _mask_code_spans_preserving_offsets(text: str) -> str:
    """Replace fenced/inline code spans with spaces while preserving character offsets."""
    chars = list(text)
    for m in re.finditer(r"```[\s\S]*?```|`[^`\n]+`", text):
        for idx in range(m.start(), m.end()):
            if chars[idx] != "\n":
                chars[idx] = " "
    return "".join(chars)


class DeterministicScreener:
    """Layer 1: High-precision secrets, internal IPs, denylist, prompt overrides, and checksummed PII."""

    def __init__(self, denylist: tuple[str, ...] = DEFAULT_DENYLIST_TERMS) -> None:
        self.denylist = tuple(t for t in denylist if t and t.strip())
        self._deny_patterns = [(term, re.compile(rf"(?i)\b{re.escape(term)}\b")) for term in self.denylist]

    def scan(self, text: str) -> list[SpanFinding]:
        out: list[SpanFinding] = []
        internal_ranges: list[tuple[int, int]] = []

        for rule, pat in _SECRET_REGEXES:
            for m in pat.finditer(text):
                out.append(SpanFinding("SECRET_CREDENTIAL", m.start(), m.end(), 0.99, "L1", rule))

        for m in _ASSIGN_SECRET_RE.finditer(text):
            if _shannon_entropy(m.group(1)) >= 3.3:
                out.append(SpanFinding("SECRET_CREDENTIAL", m.start(1), m.end(1), 0.99, "L1", "HIGH_ENTROPY_ASSIGNMENT"))

        for term, pat in self._deny_patterns:
            for m in pat.finditer(text):
                out.append(SpanFinding("ORG_DENYLIST", m.start(), m.end(), 0.99, "L1", f"DENYLIST:{term}"))

        for pat in _OVERRIDE_PATTERNS:
            for m in pat.finditer(text):
                out.append(SpanFinding("PROMPT_OVERRIDE", m.start(), m.end(), 0.99, "L1", "PROMPT_OVERRIDE"))

        for rule, pat in (("TAILSCALE_IP", _TAILSCALE_IP_RE), ("RFC1918_PRIVATE_IP", _RFC1918_IP_RE)):
            for m in pat.finditer(text):
                internal_ranges.append((m.start(), m.end()))
                out.append(SpanFinding("INTERNAL_IP", m.start(), m.end(), 0.99, "L1", rule))

        for m in _SSN_RE.finditer(text):
            out.append(SpanFinding("US_SSN", m.start(), m.end(), 0.95, "L1", "US_SSN"))
        for m in _CUST_RE.finditer(text):
            out.append(SpanFinding("CUSTOMER_ID", m.start(), m.end(), 0.95, "L1", "CUSTOMER_ID"))
        for m in _EMAIL_RE.finditer(text):
            out.append(SpanFinding("EMAIL_ADDRESS", m.start(), m.end(), 0.95, "L1", "EMAIL"))
        for m in _IBAN_RE.finditer(text):
            if _iban_ok(m.group(0)):
                out.append(SpanFinding("IBAN_CODE", m.start(), m.end(), 0.95, "L1", "IBAN_MOD97"))
        for m in _CARD_RE.finditer(text):
            if _luhn_ok(m.group(0)):
                out.append(SpanFinding("CREDIT_CARD", m.start(), m.end(), 0.95, "L1", "CREDIT_CARD_LUHN"))
        for pat in (_US_PHONE_RE, _INTL_PHONE_RE):
            for m in pat.finditer(text):
                out.append(SpanFinding("PHONE_NUMBER", m.start(), m.end(), 0.85, "L1", "PHONE"))
        for m in _IPV4_RE.finditer(text):
            ip_str = m.group(0)
            if ip_str in LOOPBACK_IPS:
                continue
            if any(not (m.end() <= rs or m.start() >= re_) for rs, re_ in internal_ranges):
                continue
            out.append(SpanFinding("IP_ADDRESS", m.start(), m.end(), 0.85, "L1", "IPV4"))

        return out


class ChunkedGlinerONNX:
    """Layer 2: 43.7 MiB GLiNER-PII-Edge INT8 ONNX with 220-word chunks and code-span masking."""

    ENT_MAP = {"person": "PERSON", "street address": "STREET_ADDRESS"}

    def __init__(self, model_dir: Path, threshold: float = 0.45, max_words_per_chunk: int = 220) -> None:
        onnx_path = model_dir / "onnx" / "model_quint8.onnx"
        tok_path = model_dir / "tokenizer.json"
        cfg_path = model_dir / "gliner_config.json"
        for req in (onnx_path, tok_path, cfg_path):
            if not req.exists():
                raise FileNotFoundError(f"Missing GLiNER artifact: {req}")

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(str(tok_path))
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.ent_token_id = int(cfg["class_token_index"])
        self.sep_token_id = int(self.tok.token_to_id(cfg["sep_token"]))
        self.cls_id = int(cfg["encoder_config"]["cls_token_id"])
        self.eos_id = int(cfg["encoder_config"]["sep_token_id"])
        self.threshold = threshold
        self.max_words = max_words_per_chunk
        self.gliner_labels = list(self.ENT_MAP.keys())

    def _analyze_chunk(self, orig_text: str, masked_chunk: str, base_offset: int) -> list[SpanFinding]:
        word_matches = list(re.finditer(r"\S+", masked_chunk))
        if not word_matches:
            return []

        ids = [self.cls_id]
        words_mask = [0]
        for lbl in self.gliner_labels:
            ids.append(self.ent_token_id)
            words_mask.append(0)
            for tid in self.tok.encode(lbl, add_special_tokens=False).ids:
                ids.append(tid)
                words_mask.append(0)
        ids.append(self.sep_token_id)
        words_mask.append(0)

        kept: list[re.Match[str]] = []
        for wi, wm in enumerate(word_matches, start=1):
            wids = self.tok.encode(wm.group(0), add_special_tokens=False).ids
            if len(ids) + len(wids) + 1 > 2048:
                break
            kept.append(wm)
            for j, tid in enumerate(wids):
                ids.append(tid)
                words_mask.append(wi if j == 0 else 0)
        ids.append(self.eos_id)
        words_mask.append(0)
        if not kept:
            return []

        logits = self.sess.run(
            None,
            {
                "input_ids": np.array([ids], dtype=np.int64),
                "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
                "words_mask": np.array([words_mask], dtype=np.int64),
                "text_lengths": np.array([[len(kept)]], dtype=np.int64),
            },
        )[0][0]
        probs = _sigmoid(logits)

        results: list[SpanFinding] = []
        for ei, glabel in enumerate(self.gliner_labels):
            ent = self.ENT_MAP[glabel]
            wi = 0
            while wi < len(kept):
                p_start = float(probs[wi, ei, 0])
                p_inside = float(probs[wi, ei, 2])
                if p_start >= self.threshold or p_inside >= self.threshold:
                    st_idx = wi
                    best_p = max(p_start, p_inside)
                    wi += 1
                    while wi < len(kept) and (float(probs[wi, ei, 1]) >= 0.22 or float(probs[wi, ei, 2]) >= self.threshold):
                        best_p = max(best_p, float(probs[wi, ei, 1]), float(probs[wi, ei, 2]))
                        ended = float(probs[wi, ei, 1]) >= 0.22 and float(probs[wi, ei, 2]) < self.threshold
                        wi += 1
                        if ended:
                            break
                    char_st = base_offset + kept[st_idx].start()
                    char_en = base_offset + kept[wi - 1].end()
                    raw_snip = orig_text[char_st:char_en].strip(".,;:()[]{}\"'`")
                    ctx_win = orig_text[max(0, char_st - 18) : min(len(orig_text), char_en + 18)].lower()
                    if ent == "PERSON" and (raw_snip.lower() in FAMOUS_AUTHORS or any(a in ctx_win for a in FAMOUS_AUTHORS)):
                        continue
                    results.append(SpanFinding(ent, char_st, char_en, round(best_p, 4), "L2", f"GLINER:{glabel}"))
                else:
                    wi += 1
        return results

    def scan(self, text: str) -> list[SpanFinding]:
        masked_full = _mask_code_spans_preserving_offsets(text)
        word_matches = list(re.finditer(r"\S+", masked_full))
        if not word_matches:
            return []
        if len(word_matches) <= self.max_words:
            return self._analyze_chunk(text, masked_full, 0)

        results: list[SpanFinding] = []
        for idx in range(0, len(word_matches), self.max_words):
            win = word_matches[idx : idx + self.max_words]
            ch_st, ch_en = win[0].start(), win[-1].end()
            sub_slice = masked_full[ch_st:ch_en]
            if sub_slice.strip():
                results.extend(self._analyze_chunk(text, sub_slice, ch_st))
        return results


class SlidingMiniLMGateONNX:
    """Layer 3: 22.0 MiB distilled_minilm_bert_v4 INT8 ONNX with mini-batched sliding windows."""

    def __init__(self, model_dir: Path, stride: int = 128, batch_size: int = 8) -> None:
        onnx_path = model_dir / "model_int8.onnx"
        tok_path = model_dir / "tokenizer.json"
        meta_path = model_dir / "meta.json"
        for req in (onnx_path, tok_path, meta_path):
            if not req.exists():
                raise FileNotFoundError(f"Missing MiniLM artifact: {req}")

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.max_len = int(meta["max_length"])
        self.window = self.max_len - 2
        self.stride = stride
        self.batch_size = batch_size

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(str(tok_path))
        self.tok.no_truncation()
        self.cls_id = int(self.tok.token_to_id("[CLS]"))
        self.sep_id = int(self.tok.token_to_id("[SEP]"))
        self.pad_id = int(self.tok.token_to_id("[PAD]") or 0)

    def predict_prob(self, text: str) -> tuple[float, int]:
        ids = self.tok.encode(text, add_special_tokens=False).ids
        if len(ids) <= self.window:
            seq = [self.cls_id] + ids + [self.sep_id]
            logits = self.sess.run(
                None,
                {"input_ids": np.array([seq], dtype=np.int64), "attention_mask": np.ones((1, len(seq)), dtype=np.int64)},
            )[0][0]
            return float(_softmax(logits)[1]), 1

        starts = list(range(0, max(1, len(ids) - self.window + 1), self.stride))
        if starts[-1] + self.window < len(ids):
            starts.append(len(ids) - self.window)
        seqs = [[self.cls_id] + ids[st : st + self.window] + [self.sep_id] for st in starts]

        max_prob = 0.0
        for b in range(0, len(seqs), self.batch_size):
            batch_seqs = seqs[b : b + self.batch_size]
            max_seq_len = max(len(s) for s in batch_seqs)
            b_ids = np.full((len(batch_seqs), max_seq_len), self.pad_id, dtype=np.int64)
            b_mask = np.zeros((len(batch_seqs), max_seq_len), dtype=np.int64)
            for i, seq in enumerate(batch_seqs):
                b_ids[i, : len(seq)] = seq
                b_mask[i, : len(seq)] = 1
            logits_b = self.sess.run(None, {"input_ids": b_ids, "attention_mask": b_mask})[0]
            for row in logits_b:
                p = float(_softmax(row)[1])
                if p > max_prob:
                    max_prob = p
        return max_prob, len(seqs)


def _apply_pii_scrubbing(text: str, findings: list[SpanFinding]) -> tuple[str, list[SpanFinding]]:
    """Resolve overlapping spans (preferring hard blocks, then longest PII span) and redact PII."""
    ordered = sorted(
        findings,
        key=lambda f: (
            0 if f.entity_type in HARD_BLOCK_ENTITIES else 1,
            -(f.end - f.start),
            -f.score,
            f.start,
        ),
    )
    accepted: list[SpanFinding] = []
    for cand in ordered:
        if any(not (cand.end <= ex.start or cand.start >= ex.end) for ex in accepted):
            continue
        accepted.append(cand)
    accepted.sort(key=lambda f: f.start)

    out: list[str] = []
    cursor = 0
    for f in accepted:
        if f.entity_type in HARD_BLOCK_ENTITIES:
            continue
        out.append(text[cursor : f.start])
        out.append(f"<{f.entity_type}>")
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out), accepted


class PrivacyScreener:
    """Production local screener combining Deterministic L1, Chunked GLiNER ONNX, and Sliding MiniLM v4 ONNX."""

    def __init__(
        self,
        *,
        models_dir: Path | None = None,
        threshold: float = 0.50,
        extra_denylist: tuple[str, ...] = (),
        strict: bool = True,
        deterministic_only: bool = False,
    ) -> None:
        self.models_dir = (models_dir or default_models_dir()).resolve()
        self.threshold = float(threshold)
        denylist = tuple(dict.fromkeys([*DEFAULT_DENYLIST_TERMS, *(t.strip() for t in extra_denylist if t.strip())]))
        self.det = DeterministicScreener(denylist=denylist)
        self.strict = strict
        self.deterministic_only = deterministic_only
        self.gliner: ChunkedGlinerONNX | None = None
        self.minilm: SlidingMiniLMGateONNX | None = None

        if not deterministic_only:
            gliner_dir = self.models_dir / "gliner-pii-edge"
            minilm_dir = self.models_dir / "distilled_minilm_bert_v4"
            if strict and (not gliner_dir.exists() or not minilm_dir.exists()):
                raise RuntimeError(
                    f"Required local ONNX screening models missing in {self.models_dir} "
                    "(expected gliner-pii-edge and distilled_minilm_bert_v4). Refusing fail-open scan."
                )
            if gliner_dir.exists() and minilm_dir.exists():
                self.gliner = ChunkedGlinerONNX(gliner_dir, threshold=0.45, max_words_per_chunk=220)
                self.minilm = SlidingMiniLMGateONNX(minilm_dir, stride=128, batch_size=8)

        self.rules_hash = hashlib.sha256(
            json.dumps(
                {
                    "version": SCANNER_VERSION,
                    "threshold": self.threshold,
                    "denylist": list(denylist),
                    "onnx": not deterministic_only,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]

    def deterministic_rescan(self, text: str) -> list[SpanFinding]:
        """Post-redaction fail-closed L1 check for any remaining hard-block patterns."""
        return [f for f in self.det.scan(text) if f.entity_type in HARD_BLOCK_ENTITIES]

    def screen_markdown(self, raw_markdown: str, *, strip_frontmatter: bool = True) -> ScreenResult:
        t0 = time.perf_counter()
        text = parse_frontmatter(raw_markdown)[1] if strip_frontmatter else raw_markdown
        text = text.strip()
        if not text:
            return ScreenResult("allow", [], [], 0.0, 1, 0.0, "", self.rules_hash, SCANNER_VERSION)

        findings: list[SpanFinding] = self.det.scan(text)
        if self.gliner is not None:
            findings.extend(self.gliner.scan(text))

        scrubbed_body, resolved = _apply_pii_scrubbing(text, findings)

        p_post = 0.0
        chunks = 1
        if self.minilm is not None:
            p_post, chunks = self.minilm.predict_prob(scrubbed_body)

        hard_blocks = [f for f in resolved if f.entity_type in HARD_BLOCK_ENTITIES]
        pii_hits = [f for f in resolved if f.entity_type not in HARD_BLOCK_ENTITIES]

        if hard_blocks or p_post >= self.threshold:
            action = "block"
        elif pii_hits:
            action = "redact_and_review"
        else:
            action = "allow"

        return ScreenResult(
            action=action,
            entity_types=sorted({f.entity_type for f in resolved}),
            hard_block_rules=sorted({f.rule for f in hard_blocks}),
            p_post_scrub=round(p_post, 4),
            chunks=chunks,
            latency_ms=round((time.perf_counter() - t0) * 1000.0, 1),
            scrubbed_body=scrubbed_body,
            rules_hash=self.rules_hash,
            scanner_version=SCANNER_VERSION,
        )
