"""Read-only aggregate provenance for the data workspace."""

from functools import lru_cache

import httpx

from ..data import prepare_csv
from ..policy import load_policy


@lru_cache(maxsize=6)
def source_report(path, modified, size):
    prepared = prepare_csv(path, "real" if path.endswith("real_votes.csv") else "npx")
    raw_counts = prepared["report"]["label_counts"]
    counts = {vote: raw_counts.get(vote, 0) for vote in ("FOR", "MOT", "AVSTÅ")}
    counts["UKJENT"] = raw_counts.get("UNKNOWN", 0)
    return {
        "report": prepared["report"],
        "counts": counts,
        "known": sum(counts[v] for v in ("FOR", "MOT", "AVSTÅ")),
        "quarantined": len(prepared["quarantine"]),
    }


def bootstrap(settings):
    policy = load_policy(settings.policy_path)
    sources = []
    for key, name, filename in [
        ("real", "NBIM · stemmehistorikk", "real_votes.csv"),
        ("npx", "N-PX · separat datakilde", "npx_votes.csv"),
    ]:
        path = settings.root / "data" / filename
        if path.exists():
            st = path.stat()
            sources.append(
                dict(source_report(str(path), st.st_mtime_ns, st.st_size), id=key, name=name)
            )
    available, detail = False, "Modelltilgang er ikke kontrollert."
    if settings.provider == "ollama":
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                response = client.get(settings.base_url + "/api/tags")
            response.raise_for_status()
            names = {m.get("name") for m in response.json().get("models", [])}
            available = {settings.model, settings.reviewer_model or settings.model}.issubset(names)
            detail = (
                "Lokal modell tilgjengelig"
                if available
                else "Den valgte modellen er ikke lastet ned i Ollama."
            )
        except (httpx.HTTPError, ValueError):
            detail = "Start Ollama for å behandle nye sakslister."
    else:
        available = bool(settings.api_key and settings.model)
        detail = (
            "API konfigurert; tilkobling testes ved kjøring."
            if available
            else "API-oppsettet mangler."
        )
    return {
        "model": {
            "name": settings.model,
            "reviewer": settings.reviewer_model,
            "provider": settings.provider,
            "available": available,
            "detail": detail,
        },
        "policy": {
            k: policy[k] for k in ("version", "valid_from", "valid_through", "source_url", "rules")
        },
        "sources": sources,
        "limits": {"max_mb": 20, "max_items": 100, "max_attempts": settings.max_attempts},
    }
