"""Ollama native JSON-schema API. No credentials and no external server fallback."""

import json
import time

import httpx

from .agents import (
    AUTHOR_INSTRUCTIONS,
    DECISION_SCHEMA,
    REVIEW_INSTRUCTIONS,
    REVIEW_SCHEMA,
    _model_rules,
)
from .data import safe_record


def structured_output_options(model):
    """Qwen3 uses non-thinking mode so its small JSON budget reaches the final answer."""
    if model.split(":", 1)[0].lower() == "qwen3":
        return {"think": False}
    return {}


class LocalProviderError(RuntimeError):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"Lokal modellserver svarte med HTTP {status_code}.")


class OllamaAgents:
    def __init__(self, settings, model=None, reviewer_model=None):
        self.settings = settings
        self.model = model or settings.model
        self.reviewer_model = reviewer_model or settings.reviewer_model or self.model
        self.client = httpx.Client(
            base_url=settings.base_url, timeout=settings.timeout_seconds, trust_env=False
        )
        self.last_usage = {}

    def close(self):
        self.client.close()

    def _call(self, model, instructions, payload, schema):
        self.last_usage = {}
        started = time.perf_counter()
        # Include the contract in the prompt as recommended by Ollama, while
        # constrained decoding enforces its structure independently.
        response = self.client.post(
            "/api/chat",
            json={
                "model": model,
                **structured_output_options(model),
                "stream": False,
                "format": schema,
                "keep_alive": "5m",
                "messages": [
                    {
                        "role": "system",
                        "content": instructions + "\nReturn JSON matching: " + json.dumps(schema),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "options": {
                    "temperature": 0,
                    "num_ctx": self.settings.context_tokens,
                    "num_predict": self.settings.max_output_tokens,
                },
            },
        )
        if not response.is_success:
            raise LocalProviderError(response.status_code)
        data = response.json()
        self.last_usage = {
            "provider": "ollama",
            "model": data.get("model", model),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "usage": {
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
            },
            "load_duration_ns": data.get("load_duration"),
        }
        if data.get("done") is not True or data.get("done_reason") == "length":
            raise ValueError(
                "Lokalt modellsvar ble avbrutt; kontroller tokengrense og tidsavbrudd."
            )
        if (
            data.get("prompt_eval_count", 0)
            >= self.settings.context_tokens - self.settings.max_output_tokens
        ):
            raise ValueError("For lite kontekstvindu til sikker behandling av denne teksten.")
        return json.loads(data["message"]["content"])

    def propose(self, record, rules, feedback=""):
        return self._call(
            self.model,
            AUTHOR_INSTRUCTIONS,
            {
                "agenda_evidence": safe_record(record),
                "policies": _model_rules(rules),
                "reviewer_feedback": feedback,
            },
            DECISION_SCHEMA,
        )

    def review(self, record, rules, candidate):
        return self._call(
            self.reviewer_model,
            REVIEW_INSTRUCTIONS,
            {
                "agenda_evidence": safe_record(record),
                "policies": _model_rules(rules),
                "candidate": candidate,
            },
            REVIEW_SCHEMA,
        )


def create_agents(settings, model=None, reviewer_model=None):
    if settings.provider == "ollama":
        return OllamaAgents(settings, model, reviewer_model)
    from .agents import LLMAgents

    return LLMAgents(
        model or settings.model, reviewer_model or settings.reviewer_model, settings=settings
    )


def local_models(settings):
    """Explicit connectivity check; never invoked implicitly by an offline doctor."""
    with httpx.Client(base_url=settings.base_url, timeout=5, trust_env=False) as client:
        try:
            response = client.get("/api/tags")
        except httpx.HTTPError:
            raise RuntimeError(
                "Kan ikke kontakte lokal Ollama. Start Ollama-appen eller kjør ollama serve."
            ) from None
        if not response.is_success:
            raise LocalProviderError(response.status_code)
        return [
            {
                "name": r["name"],
                "digest": r.get("digest"),
                "size": r.get("size"),
                "remote_host": r.get("remote_host"),
            }
            for r in response.json().get("models", [])
        ]


def model_identity(settings, names):
    installed = {m["name"]: m for m in local_models(settings)}
    identity = {}
    for name in names:
        item = installed.get(name) or installed.get(name + ":latest")
        if item is None:
            raise ValueError(f"Modellen {name} er ikke installert. Kjør ollama pull {name}.")
        if item.get("remote_host") or ":cloud" in name.lower():
            raise ValueError(
                "Denne modelloppføringen peker til en skytjeneste og er ikke tillatt i lokal modus."
            )
        identity[name] = item["digest"]
    return identity
