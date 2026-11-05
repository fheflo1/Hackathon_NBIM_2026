"""Text-only historical vote model for queue priority, never final voting.

Labels stay outside the feature payload. TF-IDF and optional clusters are fitted
only on the chronological training set. The routing threshold is selected only
on validation data; the newest dates are held out until final reporting.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable

VOTES = ("FOR", "MOT", "AVSTÅ")
MODEL_VERSION = "text-priority-v1"


def _text(record: dict[str, Any]) -> str:
    """The only model feature. Do not add outcomes, rationales or categories."""
    return str(record.get("proposal_text") or "")


def chronological_split(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep a whole meeting date in one partition, including short histories."""
    if not records:
        raise ValueError("Ingen trenbare stemmer etter filtrering.")
    for record in records:
        date.fromisoformat(record["meeting_date"])
    ordered = sorted(records, key=lambda r: (r["meeting_date"], r["record_id"]))
    years = sorted({date.fromisoformat(r["meeting_date"]).year for r in ordered})
    dates = sorted({r["meeting_date"] for r in ordered})
    if len(years) >= 3:
        validation_start, test_start = f"{years[-2]}-01-01", f"{years[-1]}-01-01"
        method = "calendar_years"
    else:
        if len(dates) < 3:
            raise ValueError("Trenger minst tre ulike møtedatoer for train/validation/test.")
        validation_index = max(1, min(len(dates) - 2, int(len(dates) * 0.6)))
        test_index = max(validation_index + 1, min(len(dates) - 1, int(len(dates) * 0.8)))
        validation_start, test_start = dates[validation_index], dates[test_index]
        method = "distinct_date_60_20_20"
    partitions = {
        "train": [r for r in ordered if r["meeting_date"] < validation_start],
        "validation": [r for r in ordered if validation_start <= r["meeting_date"] < test_start],
        "test": [r for r in ordered if r["meeting_date"] >= test_start],
    }
    if not all(partitions.values()):
        raise ValueError("Tidsdelingen ga en tom partisjon; bruk flere møtedatoer.")
    return {
        **partitions,
        "metadata": {
            "method": method,
            "validation_start": validation_start,
            "test_start": test_start,
            **{
                name: {
                    "count": len(rows),
                    "date_min": min(r["meeting_date"] for r in rows),
                    "date_max": max(r["meeting_date"] for r in rows),
                    "class_counts": dict(Counter(r["vote_label"] for r in rows)),
                }
                for name, rows in partitions.items()
            },
        },
    }


def select_routing_threshold(
    actual: Iterable[str], probabilities: Iterable[float], target_recall: float = 0.8
) -> dict[str, Any]:
    """Choose the largest validation threshold meeting the requested MOT recall.

    No positive validation examples means recall cannot be estimated. Route all
    cases for priority rather than pretending the absence establishes safety.
    """
    if not 0 < target_recall <= 1:
        raise ValueError("target_recall må være i intervallet (0, 1].")
    labels, scores = list(actual), [float(p) for p in probabilities]
    if len(labels) != len(scores) or not labels:
        raise ValueError("Valideringslabels og sannsynligheter må ha samme, positive lengde.")
    if any(not 0 <= p <= 1 for p in scores):
        raise ValueError("MOT-sannsynligheter må ligge mellom 0 og 1.")
    positive_scores = sorted(p for y, p in zip(labels, scores) if y == "MOT")
    if not positive_scores:
        return {
            "threshold": 0.0,
            "target_recall": target_recall,
            "validation_recall": None,
            "validation_precision": None,
            "reason": "no_positive_validation_examples_route_all",
        }
    # The required order statistic is an observed positive probability. Any
    # larger threshold would remove a required positive, including tied scores.
    import math

    required = math.ceil(target_recall * len(positive_scores))
    threshold = positive_scores[len(positive_scores) - required]
    routed = [p >= threshold for p in scores]
    tp = sum(flag and y == "MOT" for flag, y in zip(routed, labels))
    return {
        "threshold": threshold,
        "target_recall": target_recall,
        "validation_recall": tp / len(positive_scores),
        "validation_precision": tp / sum(routed) if any(routed) else 0.0,
        "reason": "highest_validation_threshold_meeting_recall",
    }


