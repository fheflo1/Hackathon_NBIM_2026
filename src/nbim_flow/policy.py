"""Versioned, dated lexical retrieval over a small, explicit policy corpus."""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from .config import Settings


def _require(condition):
    if not condition:
        raise ValueError("Ugyldig policystruktur")


def load_policy(path=None):
    path = path or Settings.from_env().policy_path
    raw = Path(path).read_bytes()
    policy = json.loads(raw)
    try:
        start = date.fromisoformat(policy["valid_from"])
        end = date.fromisoformat(policy["valid_through"])
        _require(
            start <= end
            and start.isoformat() == policy["valid_from"]
            and end.isoformat() == policy["valid_through"]
        )
        _require(all(isinstance(policy[k], str) and policy[k] for k in ("version", "source_url")))
        _require(isinstance(policy["rules"], list) and policy["rules"])
        for rule in policy["rules"]:
            _require(
                all(isinstance(rule[k], str) and rule[k].strip() for k in ("id", "text", "locator"))
            )
            _require(
                isinstance(rule["keywords"], list)
                and all(isinstance(k, str) for k in rule["keywords"])
            )
            for pattern in rule.get("demo_patterns", []):
                re.compile(pattern["pattern"])
                _require(pattern["vote"] in ("FOR", "MOT", "AVSTÅ"))
    except (KeyError, TypeError, ValueError, re.error):
        raise ValueError(
            "Ugyldig policyfil: kontroller metadata, datovindu, regler og mønstre."
        ) from None
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
    return [
        dict(rule, source_url=policy["source_url"], kind="curated_paraphrase")
        for score, rule in ranked[:top_k]
        if score > 0
    ]


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
