"""Offline readiness checks plus an explicitly requested, synthetic API probe."""

import importlib.metadata
import importlib.util
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from .agents import validate_decision
from .config import Settings
from .data import safe_record
from .local_model import create_agents
from .operations import provider_error
from .policy import load_policy, retrieve
from .registry import resolve_model


def doctor(settings=None):
    settings = settings or Settings.from_env()
    checks = []

    def add(name, ok, detail, required=True):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "required": required})

    add("Python", sys.version_info >= (3, 11), sys.version.split()[0])
    for module, distribution in (
        ("streamlit", "streamlit"),
        ("sklearn", "scikit-learn"),
        ("langgraph", "langgraph"),
        ("openai", "openai"),
    ):
        present = importlib.util.find_spec(module) is not None
        version = (
            importlib.metadata.version(distribution)
            if present
            else "Mangler; kjør python3 run.py --setup"
        )
        add(distribution, present, version)
    for filename in ("demo_agenda.csv", "real_votes.csv", "npx_votes.csv"):
        path = settings.root / "data" / filename
        add(filename, path.is_file(), str(path), required=filename == "demo_agenda.csv")
    try:
        policy = load_policy(settings.policy_path)
        add(
            "Policy",
            True,
            f"{policy['version']}: {policy['valid_from']} – {policy['valid_through']}, {len(policy['rules'])} regler",
        )
    except (OSError, ValueError, KeyError) as exc:
        add("Policy", False, f"Ugyldig eller manglende policy ({type(exc).__name__}).")
    try:
        folder = settings.database_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            with closing(sqlite3.connect(str(Path(directory) / "check.sqlite"))) as db:
                db.execute("CREATE TABLE readiness(value INTEGER)")
        add("Lokal lagring", True, str(folder))
    except OSError:
        add("Lokal lagring", False, "Mangler skrivetilgang til artifacts-mappen.")
    add(
        "API-nøkkel",
        settings.provider == "ollama" or bool(settings.api_key),
        "Ikke nødvendig for lokal Ollama"
        if settings.provider == "ollama"
        else "Satt; verdien skjules"
        if settings.api_key
        else "Fyll inn OPENAI_API_KEY i .env",
        required=False,
    )
    add(
        "Agentmodell",
        bool(settings.model),
        settings.model or "Fyll inn OPENAI_MODEL i .env",
        required=False,
    )
    try:
        model = resolve_model(settings.root / "artifacts/model")
        add("Prioriteringsmodell", model.is_file(), str(model), required=False)
    except (OSError, ValueError, KeyError):
        add(
            "Prioriteringsmodell",
            False,
            "Modellfilene kunne ikke verifiseres; tren på nytt.",
            required=False,
        )
    return {
        "ready_offline": all(c["ok"] for c in checks if c["required"]),
        "llm_configured": bool(
            settings.model and (settings.provider == "ollama" or settings.api_key)
        ),
        "network_tested": False,
        "configuration": settings.public_info(),
        "checks": checks,
        "note": "Konfigurasjon er ikke det samme som bekreftet modelltilgang. Kjør probe eksplisitt.",
    }


def probe(settings=None, agents=None):
    settings = settings or Settings.from_env()
    if agents is None:
        settings.validate_llm()
    policy = load_policy(settings.policy_path)
    record = safe_record(
        {
            "source": "upload",
            "company": "DEMO API-kontroll",
            "meeting_id": "api-probe",
            "meeting_date": "2025-06-01",
            "item_no": "1",
            "proposal_text": "Separate the roles of chairperson and CEO",
        }
    )
    rules = retrieve(record, policy)
    if not rules:
        raise ValueError(
            "Policyen dekker ikke den syntetiske API-testen. Kontroller policyinnstillingene."
        )
    provider = agents or create_agents(settings)
    usages = []
    try:
        candidate = provider.propose(record, rules)
        usages.append(dict(getattr(provider, "last_usage", {})))
        problems = validate_decision(candidate, record, rules, 0.0)
        checked = provider.review(record, rules, candidate)
        usages.append(dict(getattr(provider, "last_usage", {})))
        valid_review = (
            isinstance(checked, dict)
            and type(checked.get("accepted")) is bool
            and type(checked.get("retryable")) is bool
        )
        return {
            "connected": True,
            "structured_outputs_ok": not problems and valid_review,
            "recommendation": candidate,
            "review": checked,
            "validation_errors": problems,
            "calls": 2,
            "provider_usage": usages,
            "note": "Kun et syntetisk eksempel. Dette er en tilkoblingstest, ikke en kvalitetsmåling.",
        }
    except Exception as exc:
        return {
            "connected": False,
            "structured_outputs_ok": False,
            "error": provider_error(exc),
            "provider_usage": usages,
        }
    finally:
        if agents is None:
            provider.close()


def initialize_env(root=None):
    from .config import project_root

    location = project_root(root)
    target = location / ".env"
    if target.exists():
        return {"created": False, "path": str(target), "message": "Eksisterende .env beholdes."}
    content = (location / ".env.example").read_text(encoding="utf-8")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    return {
        "created": True,
        "path": str(target),
        "message": "Fyll inn nøkkel og modellnavn lokalt; ikke send nøkkelen i chat.",
    }