def _metrics(actual: list[str], predicted: list[str], probabilities=None) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, average_precision_score, confusion_matrix
    from sklearn.metrics import precision_recall_fscore_support

    if not actual:
        return {"count": 0, "mot_precision": None, "mot_recall": None, "mot_f1": None}
    binary_actual, binary_predicted = [y == "MOT" for y in actual], [y == "MOT" for y in predicted]
    precision, recall, f1, _ = precision_recall_fscore_support(
        binary_actual, binary_predicted, average="binary", zero_division=0
    )
    result = {
        "count": len(actual),
        "accuracy": float(accuracy_score(actual, predicted)),
        "mot_precision": float(precision),
        "mot_recall": float(recall),
        "mot_f1": float(f1),
        "mot_support": sum(binary_actual),
        "class_counts": dict(Counter(actual)),
        "confusion_matrix": {
            "labels": list(VOTES),
            "rows_actual_columns_predicted": confusion_matrix(actual, predicted, labels=list(VOTES)).tolist(),
        },
    }
    if probabilities is not None:
        result["mot_average_precision"] = (
            float(average_precision_score(binary_actual, probabilities)) if any(binary_actual) else None
        )
    return result


def _dependencies():
    try:
        import joblib
        import sklearn
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:
        raise RuntimeError("Installer prosjektets avhengigheter: pip install -r requirements.txt") from exc
    return joblib, sklearn, TfidfVectorizer, LogisticRegression


