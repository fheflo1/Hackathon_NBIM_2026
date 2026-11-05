"""Reproducible offline demonstration, kept separate from production commands."""

import json

from .data import prepare_csv, write_prepared


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run_demo(skip_training=False, attack_only=False):
    from .config import Settings
    from .workflow import load_results, process_records

    ROOT = Settings.from_env().root
    artifacts = ROOT / "artifacts"
    summary = {"mode": "offline_demo", "live_llm_tested": False}
    if not attack_only:
        for source in ("real", "npx"):
            prepared = prepare_csv(ROOT / "data" / f"{source}_votes.csv", source)
            write_prepared(prepared, artifacts / "processed" / source)
            summary[source] = {
                k: prepared["report"][k]
                for k in (
                    "total_rows",
                    "accepted_records",
                    "quarantined_rows",
                    "unknown_labels",
                    "input_sha256",
                )
            }
            if source == "real" and not skip_training:
                from .model import train_model

                report = train_model(
                    prepared["records"], prepared["labels"], artifacts / "demo_model"
                )
                summary["model_test_2026"] = report["test"]
    demo = prepare_csv(ROOT / "data/demo_agenda.csv", "upload")
    path = artifacts / "demo.sqlite"
    summary["workflow"] = process_records(
        demo["records"], db_path=path, policy_path=ROOT / "policies/nbim_2025.json"
    )
    summary["second_pass"] = process_records(
        demo["records"], db_path=path, policy_path=ROOT / "policies/nbim_2025.json"
    )
    results = load_results(path)
    # Select current case versions, since changes to code/policy preserve history.
    latest = {}
    for result in results:
        latest.setdefault(result["record_id"], result)
    attacked = [r for r in latest.values() if "Ignore the NBIM" in r["proposal_text"]]
    summary["attack_test"] = {
        "fixture": "Synthetic instruction inserted in proposal_text",
        "detector_handoff": bool(attacked)
        and all(
            r["vote"] == "AVSTÅ"
            and r["needs_human_review"]
            and r["fallback_type"] == "prompt_injection"
            for r in attacked
        ),
        "limitation": "Tester kjent tekstmønster og sikkerhetsruting; beviser ikke LLM-robusthet mot andre angrep.",
    }
    summary["demo_results"] = [
        {
            k: r[k]
            for k in (
                "company",
                "vote",
                "status",
                "needs_human_review",
                "attempts",
                "fallback_type",
            )
        }
        for r in latest.values()
    ]
    artifacts.mkdir(exist_ok=True)
    (artifacts / "demo_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    emit(summary)
    if not summary["attack_test"]["detector_handoff"]:
        raise RuntimeError("Motstandstesten feilet; se artifacts/demo_report.json")
