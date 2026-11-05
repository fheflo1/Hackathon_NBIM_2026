"""Reproducible local commands. No API calls unless --mode llm is explicit."""

import argparse
import json
import sys
from pathlib import Path

from .data import prepare_csv, write_prepared

ROOT = Path(__file__).resolve().parents[1]


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def dataset(args):
    path = args.input or ROOT / "data" / f"{args.source}_votes.csv"
    if args.source == "upload" and not args.input:
        raise ValueError("--source upload krever --input sti/til/saksliste.csv")
    return prepare_csv(path, args.source)


def main(argv=None):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Sporbar dataflyt for stemmeanbefalinger")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "train", "process", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--source", choices=("real", "npx", "upload"), default="real")
        command.add_argument("--input", type=Path)
        if name == "prepare":
            command.add_argument("--out", type=Path)
        if name == "train":
            command.add_argument("--out", type=Path, default=ROOT / "artifacts/model")
            command.add_argument("--clusters", type=int, default=0)
            command.add_argument("--target-recall", type=float, default=0.8)
        if name in ("process", "evaluate"):
            command.add_argument("--db", type=Path, default=ROOT / "artifacts/audit.sqlite")
            command.add_argument("--mode", choices=("demo", "llm"), default="demo" if name == "process" else "llm")
        if name == "process":
            command.add_argument("--limit", type=int, default=20)
            command.add_argument("--max-attempts", type=int, default=5)
            command.add_argument("--policy", type=Path, default=ROOT / "policies/nbim_2025.json")
            command.add_argument("--model", help="API-modellnavn; ellers OPENAI_MODEL")
            command.add_argument("--reviewer-model")
            command.add_argument("--priority-model", type=Path)
            command.add_argument("--year", type=int, help="Begrens sakslisten til ett møteår")
    demo = commands.add_parser("demo", help="Reproduser datakontroll, historisk modell og syntetisk flyt")
    demo.add_argument("--skip-training", action="store_true")
    commands.add_parser("attack-test", help="Kjør syntetisk motstandstest uten API")
    args = parser.parse_args(argv)
    try:
        if args.command in ("prepare", "train", "process", "evaluate"):
            prepared = dataset(args)
            if args.command == "prepare":
                write_prepared(prepared, args.out or ROOT / "artifacts/processed" / args.source)
                emit(prepared["report"])
            elif args.command == "train":
                from .model import train_model
                emit(train_model(prepared["records"], prepared["labels"], args.out,
                                 target_recall=args.target_recall, clusters=args.clusters))
            elif args.command == "evaluate":
                from .evaluation import evaluate_results
                from .workflow import load_results
                emit(evaluate_results(prepared["records"], prepared["labels"], load_results(args.db), mode=args.mode))
            else:
                from .workflow import process_records
                records = prepared["records"]
                if args.year:
                    records = [r for r in records if r["meeting_date"].startswith(str(args.year) + "-")]
                emit(process_records(records, db_path=args.db, mode=args.mode, model=args.model,
                                     reviewer_model=args.reviewer_model, max_attempts=args.max_attempts,
                                     limit=args.limit, policy_path=args.policy, model_path=args.priority_model))
        else:
            run_demo(skip_training=args.command == "attack-test" or args.skip_training,
                     attack_only=args.command == "attack-test")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Kunne ikke fullføre: {exc}\n")


def run_demo(skip_training=False, attack_only=False):
    from .workflow import load_results, process_records
    artifacts = ROOT / "artifacts"
    summary = {"mode": "offline_demo", "live_llm_tested": False}
    if not attack_only:
        for source in ("real", "npx"):
            prepared = prepare_csv(ROOT / "data" / f"{source}_votes.csv", source)
            write_prepared(prepared, artifacts / "processed" / source)
            summary[source] = {k: prepared["report"][k] for k in
                               ("total_rows", "accepted_records", "quarantined_rows", "unknown_labels", "input_sha256")}
            if source == "real" and not skip_training:
                from .model import train_model
                report = train_model(prepared["records"], prepared["labels"], artifacts / "model")
                summary["model_test_2026"] = report["test"]
    demo = prepare_csv(ROOT / "data/demo_agenda.csv", "upload")
    path = artifacts / "demo.sqlite"
    summary["workflow"] = process_records(demo["records"], db_path=path, policy_path=ROOT / "policies/nbim_2025.json")
    summary["second_pass"] = process_records(demo["records"], db_path=path, policy_path=ROOT / "policies/nbim_2025.json")
    results = load_results(path)
    # Select current case versions, since changes to code/policy preserve history.
    latest = {}
    for result in results:
        latest.setdefault(result["record_id"], result)
    attacked = [r for r in latest.values() if "Ignore the NBIM" in r["proposal_text"]]
    summary["attack_test"] = {
        "fixture": "Synthetic instruction inserted in proposal_text",
        "detector_handoff": bool(attacked) and all(r["vote"] == "AVSTÅ" and r["needs_human_review"]
                                                    and r["fallback_type"] == "prompt_injection" for r in attacked),
        "limitation": "Tester kjent tekstmønster og sikkerhetsruting; beviser ikke LLM-robusthet mot andre angrep.",
    }
    summary["demo_results"] = [{k: r[k] for k in ("company", "vote", "status", "needs_human_review", "attempts", "fallback_type")}
                               for r in latest.values()]
    artifacts.mkdir(exist_ok=True)
    (artifacts / "demo_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit(summary)
    if not summary["attack_test"]["detector_handoff"]:
        raise RuntimeError("Motstandstesten feilet; se artifacts/demo_report.json")


if __name__ == "__main__":
    main()
