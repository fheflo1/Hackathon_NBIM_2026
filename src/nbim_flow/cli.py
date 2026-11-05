"""CLI boundary: validate configuration, invoke services, return useful exit codes."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .config import Settings
from .data import prepare_csv, write_prepared


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def parser_for_cli():
    parser = argparse.ArgumentParser(description="NBIM stemmeanbefalinger og lokal drift")
    parser.add_argument(
        "--root", type=Path, help="Prosjektmappe; ellers brukes repoet eller NBIM_ROOT"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "probe", "init-env", "models", "status", "workflow"):
        command = commands.add_parser(name)
        if name == "init-env":
            command.add_argument(
                "--model", help="Modellnavn for ny .env; eksisterende fil endres ikke"
            )
        if name == "status":
            command.add_argument("--mode", choices=("demo", "llm"), default="llm")
    backup = commands.add_parser("backup")
    backup.add_argument("--out", type=Path, required=True)
    activate = commands.add_parser("activate-model")
    activate.add_argument("run_id")
    for name in ("prepare", "train", "process", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--source", choices=("real", "npx", "upload"), default="real")
        command.add_argument("--input", type=Path)
        if name == "prepare":
            command.add_argument("--out", type=Path)
        if name == "train":
            command.add_argument("--out", type=Path)
            command.add_argument("--clusters", type=int, default=0)
            command.add_argument("--target-recall", type=float, default=0.8)
        if name in ("process", "evaluate"):
            command.add_argument("--db", type=Path)
            command.add_argument("--mode", choices=("demo", "llm"), default="llm")
        if name == "process":
            command.add_argument("--limit", type=int, default=5)
            command.add_argument("--max-attempts", type=int)
            command.add_argument("--max-api-calls", type=int)
            command.add_argument("--policy", type=Path)
            command.add_argument("--model")
            command.add_argument("--reviewer-model")
            command.add_argument("--priority-model", type=Path)
            command.add_argument("--year", type=int)
    return parser


def main(argv=None):
    parser = parser_for_cli()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env(root=args.root)
        if args.command == "init-env":
            from .diagnostics import initialize_env

            result = initialize_env(settings.root)
            if result["created"] and args.model:
                path = Path(result["path"])
                path.write_text(
                    path.read_text().replace("LLM_MODEL=qwen2.5:7b", f"LLM_MODEL={args.model}")
                )
            emit(result)
        elif args.command == "doctor":
            from .diagnostics import doctor

            report = doctor(settings)
            emit(report)
            return 0 if report["ready_offline"] else 1
        elif args.command == "probe":
            from .diagnostics import probe

            report = probe(settings)
            emit(report)
            return 0 if report["connected"] and report["structured_outputs_ok"] else 1
        elif args.command == "models":
            from .local_model import local_models

            if settings.provider != "ollama":
                raise ValueError("models viser lokalt installerte Ollama-modeller.")
            emit(local_models(settings))
        elif args.command == "status":
            from .monitoring import operational_snapshot

            emit(operational_snapshot(settings.database_path, mode=args.mode))
        elif args.command == "workflow":
            from .diagrams import WORKFLOW_MERMAID

            print(WORKFLOW_MERMAID)
        elif args.command == "activate-model":
            from .registry import activate_run

            activate_run(settings.root / "artifacts/model", args.run_id)
            emit({"activated": args.run_id})
        elif args.command == "backup":
            source = settings.database_path
            out = settings.path(args.out)
            if not source.exists() or out.exists():
                raise ValueError("Kildedatabasen må finnes, og backupfilen må være ny.")
            out.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
                with closing(sqlite3.connect(out)) as dst:
                    src.backup(dst)
            emit({"backup": str(out), "source": str(source)})
        else:
            if args.source == "upload" and args.input is None:
                raise ValueError("--source upload krever --input sti/til/agenda.csv")
            input_path = (
                settings.path(args.input)
                if args.input
                else settings.root / "data" / f"{args.source}_votes.csv"
            )
            data = prepare_csv(input_path, args.source)
            if args.command == "prepare":
                out = (
                    settings.path(args.out)
                    if args.out
                    else settings.root
                    / "artifacts/processed"
                    / args.source
                    / data["report"]["input_sha256"][:12]
                )
                write_prepared(data, out)
                emit(data["report"])
            elif args.command == "train":
                from .model import train_model

                out = settings.path(args.out) if args.out else settings.root / "artifacts/model"
                emit(
                    train_model(
                        data["records"],
                        data["labels"],
                        out,
                        target_recall=args.target_recall,
                        clusters=args.clusters,
                    )
                )
            elif args.command == "evaluate":
                from .evaluation import evaluate_results
                from .store import load_results

                path = settings.path(args.db) if args.db else settings.database_path
                emit(
                    evaluate_results(
                        data["records"], data["labels"], load_results(path), mode=args.mode
                    )
                )
            else:
                from .workflow import process_records

                records = [
                    r
                    for r in data["records"]
                    if not args.year or r["meeting_date"].startswith(f"{args.year}-")
                ]
                summary = process_records(
                    records,
                    settings=settings,
                    db_path=settings.path(args.db) if args.db else settings.database_path,
                    policy_path=settings.path(args.policy) if args.policy else settings.policy_path,
                    mode=args.mode,
                    model=args.model,
                    reviewer_model=args.reviewer_model,
                    max_attempts=args.max_attempts,
                    max_api_calls=args.max_api_calls,
                    limit=args.limit,
                    model_path=settings.path(args.priority_model) if args.priority_model else None,
                )
                emit(summary)
                return 2 if summary["errors"] or summary["stopped_reason"] else 0
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"Kunne ikke fullføre: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
