"""Application service: validate, prioritize, claim, run graph and record a batch."""

import hashlib
import json
import time
import uuid
from datetime import date
from pathlib import Path

from .agents import PROMPT_VERSION, demo_propose, demo_review
from .config import Settings
from .data import safe_record
from .graph import run_graph
from .local_model import create_agents, model_identity
from .operations import CallBudget, log_event
from .policy import injection_signals, load_policy, retrieve
from .store import AuditStore
from .store import load_events as load_events
from .store import load_results as load_results

PIPELINE_VERSION = "nbim-flow-v2"


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def pipeline_fingerprint():
    # UI, CLI, logging and registry edits do not invalidate vote recommendations.
    root = Path(__file__).parent
    return _digest(
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (
                "workflow.py",
                "graph.py",
                "agents.py",
                "local_model.py",
                "data.py",
                "policy.py",
            )
        }
    )


def _validated(records):
    result = [safe_record(r) for r in records]
    seen = {}
    for record in result:
        try:
            parsed = date.fromisoformat(record["meeting_date"])
            valid = (
                parsed.isoformat() == record["meeting_date"]
                and record["meeting_id"]
                and record["item_no"]
                and record["proposal_text"]
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Ugyldig saksgrunnlag: kjør CSV-filen gjennom preprocessing først.")
        prior = seen.get(record["record_id"])
        if prior is not None and prior != record["evidence_hash"]:
            raise ValueError("Motstridende versjoner av samme sak; kjør preprocessing først.")
        seen[record["record_id"]] = record["evidence_hash"]
    return result


def process_records(
    records,
    db_path=None,
    mode="demo",
    model=None,
    reviewer_model=None,
    max_attempts=None,
    limit=20,
    policy_path=None,
    model_path=None,
    min_confidence=None,
    agents=None,
    settings=None,
    max_api_calls=None,
):
    settings = settings or Settings.from_env()
    db_path = db_path or settings.database_path
    policy_path = policy_path or settings.policy_path
    max_attempts = settings.max_attempts if max_attempts is None else max_attempts
    min_confidence = settings.min_confidence if min_confidence is None else min_confidence
    call_limit = settings.max_api_calls if max_api_calls is None else max_api_calls
    if mode not in ("demo", "llm"):
        raise ValueError("mode må være demo eller llm")
    if (
        not 1 <= max_attempts <= 5
        or not 1 <= limit <= 1000
        or not 0 <= min_confidence <= 1
        or not 1 <= call_limit <= 1000
    ):
        raise ValueError(
            "Ugyldig budsjett: 1–5 forsøk, 1–1000 saker/kall og konfidens mellom 0 og 1."
        )
    if mode == "demo" and agents is not None:
        raise ValueError("Tilpassede agenter krever mode=llm")
    model = model or settings.model
    reviewer_model = reviewer_model or settings.reviewer_model or model
    if mode == "llm" and agents is None:
        if not model or (settings.provider == "openai" and not settings.api_key):
            raise ValueError("Kontroller LLM_MODEL og leverandøroppsettet i .env.")
    records = _validated(records)
    policy = load_policy(policy_path)
    identity = {}
    if mode == "llm" and agents is None and settings.provider == "ollama":
        identity = model_identity(settings, {model, reviewer_model})
    priority, model_hash = {}, None
    if model_path:
        from .model import prioritize
        from .registry import resolve_model

        location = resolve_model(model_path)
        model_hash = hashlib.sha256(location.read_bytes()).hexdigest()
        annotated = prioritize(records, location)
        priority = {
            r["record_id"]: {k: r[k] for k in ("p_mot", "priority", "priority_model_id")}
            for r in annotated
        }
        records.sort(key=lambda r: -priority[r["record_id"]]["p_mot"])
    config = {
        "pipeline_version": PIPELINE_VERSION,
        "code_sha256": pipeline_fingerprint(),
        "policy_sha256": policy["sha256"],
        "policy_version": policy["version"],
        "prompt_version": PROMPT_VERSION,
        "mode": mode,
        "provider": settings.provider if mode == "llm" else "demo",
        "base_url": settings.base_url if mode == "llm" else None,
        "context_tokens": settings.context_tokens,
        "model": model if mode == "llm" else "demo-rules",
        "reviewer_model": reviewer_model if mode == "llm" else "demo-check",
        "priority_model_sha256": model_hash,
        "max_attempts": max_attempts,
        "min_confidence": min_confidence,
        "max_output_tokens": settings.max_output_tokens,
        "reasoning_effort": settings.reasoning_effort,
        "input_limit": settings.max_input_characters,
        "cache_namespace": settings.cache_namespace,
    }
    config["model_identity"] = identity
    decision_config = {
        k: v for k, v in config.items() if k not in ("priority_model_sha256", "max_attempts")
    }
    batch_id = uuid.uuid4().hex
    summary = {
        "batch_id": batch_id,
        "processed": 0,
        "skipped": 0,
        "errors": 0,
        "busy": 0,
        "deferred": 0,
        "api_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "stopped_reason": None,
    }
    budget = CallBudget(call_limit if mode == "llm" else 100000)
    provider = agents
    call_metrics = []
    store = AuditStore(db_path)
    started = time.perf_counter()
    store.start_batch(
        batch_id,
        {
            "config": config,
            "input_count": len(records),
            "limit": limit,
            "input_sha256": _digest(sorted(r["evidence_hash"] for r in records)),
            "sources": sorted({r["source"] for r in records}),
        },
    )
    log_event("batch_started", batch_id=batch_id, mode=mode, input_count=len(records), limit=limit)

    def get_provider():
        nonlocal provider
        if provider is None:
            provider = create_agents(settings, model, reviewer_model)
        return provider

    def propose(record, rules, feedback=""):
        return (
            demo_propose(record, rules, feedback)
            if mode == "demo"
            else get_provider().propose(record, rules, feedback)
        )

    def review(record, rules, candidate):
        return (
            demo_review(record, rules, candidate)
            if mode == "demo"
            else get_provider().review(record, rules, candidate)
        )

    def usage():
        return getattr(provider, "last_usage", {}) if provider else {}

    consecutive_errors = 0
    try:
        for record in records:
            if summary["processed"] + summary["errors"] + summary["deferred"] >= limit:
                break
            key = _digest({"evidence_hash": record["evidence_hash"], "config": decision_config})
            initial = {
                **record,
                "run_key": key,
                "batch_id": batch_id,
                "mode": mode,
                "config": config,
                "vote": "AVSTÅ",
                "status": "processing",
                "needs_human_review": True,
                "attempts": 0,
                "retries": 0,
                "confidence": 0.0,
                "reason": "Behandling pågår",
                "citations": [],
                "priority_metadata": priority.get(record["record_id"], {}),
            }
            claimed, attempts, claim_state = store.claim(key, initial)
            if not claimed:
                summary["skipped"] += 1
                summary["busy"] += claim_state == "busy"
                store.event(
                    key,
                    record["record_id"],
                    attempts,
                    "cache_hit" if claim_state == "cached" else "busy",
                    {"batch_id": batch_id},
                )
                continue
            case_started = time.perf_counter()
            store.event(
                key,
                record["record_id"],
                attempts,
                "case_started",
                {"claim": claim_state, "config": config, "batch_id": batch_id},
            )
            rules = retrieve(record, policy)
            store.event(
                key,
                record["record_id"],
                attempts,
                "policy_retrieved",
                {"ids": [r["id"] for r in rules], "batch_id": batch_id},
            )
            alarm = injection_signals(record["proposal_text"])
            state = {"attempts": attempts, "accepted": False}
            if alarm:
                fallback, reason = (
                    "prompt_injection",
                    "Mulig instruksjonsangrep i dokumentet. Krever manuell vurdering.",
                )
                store.event(
                    key,
                    record["record_id"],
                    attempts,
                    "safety_gate",
                    {"patterns": alarm, "batch_id": batch_id},
                )
            elif len(record["proposal_text"]) > settings.max_input_characters:
                fallback, reason = (
                    "input_too_large",
                    "Forslagsteksten er over tillatt størrelse og må deles eller vurderes manuelt.",
                )
            elif not rules:
                fallback, reason = (
                    "policy_unavailable",
                    "Ingen relevant policy i det verifiserte datovinduet og utvalget. Krever flere kilder.",
                )
            elif attempts >= max_attempts:
                fallback, reason = (
                    "max_attempts",
                    "Saken har brukt opp budsjettet for vurderingsforsøk.",
                )
            else:
                previous_feedback = ""
                if attempts:
                    prior = [e for e in load_events(db_path, key) if e["event"] == "verification"]
                    previous_feedback = prior[-1]["payload"].get("reason", "") if prior else ""
                state = run_graph(
                    record,
                    rules,
                    propose,
                    review,
                    store,
                    key,
                    max_attempts,
                    attempts,
                    min_confidence,
                    usage,
                    budget,
                    batch_id,
                    call_metrics,
                    previous_feedback,
                )
                fallback = (
                    "call_budget"
                    if state.get("error", {}).get("category") == "call_budget"
                    else "provider_error"
                    if state.get("error")
                    else "max_attempts"
                    if state["attempts"] >= max_attempts and not state.get("accepted")
                    else "insufficient_evidence"
                )
                reason = (
                    state.get("error", {}).get("message")
                    or state.get("feedback")
                    or "Saken må vurderes manuelt."
                )
            accepted = state.get("accepted", False)
            candidate, error = state.get("candidate", {}), state.get("error", {})
            status = (
                ("verified" if mode == "llm" else "demo_checked")
                if accepted
                else "deferred"
                if fallback == "call_budget"
                else "error"
                if error
                else "human_review"
            )
            result = dict(
                initial,
                attempts=state["attempts"],
                retries=max(0, state["attempts"] - 1),
                status=status,
                vote=candidate["vote"] if accepted else "AVSTÅ",
                confidence=candidate["confidence"] if accepted else 0.0,
                reason=candidate["reason"] if accepted else reason,
                review_reason=state.get("feedback", reason),
                needs_human_review=not accepted or mode == "demo",
                fallback_type=None if accepted else fallback,
                provider_error=error or None,
                duration_ms=round((time.perf_counter() - case_started) * 1000, 2),
            )
            if accepted:
                by_id = {r["id"]: r for r in rules}
                result["citations"] = [
                    dict(
                        c,
                        source_url=policy["source_url"],
                        locator=by_id[c["policy_id"]]["locator"],
                        kind="curated_paraphrase",
                    )
                    for c in candidate["citations"]
                ]
            store.finish(result)
            counter = "deferred" if status == "deferred" else "errors" if error else "processed"
            summary[counter] += 1
            consecutive_errors = consecutive_errors + 1 if error else 0
            if error.get("stop_batch") or consecutive_errors >= 3:
                summary["stopped_reason"] = (
                    error.get("category") if error.get("stop_batch") else "circuit_breaker"
                )
                break
    except BaseException:
        summary["stopped_reason"] = "interrupted"
        raise
    finally:
        summary["api_calls"] = budget.used if mode == "llm" else 0
        for metric in call_metrics:
            token_usage = metric.get("usage") or {}
            summary["input_tokens"] += token_usage.get("input_tokens", 0)
            summary["output_tokens"] += token_usage.get("output_tokens", 0)
        summary["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        store.finish_batch(
            batch_id, summary, "stopped" if summary["stopped_reason"] else "completed"
        )
        store.close()
        if provider is not None and agents is None:
            provider.close()
        log_event("batch_finished", **summary)
    return summary
