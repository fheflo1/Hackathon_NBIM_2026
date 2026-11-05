"""Deterministic preprocessing and a strict boundary around pre-vote evidence.

Historical votes, explanations and data-quality flags are exported separately
from records. Neither the classifier nor an agent should consume the labels file.
All functionality in this module uses Python's standard library.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


_FACT_FIELDS = (
    "source", "company_id", "company", "ticker", "country", "market",
    "meeting_id", "meeting_date", "item_no", "proposal_number",
    "proposal_text", "proponent", "mgmt_rec",
)
SAFE_FIELDS = ("record_id", *_FACT_FIELDS, "evidence_hash", "topic")
PREPROCESSING_VERSION = "1.0.0"
_SOURCES = {"real", "npx", "upload"}
_VOTES = {
    "FOR": "FOR", "AGAINST": "MOT", "MOT": "MOT",
    "WITHHOLD": "MOT", "ABSTAIN": "AVSTÅ", "AVSTÅ": "AVSTÅ",
    "AVSTA": "AVSTÅ",
}


def _text(value: Any) -> str:
    """NFC and whitespace normalization retain words, case and punctuation."""
    return " ".join(unicodedata.normalize("NFC", str(value or "")).split())


def normalize_vote(value: Any) -> str | None:
    """Map supported labels; nonvotes and voting frequencies remain unknown.

    WITHHOLD is grouped with MOT for classification, while raw_vote in the
    separate labels export preserves its different legal meaning.
    """
    return _VOTES.get(_text(value).upper())


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _topic(text: str) -> str:
    """A transparent routing hint, never a historical category or decision."""
    text = text.casefold()
    patterns = (
        ("sustainability", r"climate|sustainab|environment|emission|human rights"),
        ("remuneration", r"remunerat|compensat|say.on.pay|equity.plan|incentive|pay "),
        ("auditor", r"auditor|audit firm|accounting firm"),
        ("board", r"director|board|chairperson|chairman"),
        ("capital", r"share (?:issuance|repurchase)|buyback|capital|merger|acquisition"),
        ("financial", r"financial statement|annual report|dividend|accounts"),
        ("shareholder_rights", r"shareholder|voting right|written consent|proxy access"),
    )
    return next((name for name, pattern in patterns if re.search(pattern, text)), "other")


def safe_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return only pre-vote facts, recomputing all derived fields.

    This remains a whitelist even when callers provide an already prepared
    record with appended label or rationale fields. It does not fetch external
    evidence or infer missing company facts from historical vote explanations.
    """
    result: dict[str, Any] = {key: _text(record.get(key)) for key in _FACT_FIELDS}
    source = result["source"]
    if source not in _SOURCES:
        raise ValueError("source must be explicitly set to real, npx or upload")
    result["item_no"] = result["item_no"] or result["proposal_number"]
    management = record.get("mgmt_rec_raw")
    if not _text(management):
        management = record.get("mgmt_rec")
    result["mgmt_rec"] = normalize_vote(management)
    identity = [source, result["meeting_id"], result["item_no"]]
    result["record_id"] = _hash(identity)
    result["evidence_hash"] = _hash({key: result[key] for key in _FACT_FIELDS})
    result["topic"] = _topic(result["proposal_text"])
    return {key: result[key] for key in SAFE_FIELDS}


def _valid_date(value: str) -> bool:
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and date.fromisoformat(value) is not None
    except ValueError:
        return False


def _label(raw: dict[str, Any], record_id: str) -> dict[str, Any]:
    raw_vote = _text(raw.get("nbim_vote_raw")) or _text(raw.get("nbim_vote"))
    vote = normalize_vote(raw_vote)
    flags = []
    if vote is None:
        flags.append("unknown_vote_label")
    normalized_given = normalize_vote(raw.get("nbim_vote"))
    if normalized_given is not None and normalized_given != vote:
        flags.append("inconsistent_vote_label")
    if _text(raw.get("funds_disagree")).casefold() in {"1", "1.0", "true", "yes"}:
        flags.append("funds_disagree")
    if _text(raw.get("injection_flag")).casefold() in {"1", "1.0", "true", "yes"}:
        # This source flag also marks extraction noise; it is not evidence that
        # a deliberate prompt-injection attack has actually taken place.
        flags.append("source_quality_flag")
    if not _text(raw.get("company_id")):
        flags.append("missing_company_id")
    if not _text(raw.get("country")):
        flags.append("missing_country")
    disqualifying = {"unknown_vote_label", "inconsistent_vote_label",
                     "funds_disagree", "source_quality_flag"}
    return {
        "record_id": record_id,
        "vote_label": vote,
        "raw_vote": raw_vote,
        "training_eligible": not bool(disqualifying.intersection(flags)),
        "quality_flags": flags,
    }


