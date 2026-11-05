"""The bounded recommendation/verification graph; persistence is injected."""

import time
from typing import TypedDict

from .agents import validate_decision
from .operations import provider_error


class CaseState(TypedDict, total=False):
    attempts: int
    candidate: dict
    review: dict
    feedback: str
    error: dict
    accepted: bool


def run_graph(
    record,
    rules,
    propose,
    review,
    store,
    key,
    max_attempts,
    previous_attempts,
    min_confidence,
    usage,
    budget,
    batch_id,
    call_metrics,
    previous_feedback="",
):
    from langgraph.graph import END, START, StateGraph

    def event(attempt, kind, payload):
        store.event(key, record["record_id"], attempt, kind, dict(payload, batch_id=batch_id))

    def call(role, attempt, function, *args):
        budget.reserve()
        started = time.perf_counter()
        succeeded = False
        try:
            value = function(*args)
            succeeded = True
            return value
        finally:
            provider = usage()
            call_metrics.append(provider)
            event(
                attempt,
                "model_call",
                {
                    "role": role,
                    "success": succeeded,
                    "provider": provider,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )

    def author(state):
        # No attempt is consumed when there is no budget to start a call.
        if budget.used >= budget.limit:
            from .operations import CallBudgetExceeded

            return {"error": provider_error(CallBudgetExceeded()), "accepted": False}
        attempt = state["attempts"] + 1
        store.start_attempt(key, attempt)
        event(attempt, "attempt_started", {})
        try:
            candidate = call("author", attempt, propose, record, rules, state.get("feedback", ""))
            event(attempt, "recommendation", {"candidate": candidate})
            return {"attempts": attempt, "candidate": candidate, "error": {}}
        except Exception as exc:
            error = provider_error(exc)
            event(attempt, "provider_error", dict(error, role="author"))
            return {"attempts": attempt, "error": error, "accepted": False}

    def verifier(state):
        candidate, attempt = state["candidate"], state["attempts"]
        errors = validate_decision(candidate, record, rules, min_confidence)
        event(attempt, "source_validation", {"errors": errors})
        if errors:
            low = (
                isinstance(candidate, dict)
                and isinstance(candidate.get("confidence"), (int, float))
                and candidate["confidence"] < min_confidence
            )
            checked = {"accepted": False, "retryable": not low, "reason": "; ".join(errors)}
        else:
            try:
                checked = call("reviewer", attempt, review, record, rules, candidate)
                if (
                    not isinstance(checked, dict)
                    or type(checked.get("accepted")) is not bool
                    or type(checked.get("retryable")) is not bool
                    or not isinstance(checked.get("reason"), str)
                    or not checked["reason"].strip()
                ):
                    raise ValueError("Ugyldig kontrollsvar")
            except Exception as exc:
                error = provider_error(exc)
                event(attempt, "provider_error", dict(error, role="reviewer"))
                return {"error": error, "accepted": False}
        event(attempt, "verification", checked)
        return {"review": checked, "accepted": checked["accepted"], "feedback": checked["reason"]}

    def route(state):
        if (
            state.get("error")
            or state.get("accepted")
            or state["attempts"] >= max_attempts
            or not state.get("review", {}).get("retryable", False)
        ):
            return END
        return "recommend"

    graph = StateGraph(CaseState)
    graph.add_node("recommend", author)
    graph.add_node("verify", verifier)
    graph.add_edge(START, "recommend")
    graph.add_conditional_edges(
        "recommend", lambda s: END if s.get("error") else "verify", {END: END, "verify": "verify"}
    )
    graph.add_conditional_edges("verify", route, {END: END, "recommend": "recommend"})
    return graph.compile().invoke(
        {"attempts": previous_attempts, "feedback": previous_feedback, "accepted": False},
        {"recursion_limit": max_attempts * 3 + 5},
    )