def train_model(
    records: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    output_dir: str | Path,
    target_recall: float = 0.8,
    clusters: int = 0,
) -> dict[str, Any]:
    """Train on one source and save an honestly held-out evaluation.

    N-PX labels have unverified manager provenance and are never silently mixed
    with NBIM labels. ``prioritize`` retains every record, even at low scores.
    """
    joblib, sklearn, TfidfVectorizer, LogisticRegression = _dependencies()
    if not 0 < target_recall <= 1:
        raise ValueError("target_recall må være i intervallet (0, 1].")
    if clusters < 0:
        raise ValueError("clusters må være null eller positivt.")
    label_by_id = {}
    for label in labels:
        identity = label["record_id"]
        if identity in label_by_id and label_by_id[identity] != label:
            raise ValueError(f"Motstridende labels for {identity}.")
        label_by_id[identity] = label
    eligible, seen, excluded = [], set(), Counter()
    sources = {str(r.get("source") or "unknown") for r in records}
    if len(sources) != 1:
        raise ValueError("Tren én datakilde om gangen; NBIM- og N-PX-labels må ikke blandes.")
    for record in records:
        identity = record["record_id"]
        if identity in seen:
            raise ValueError(f"Duplikat-ID i modellinput: {identity}.")
        seen.add(identity)
        label = label_by_id.get(identity, {})
        if label.get("vote_label") not in VOTES:
            excluded["unknown_label"] += 1
        elif not label.get("training_eligible", True):
            excluded["training_ineligible"] += 1
        elif not _text(record).strip():
            excluded["empty_text"] += 1
        else:
            # Explicit projection: post-vote columns can never enter training.
            eligible.append({
                "record_id": identity,
                "meeting_date": record["meeting_date"],
                "proposal_text": _text(record),
                "mgmt_rec": record.get("mgmt_rec"),
                "vote_label": label["vote_label"],
            })
    split = chronological_split(eligible)
    training, validation, testing = split["train"], split["validation"], split["test"]
    train_labels = [r["vote_label"] for r in training]
    if len(set(train_labels)) < 2 or "MOT" not in train_labels:
        raise ValueError("Treningsperioden må inneholde minst to klasser, inkludert MOT.")
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2), max_features=30000, min_df=1, sublinear_tf=True,
        strip_accents="unicode", token_pattern=r"(?u)\b\w\w+\b",
    )
    x_train = vectorizer.fit_transform([_text(r) for r in training])
    classifier = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
    classifier.fit(x_train, train_labels)
    mot_index = list(classifier.classes_).index("MOT")
    x_validation = vectorizer.transform([_text(r) for r in validation])
    validation_p = classifier.predict_proba(x_validation)[:, mot_index].tolist()
    routing = select_routing_threshold([r["vote_label"] for r in validation], validation_p, target_recall)
    x_test = vectorizer.transform([_text(r) for r in testing])
    predictions = classifier.predict(x_test).tolist()
    test_p = classifier.predict_proba(x_test)[:, mot_index].tolist()
    actual = [r["vote_label"] for r in testing]
    route_labels = ["MOT" if p >= routing["threshold"] else "FOR" for p in test_p]
    board_indices = [i for i, r in enumerate(testing) if r.get("mgmt_rec") in VOTES]
    source = next(iter(sources))
    training_digest = hashlib.sha256(json.dumps(
        [[r["record_id"], r["meeting_date"], _text(r), r["vote_label"]] for r in training],
        ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    model_id = hashlib.sha256(json.dumps({
        "version": MODEL_VERSION, "sklearn": sklearn.__version__, "training_digest": training_digest,
        "routing": routing, "clusters": clusters,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    clusterer, cluster_topics = None, {}
    if clusters:
        if clusters > len(training):
            raise ValueError("Antall klynger kan ikke overstige antall treningsrader.")
        from sklearn.cluster import MiniBatchKMeans

        clusterer = MiniBatchKMeans(n_clusters=clusters, random_state=42, n_init=3, batch_size=1024)
        clusterer.fit(x_train)
        terms = vectorizer.get_feature_names_out()
        cluster_topics = {
            str(i): [str(terms[j]) for j in center.argsort()[-8:][::-1]]
            for i, center in enumerate(clusterer.cluster_centers_)
        }
    report = {
        "model_version": MODEL_VERSION,
        "model_id": model_id,
        "source": source,
        "label_provenance": "NBIM labels as supplied; source authenticity not independently audited" if source == "real"
        else "N-PX manager identity unverified; these are not established NBIM labels",
        "features": ["proposal_text"],
        "excluded": dict(excluded),
        "split": split["metadata"],
        "routing_threshold": routing,
        "test": {
            "model": _metrics(actual, predictions, test_p),
            "routing": {
                **_metrics(actual, route_labels, test_p),
                "priority_count": sum(y == "MOT" for y in route_labels),
                "priority_fraction": sum(y == "MOT" for y in route_labels) / len(testing),
                "meaning": "MOT here means high-priority queue, not an approved vote",
            },
            "always_for_baseline": _metrics(actual, ["FOR"] * len(actual)),
            "board_baseline": {
                **_metrics([actual[i] for i in board_indices], [testing[i]["mgmt_rec"] for i in board_indices]),
                "coverage": len(board_indices) / len(testing),
                "missing_board_recommendations": len(testing) - len(board_indices),
            },
            "model_on_board_available_subset": _metrics(
                [actual[i] for i in board_indices], [predictions[i] for i in board_indices], [test_p[i] for i in board_indices]
            ),
        },
        "cluster_topics": cluster_topics,
        "limitations": [
            "Scores are uncalibrated; class weighting changes their probability interpretation.",
            "Historical vote prediction is queue priority, not evidence of NBIM policy compliance.",
            "No record is skipped or approved based on this score.",
            "Training-source performance does not establish transfer to another manager or source.",
            "Repeated proposal wording can span years; dates are disjoint, wording need not be.",
        ],
    }
    bundle = {
        "model_version": MODEL_VERSION, "model_id": model_id, "source": source,
        "sklearn_version": sklearn.__version__, "vectorizer": vectorizer,
        "classifier": classifier, "mot_index": mot_index,
        "threshold": routing["threshold"], "clusterer": clusterer,
        "trained_through": split["metadata"]["train"]["date_max"],
        "evaluated_through": split["metadata"]["test"]["date_max"],
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output / "model.joblib")
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "test_predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = ["record_id", "meeting_date", "actual_vote", "predicted_vote", "p_mot", "priority", "mgmt_rec"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row, prediction, probability in zip(testing, predictions, test_p):
            writer.writerow({
                "record_id": row["record_id"], "meeting_date": row["meeting_date"],
                "actual_vote": row["vote_label"], "predicted_vote": prediction,
                "p_mot": probability,
                "priority": "high" if probability >= routing["threshold"] else "normal",
                "mgmt_rec": row.get("mgmt_rec") or "",
            })
    return report


def load_model(path: str | Path) -> dict[str, Any]:
    """Load only trusted local artifacts: joblib can execute code when loading."""
    joblib, *_ = _dependencies()
    location = Path(path)
    bundle = joblib.load(location / "model.joblib" if location.is_dir() else location)
    if not isinstance(bundle, dict) or bundle.get("model_version") != MODEL_VERSION:
        raise ValueError("Ukjent modellformat; tren modellen på nytt.")
    return bundle


def prioritize(records: list[dict[str, Any]], model_path: str | Path) -> list[dict[str, Any]]:
    """Annotate all records in their input order; low priority is never a skip.

    The source check prevents unsupported cross-manager use. A model fitted on
    later historical data can still be used for an exploratory dashboard, but
    this must not be reported as a new chronological backtest.
    """
    model = load_model(model_path)
    if not records:
        return []
    if any(str(r.get("source") or "unknown") != model["source"] for r in records):
        raise ValueError("Modellen kan bare prioritere sin egen datakilde.")
    matrix = model["vectorizer"].transform([_text(r) for r in records])
    probabilities = model["classifier"].predict_proba(matrix)[:, model["mot_index"]].tolist()
    predictions = model["classifier"].predict(matrix).tolist()
    cluster_ids = model["clusterer"].predict(matrix).tolist() if model.get("clusterer") is not None else [None] * len(records)
    return [
        {
            **record,
            "p_mot": float(probability),
            "priority": "high" if probability >= model["threshold"] else "normal",
            "predicted_vote": prediction,
            "priority_model_id": model["model_id"],
            **({"cluster": int(cluster)} if cluster is not None else {}),
        }
        for record, probability, prediction, cluster in zip(records, probabilities, predictions, cluster_ids)
    ]