def prepare_csv(path: str | Path, source: str) -> dict[str, Any]:
    """Read the complete CSV, report quality, and separate evidence from labels.

    All distinct rows sharing a source/meeting/item identity are quarantined
    when any column conflicts, including historical labels. Exact duplicates
    of otherwise valid rows are retained once. Unknown votes remain usable for
    inference. source is mandatory because company and meeting IDs are not
    comparable between NBIM and N-PX datasets.
    """
    if source not in _SOURCES:
        raise ValueError("source must be explicitly set to real, npx or upload")
    raw_bytes = Path(path).read_bytes()
    input_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    with io.StringIO(raw_bytes.decode("utf-8-sig"), newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV must contain a header")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV has duplicate column names")
        columns = list(reader.fieldnames)
        raw_rows = list(reader)

    missingness = {key: sum(not _text(row.get(key)) for row in raw_rows) for key in columns}
    label_counts: Counter[str] = Counter()
    dates = []
    groups: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    quarantine: list[dict[str, Any]] = []
    records = []
    labels = []

    def reject(row_number: int, raw: dict[str, Any], reasons: list[str], record_id: str | None) -> None:
        quarantine.append({"source": source, "row_number": row_number,
                           "record_id": record_id, "reasons": reasons,
                           "record": raw})

    for row_number, raw in enumerate(raw_rows, start=2):
        vote = normalize_vote(_text(raw.get("nbim_vote_raw")) or raw.get("nbim_vote"))
        label_counts[vote or "UNKNOWN"] += 1
        meeting_date = _text(raw.get("meeting_date"))
        if _valid_date(meeting_date):
            dates.append(meeting_date)
        if None in raw:
            reject(row_number, raw, ["malformed_csv_row"], None)
            continue
        record = safe_record({**raw, "source": source})
        if not record["meeting_id"] or not record["item_no"]:
            reject(row_number, raw, ["missing_identity"], None)
            continue
        groups[record["record_id"]].append((row_number, raw, record))

    duplicate_rows = 0
    conflicting_ids = 0
    for record_id, group in groups.items():
        signatures = {_hash({key: _text(value) for key, value in raw.items()})
                      for _, raw, _ in group}
        duplicate_rows += len(group) - len(signatures)
        if len(signatures) > 1:
            conflicting_ids += 1
            for row_number, raw, _ in group:
                reject(row_number, raw, ["conflicting_identity"], record_id)
            continue
        row_number, raw, record = group[0]
        reasons = []
        if not record["proposal_text"]:
            reasons.append("missing_proposal_text")
        if not _valid_date(record["meeting_date"]):
            reasons.append("invalid_meeting_date")
        if reasons:
            for row_number, raw, _ in group:
                reject(row_number, raw, reasons, record_id)
            continue
        records.append(record)
        labels.append(_label(raw, record_id))

    report = {
        "source": source,
        "input_file": Path(path).name,
        "input_sha256": input_sha256,
        "preprocessing_version": PREPROCESSING_VERSION,
        "total_rows": len(raw_rows),
        "columns": columns,
        "accepted_records": len(records),
        "quarantined_rows": len(quarantine),
        "duplicate_rows": duplicate_rows,
        "conflicting_ids": conflicting_ids,
        "unknown_labels": label_counts["UNKNOWN"],
        "label_counts": dict(label_counts),
        "accepted_label_counts": dict(Counter(label["vote_label"] or "UNKNOWN" for label in labels)),
        "training_eligible": sum(label["training_eligible"] for label in labels),
        "missingness": missingness,
        "quality_flag_counts": dict(Counter(flag for label in labels for flag in label["quality_flags"])),
        "quarantine_reason_counts": dict(Counter(reason for row in quarantine for reason in row["reasons"])),
        "date_range": {"min": min(dates) if dates else None, "max": max(dates) if dates else None},
        "notes": [
            "Label counts and missingness cover all input rows, before deduplication.",
            "Raw nonvotes and frequency choices remain UNKNOWN, not AVSTÅ.",
            "WITHHOLD is grouped with MOT; its original value remains in labels.jsonl.",
            "injection_flag is a source quality flag, not a verified attack label.",
            "topic is derived only from proposal text, for routing, not a decision.",
            "N-PX fund provenance must be verified before treating its labels as NBIM votes.",
        ],
    }
    return {"records": records, "labels": labels, "quarantine": quarantine, "report": report}


def write_prepared(result: dict[str, Any], output_dir: str | Path) -> None:
    """Write portable UTF-8 exports, replacing earlier exports in this folder."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for key in ("records", "labels", "quarantine"):
        with (output / f"{key}.jsonl").open("w", encoding="utf-8") as handle:
            for record in result[key]:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    (output / "report.json").write_text(
        json.dumps(result["report"], ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
