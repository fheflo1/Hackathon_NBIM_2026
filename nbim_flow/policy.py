"""Versioned, dated lexical retrieval over a small, explicit policy corpus."""

import hashlib
import json
import re
from datetime import date
from pathlib import Path


def load_policy(path="policies/nbim_2025.json"):
    raw = Path(path).read_bytes()
    policy = json.loads(raw)
    date.fromisoformat(policy["valid_from"])
    date.fromisoformat(policy["valid_through"])
    ids = [r["id"] for r in policy["rules"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Policy-ID-er må være unike")
    policy["sha256"] = hashlib.sha256(raw).hexdigest()
    return policy


def retrieve(record, policy, top_k=3):
    """No later-year policy is silently applied to earlier meetings."""
    meeting_date = record["meeting_date"]
    if not policy["valid_from"] <= meeting_date <= policy["valid_through"]:
        return []
    tokens = set(re.findall(r"\w+", record["proposal_text"].casefold()))
    ranked = [(len(tokens.intersection(r["keywords"])), r) for r in policy["rules"]]
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [dict(rule, source_url=policy["source_url"], kind="curated_paraphrase")
            for score, rule in ranked[:top_k] if score > 0]


def injection_signals(text):
    """A small alarm list, not a complete prompt-injection defence."""
    patterns = [
        r"ignore\s+(?:all\s+)?(?:(?:previous|prior|the|nbim|voting)\s+)*(?:instructions|rules|guidelines|policy)",
        r"disregard\s+(?:the\s+)?(?:policy|instructions|guidelines)",
        r"ignorer\s+(?:alle\s+)?(?:tidligere\s+)?(?:instruksjoner|retningslinj|regler)",
        r"(?:system|assistant|developer)\s*:",
        r"<\|(?:im_start|system)",
    ]
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]
