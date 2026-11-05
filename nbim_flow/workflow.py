"""Bounded LangGraph recommendation/review loop with evidence-based caching."""

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import TypedDict

from .agents import LLMAgents, PROMPT_VERSION, demo_propose, demo_review, validate_decision
from .data import safe_record
from .policy import injection_signals, load_policy, retrieve
from .store import AuditStore, load_events, load_results

PIPELINE_VERSION = "nbim-flow-v1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def pipeline_fingerprint():
    """Include source/prompt changes, not just a manually maintained version."""
    root = Path(__file__).parent
    return _digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(root.glob("*.py"))})


class CaseState(TypedDict, total=False):
    attempts: int
    candidate: dict
    review: dict
    feedback: str
    error: str
    accepted: bool


def _run_graph(record, rules, propose, review, store, key, max_attempts, previous_attempts,
               min_confidence, usage):
    from langgraph.graph import END, START, StateGraph

    def author(state):
        attempt = state["attempts"] + 1
        store.start_attempt(key, attempt)
        store.event(key, record["record_id"], attempt, "attempt_started", {})
        try:
            candidate = propose(record, rules, state.get("feedback", ""))
            store.event(key, record["record_id"], attempt, "recommendation",
                        {"candidate": candidate, "provider": usage()})
            return {"attempts": attempt, "candidate": candidate, "error": ""}
        except Exception as exc:
            # Exception messages can contain request details. Audit type, not keys/payloads.
            error = type(exc).__name__
            store.event(key, record["record_id"], attempt, "provider_error", {"role": "author", "type": error})
            return {"attempts": attempt, "error": error, "accepted": False}

    def verifier(state):
        candidate, attempt = state["candidate"], state["attempts"]
        errors = validate_decision(candidate, record, rules, min_confidence)
        store.event(key, record["record_id"], attempt, "source_validation", {"errors": errors})
        if errors:
            # Missing facts cannot be created by another pass through the same prompt.
            low_confidence = isinstance(candidate, dict) and isinstance(candidate.get("confidence"), (int, float)) and candidate["confidence"] < min_confidence
            checked = {"accepted": False, "retryable": not low_confidence, "reason": "; ".join(errors)}
        else:
            try:
                checked = review(record, rules, candidate)
                if (not isinstance(checked, dict) or type(checked.get("accepted")) is not bool
                        or type(checked.get("retryable")) is not bool
                        or not isinstance(checked.get("reason"), str) or not checked["reason"].strip()):
                    raise ValueError("Ugyldig kontrollsvar")
                store.event(key, record["record_id"], attempt, "reviewer_usage", usage())
            except Exception as exc:
                error = type(exc).__name__
                store.event(key, record["record_id"], attempt, "provider_error", {"role": "reviewer", "type": error})
                return {"error": error, "accepted": False}
        store.event(key, record["record_id"], attempt, "verification", checked)
        return {"review": checked, "accepted": checked["accepted"], "feedback": checked["reason"]}

    def route(state):
        if (state.get("error") or state.get("accepted") or state["attempts"] >= max_attempts
                or not state.get("review", {}).get("retryable", False)):
            return END
        return "recommend"

    graph = StateGraph(CaseState)
    graph.add_node("recommend", author)
    graph.add_node("verify", verifier)
    graph.add_edge(START, "recommend")
    graph.add_conditional_edges("recommend", lambda s: END if s.get("error") else "verify", {END: END, "verify": "verify"})
    graph.add_conditional_edges("verify", route, {END: END, "recommend": "recommend"})
    return graph.compile().invoke({"attempts": previous_attempts, "feedback": "", "accepted": False},
                                  {"recursion_limit": max_attempts * 3 + 5})


