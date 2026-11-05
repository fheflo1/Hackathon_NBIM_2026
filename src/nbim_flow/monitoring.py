"""Descriptive operations and input-shift checks, not claimed model-quality drift."""

import math
from collections import Counter

from .store import load_batches, load_results


def input_shift(records, reference, min_sample=30):
    if not records or len(records) < min_sample or not reference or not reference.get("topics"):
        return {"measured": False, "reason": "Trenger referanseprofil og minst 30 saker."}
    current = Counter(r.get("topic", "unknown") for r in records)
    baseline = reference["topics"]
    total_old, total_new = sum(baseline.values()), sum(current.values())
    if not total_old:
        return {"measured": False, "reason": "Tom referanseprofil."}
    distance = (
        sum(
            abs(current.get(k, 0) / total_new - baseline.get(k, 0) / total_old)
            for k in set(current) | set(baseline)
        )
        / 2
    )
    return {
        "measured": True,
        "topic_total_variation": distance,
        "warning": distance > 0.25,
        "current_count": len(records),
        "current_topics": dict(current),
        "note": "Beskrivende endring i temafordeling; beviser ikke forverret modellkvalitet.",
    }


def operational_snapshot(db_path, mode="llm"):
    results = [r for r in load_results(db_path, latest=True) if r.get("mode") == mode]
    batches = [
        b for b in load_batches(db_path) if b["metadata"].get("config", {}).get("mode") == mode
    ]
    completed = [b["summary"] for b in batches if b.get("summary")]
    durations = sorted(
        r["duration_ms"] for r in results if isinstance(r.get("duration_ms"), (int, float))
    )
    statuses = dict(Counter(r["status"] for r in results))
    p95 = durations[max(0, math.ceil(len(durations) * 0.95) - 1)] if durations else None
    alerts = []
    if any(b.get("summary", {}).get("stopped_reason") for b in batches[:1] if b.get("summary")):
        alerts.append(
            {
                "level": "warning",
                "message": "Siste batch ble stoppet. Se årsak og gjenværende saker før ny kjøring.",
            }
        )
    if statuses.get("error", 0):
        alerts.append(
            {
                "level": "warning",
                "message": f"{statuses['error']} saker har API- eller svarfeil og er ikke godkjent.",
            }
        )
    policy_gaps = sum(r.get("fallback_type") == "policy_unavailable" for r in results)
    if policy_gaps:
        alerts.append(
            {
                "level": "info",
                "message": f"{policy_gaps} saker mangler dekkende policy. Flere agentforsøk løser ikke dette.",
            }
        )
    return {
        "mode": mode,
        "current_case_count": len(results),
        "status_counts": statuses,
        "human_review_pending": sum(bool(r.get("review_pending")) for r in results),
        "human_reviewed": sum(bool(r.get("human_review")) for r in results),
        "case_p95_duration_ms": p95,
        "batches_in_window": len(batches),
        "api_calls": sum(s.get("api_calls", 0) for s in completed),
        "input_tokens": sum(s.get("input_tokens", 0) for s in completed),
        "output_tokens": sum(s.get("output_tokens", 0) for s in completed),
        "cache_hits": sum(s.get("skipped", 0) - s.get("busy", 0) for s in completed),
        "alerts": alerts,
        "recent_batches": batches,
        "note": "Saksoversikt viser siste versjon per sak/modus. Batchsummer gjelder de 100 siste registrerte batchene før modusfilter.",
    }
