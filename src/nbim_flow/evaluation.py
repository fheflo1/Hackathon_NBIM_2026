"""Evaluate selected, stored workflow outcomes against separate historical labels.

This is a descriptive audit of the selected cohort. It is not a chronological
held-out evaluation, an audit of rationale correctness, or a claim about the
performance of the full pipeline on unprocessed cases.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from .data import normalize_vote

VOTES = ("FOR", "MOT", "AVSTÅ")
_FINISHED = {"verified", "demo_checked", "human_review", "error"}


def _updated(result: dict[str, Any]) -> tuple[float, str]:
    try:
        stamp = datetime.fromisoformat(str(result.get("updated_at", "")).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        updated = stamp.timestamp()
    except (ValueError, TypeError, OverflowError):
        updated = float("-inf")
    return updated, str(result.get("run_key", ""))


def _metrics(actual: list[str], predicted: list[str]) -> dict[str, Any]:
    matrix = [[0 for _ in VOTES] for _ in VOTES]
    for truth, prediction in zip(actual, predicted):
        matrix[VOTES.index(truth)][VOTES.index(prediction)] += 1
    tp = sum(a == "MOT" and p == "MOT" for a, p in zip(actual, predicted))
    fp = sum(a != "MOT" and p == "MOT" for a, p in zip(actual, predicted))
    fn = sum(a == "MOT" and p != "MOT" for a, p in zip(actual, predicted))
    tn = len(actual) - tp - fp - fn
    return {
        "count": len(actual),
        "accuracy": sum(a == p for a, p in zip(actual, predicted)) / len(actual)
        if actual
        else None,
        "mot_precision": tp / (tp + fp) if tp + fp else None,
        "mot_recall": tp / (tp + fn) if tp + fn else None,
        "mot_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "mot_support": tp + fn,
        "class_counts": {vote: actual.count(vote) for vote in VOTES},
        "mot_confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "confusion_matrix": {"labels": list(VOTES), "rows_actual_columns_predicted": matrix},
    }


def evaluate_results(
    records: Iterable[dict[str, Any]],
    labels: Iterable[dict[str, Any]],
    results: Iterable[dict[str, Any]],
    mode: str = "llm",
) -> dict[str, Any]:
    """Join current evidence and historical labels to latest stored outcomes.

    Matching requires record_id AND evidence_hash AND the explicitly selected
    execution mode. Source is already part of prepared record_id. Results for
    an earlier evidence revision or a different mode never contribute metrics.
    Unknown historical labels are excluded, rather than treated as negatives.
    API-error fallbacks are included as workflow dispositions; pending records
    are not processed outcomes. Policy/model versions may differ in the cohort.
    """
    if mode not in {"llm", "demo"}:
        raise ValueError("mode må være llm eller demo")
    current: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id, evidence_hash = record.get("record_id"), record.get("evidence_hash")
        if not record_id or not evidence_hash:
            raise ValueError(
                "Evaluering krever ferdigbehandlede saksdata med record_id og evidence_hash"
            )
        if record_id in current and current[record_id]["evidence_hash"] != evidence_hash:
            raise ValueError(
                "Samme record_id har flere inputversjoner; velg ett aktuelt saksgrunnlag"
            )
        current[record_id] = record

    actual_by_id: dict[str, str | None] = {}
    for label in labels:
        record_id = label.get("record_id")
        if record_id not in current:
            continue
        vote = normalize_vote(label.get("vote_label"))
        if record_id in actual_by_id and actual_by_id[record_id] != vote:
            raise ValueError("Motstridende historiske etiketter for samme record_id")
        actual_by_id[record_id] = vote

    latest: dict[str, dict[str, Any]] = {}
    for result in results:
        record_id = result.get("record_id")
        record = current.get(record_id)
        if (
            record is None
            or result.get("mode") != mode
            or result.get("evidence_hash") != record["evidence_hash"]
        ):
            continue
        # Source comparison adds a guard against malformed externally supplied
        # result records; normally the source-specific hash already isolates it.
        if result.get("source") and record.get("source") and result["source"] != record["source"]:
            continue
        if record_id not in latest or _updated(result) > _updated(latest[record_id]):
            latest[record_id] = result

    processed = {
        record_id: result
        for record_id, result in latest.items()
        if result.get("status") in _FINISHED and normalize_vote(result.get("vote")) in VOTES
    }
    evaluated = [record_id for record_id in processed if actual_by_id.get(record_id) in VOTES]
    actual = [actual_by_id[record_id] for record_id in evaluated]
    predicted = [normalize_vote(processed[record_id]["vote"]) for record_id in evaluated]
    board_cohort = [
        record_id
        for record_id in evaluated
        if normalize_vote(current[record_id].get("mgmt_rec")) in VOTES
    ]
    board_actual = [actual_by_id[record_id] for record_id in board_cohort]
    board_predicted = [normalize_vote(current[record_id]["mgmt_rec"]) for record_id in board_cohort]
    comparable_predicted = [
        normalize_vote(processed[record_id]["vote"]) for record_id in board_cohort
    ]
    known_input = sum(vote in VOTES for vote in actual_by_id.values())
    sources = sorted({str(record.get("source", "unknown")) for record in current.values()})
    policy_versions = sorted(
        {
            str(result.get("config", {}).get("policy_version", "unknown"))
            for result in processed.values()
        }
    )
    verified = [
        record_id
        for record_id in evaluated
        if mode == "llm" and processed[record_id].get("status") == "verified"
    ]
    verified_count = sum(
        mode == "llm" and result.get("status") == "verified" for result in processed.values()
    )
    evaluated_ids = set(evaluated)
    configurations: dict[str, dict[str, Any]] = {}
    for record_id, result in latest.items():
        config = result.get("config") or {}
        config_sha = hashlib.sha256(
            json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        summary = configurations.setdefault(
            config_sha,
            {
                "configuration_sha256": config_sha,
                "config": config,
                "selected_result_count": 0,
                "processed_count": 0,
                "known_label_evaluated_count": 0,
            },
        )
        summary["selected_result_count"] += 1
        summary["processed_count"] += record_id in processed
        summary["known_label_evaluated_count"] += record_id in evaluated_ids
    return {
        "mode": mode,
        "evaluation_kind": "stored_llm_outcomes" if mode == "llm" else "deterministic_demo_only",
        "cohort": "selected_current_input_and_latest_matching_stored_results",
        "is_chronological_heldout_evaluation": False,
        "sources": sources,
        "policy_versions": policy_versions,
        "configuration_count": len(configurations),
        "configuration_summaries": [configurations[key] for key in sorted(configurations)],
        "mixed_configuration_warning": (
            "The selected stored results use multiple configurations; aggregate metrics mix policy, prompt and/or model settings."
            if len(configurations) > 1
            else None
        ),
        "available_input_count": len(current),
        "available_known_label_count": known_input,
        "selected_result_count": len(latest),
        "processed_count": len(processed),
        "pending_count": sum(result.get("status") == "processing" for result in latest.values()),
        "invalid_outcome_count": sum(
            result.get("status") in _FINISHED and normalize_vote(result.get("vote")) not in VOTES
            for result in latest.values()
        ),
        "known_label_evaluated_count": len(evaluated),
        "unknown_label_processed_count": len(processed) - len(evaluated),
        "coverage": len(processed) / len(current) if current else 0.0,
        "known_label_coverage": len(evaluated) / known_input if known_input else None,
        "verified_count": verified_count,
        "verified_coverage": verified_count / len(current) if current else 0.0,
        "verified_known_label_coverage": len(verified) / known_input if known_input else None,
        "demo_checked_count": sum(
            result.get("status") == "demo_checked" for result in processed.values()
        ),
        "needs_human_count": sum(
            bool(result.get("needs_human_review")) for result in processed.values()
        ),
        "fallback_abstentions": sum(
            normalize_vote(result.get("vote")) == "AVSTÅ" and bool(result.get("fallback_type"))
            for result in processed.values()
        ),
        "status_counts": dict(Counter(result.get("status") for result in processed.values())),
        "metrics": _metrics(actual, predicted),
        "verified_only_metrics": _metrics(
            [actual_by_id[rid] for rid in verified],
            [normalize_vote(processed[rid]["vote"]) for rid in verified],
        ),
        "board_baseline": _metrics(board_actual, board_predicted),
        "agent_on_board_available_subset": _metrics(board_actual, comparable_predicted),
        "board_missing_count": len(evaluated) - len(board_cohort),
        "notes": [
            "This cohort consists of selected current inputs and stored outcomes; it is not a full chronological held-out test.",
            "Unknown or absent historical labels are excluded from metrics, including true-negative counts.",
            "Workflow metrics include fallback abstentions and API-error dispositions, not pending processing records.",
            "A fallback AVSTÅ is a technical disposition requiring review, not a policy-justified abstention.",
            "Board and comparable-agent metrics use exactly the same known-label cohort with available management recommendations.",
            "Verified-only metrics describe a selected subset and cannot establish coverage or safety on other cases.",
            "Vote agreement does not measure factual correctness, citation quality or compliance with the full NBIM policy.",
            "MOT precision, recall and F1 are null when their denominator is zero.",
            (
                "Demo outcomes come from local deterministic rules; this is not a live agent evaluation."
                if mode == "demo"
                else "Stored LLM runs may use different policy/model versions; inspect audit metadata for comparability."
            ),
        ],
    }