def process_records(records, db_path="artifacts/audit.sqlite", mode="demo", model=None,
                    reviewer_model=None, max_attempts=5, limit=20,
                    policy_path="policies/nbim_2025.json", model_path=None,
                    min_confidence=0.8, agents=None):
    """Process at most `limit` NEW cases; cached cases do not consume the batch.

    ``agents`` supports deterministic fake providers in integration tests. The
    public CLI only permits demo or real, explicitly selected API execution.
    """
    if mode not in ("demo", "llm"):
        raise ValueError("mode må være demo eller llm")
    if not 1 <= max_attempts <= 5 or limit < 1 or not 0 <= min_confidence <= 1:
        raise ValueError("Krever 1–5 totale forsøk, positiv batchgrense og konfidens mellom 0 og 1")
    policy = load_policy(policy_path)
    model = model or os.getenv("OPENAI_MODEL", "")
    reviewer_model = reviewer_model or os.getenv("OPENAI_REVIEWER_MODEL") or model
    if mode == "llm" and agents is None and (not os.getenv("OPENAI_API_KEY") or not model):
        raise ValueError("LLM-kjøring krever OPENAI_API_KEY og OPENAI_MODEL")
    if mode == "demo" and agents is not None:
        raise ValueError("Tilpassede agenter krever mode=llm")
    provider = agents or (LLMAgents(model, reviewer_model) if mode == "llm" else None)
    propose = provider.propose if provider else demo_propose
    review = provider.review if provider else demo_review
    usage = lambda: getattr(provider, "last_usage", {}) if provider else {}
    priority = {}
    records = [safe_record(r) for r in records]
    for record in records:
        try:
            parsed = date.fromisoformat(record["meeting_date"])
            valid = (parsed.isoformat() == record["meeting_date"] and record["meeting_id"]
                     and record["item_no"] and record["proposal_text"])
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Ugyldig saksgrunnlag: kjør CSV-filen gjennom preprocessing først")
    model_hash = None
    if model_path:
        from .model import prioritize
        location = Path(model_path)
        location = location / "model.joblib" if location.is_dir() else location
        model_hash = hashlib.sha256(location.read_bytes()).hexdigest()
        annotated = prioritize(records, location)
        priority = {r["record_id"]: {k: r[k] for k in ("p_mot", "priority", "priority_model_id")} for r in annotated}
        records.sort(key=lambda r: -priority[r["record_id"]]["p_mot"])
    config = {"pipeline_version": PIPELINE_VERSION, "code_sha256": pipeline_fingerprint(),
              "policy_sha256": policy["sha256"], "policy_version": policy["version"],
              "prompt_version": PROMPT_VERSION, "mode": mode, "model": model if mode == "llm" else "demo-rules",
              "reviewer_model": reviewer_model if mode == "llm" else "demo-check",
              "priority_model_sha256": model_hash, "max_attempts": max_attempts,
              "min_confidence": min_confidence}
    summary = {"processed": 0, "skipped": 0, "errors": 0, "busy": 0}
    store = AuditStore(db_path)
    try:
        for record in records:
            if summary["processed"] + summary["errors"] >= limit:
                break
            # Queue order and retry-budget controls do not change the reasoning
            # of a completed case, so changing them must not trigger more calls.
            decision_config = {k: v for k, v in config.items()
                               if k not in ("priority_model_sha256", "max_attempts")}
            key = _digest({"evidence_hash": record["evidence_hash"], "config": decision_config})
            initial = {**record, "run_key": key, "mode": mode, "config": config,
                       "vote": "AVSTÅ", "status": "processing", "needs_human_review": True,
                       "attempts": 0, "retries": 0, "confidence": 0.0, "reason": "Behandling pågår",
                       "citations": [], "priority_metadata": priority.get(record["record_id"], {})}
            claimed, attempts, claim_state = store.claim(key, initial)
            if not claimed:
                summary["skipped"] += 1
                summary["busy"] += claim_state == "busy"
                store.event(key, record["record_id"], attempts, "cache_hit" if claim_state == "cached" else "busy", {})
                continue
            store.event(key, record["record_id"], attempts, "case_started", {"claim": claim_state, "config": config})
            rules = retrieve(record, policy)
            store.event(key, record["record_id"], attempts, "policy_retrieved", {"ids": [r["id"] for r in rules]})
            alarm = injection_signals(record["proposal_text"])
            state = {"attempts": attempts, "accepted": False}
            if alarm:
                fallback, reason = "prompt_injection", "Dokumentet inneholder mulige instruksjoner til agenten. Krever manuell vurdering."
                store.event(key, record["record_id"], attempts, "safety_gate", {"patterns": alarm})
            elif not rules:
                fallback, reason = "policy_unavailable", "Ingen relevant policy i det verifiserte datovinduet og utvalget. Krever flere kilder."
            elif attempts >= max_attempts:
                fallback, reason = "max_attempts", "Saken har brukt opp budsjettet for vurderingsforsøk."
            else:
                state = _run_graph(record, rules, propose, review, store, key, max_attempts,
                                   attempts, min_confidence, usage)
                fallback = ("provider_error" if state.get("error") else
                            "max_attempts" if state["attempts"] >= max_attempts and not state.get("accepted")
                            else "insufficient_evidence")
                reason = state.get("feedback") or "API-kallet feilet. Saken er ikke godkjent og kan forsøkes igjen innenfor gjenværende budsjett."
            accepted = state.get("accepted", False)
            candidate = state.get("candidate", {})
            result = dict(initial, attempts=state["attempts"], retries=max(0, state["attempts"] - 1),
                          status=("verified" if mode == "llm" else "demo_checked") if accepted else
                          "error" if state.get("error") else "human_review",
                          vote=candidate["vote"] if accepted else "AVSTÅ",
                          confidence=candidate["confidence"] if accepted else 0.0,
                          reason=candidate["reason"] if accepted else reason,
                          review_reason=state.get("feedback", reason),
                          needs_human_review=not accepted or mode == "demo",
                          fallback_type=None if accepted else fallback)
            if accepted:
                rule_by_id = {r["id"]: r for r in rules}
                result["citations"] = [dict(c, source_url=policy["source_url"],
                                            locator=rule_by_id[c["policy_id"]]["locator"],
                                            kind="curated_paraphrase") for c in candidate["citations"]]
            store.finish(result)
            summary["errors" if state.get("error") else "processed"] += 1
    finally:
        store.close()
        if provider is not None and agents is None:
            provider.close()
    return summary
