"""One validated configuration boundary shared by CLI, UI and workers."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    pass


def project_root(explicit=None):
    if explicit or os.getenv("NBIM_ROOT"):
        return Path(explicit or os.environ["NBIM_ROOT"]).expanduser().resolve()
    for start in (Path.cwd(), Path(__file__).resolve().parents[2]):
        for candidate in (start, *start.parents):
            if (candidate / "pyproject.toml").is_file() and (candidate / "policies").is_dir():
                return candidate
    raise ConfigurationError("Finner ikke prosjektmappen. Start fra repoet eller sett NBIM_ROOT.")


def _number(env, name, default, minimum, maximum, cast=int):
    try:
        value = cast(env.get(name, str(default)))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} må være et tall mellom {minimum} og {maximum}.") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} må være mellom {minimum} og {maximum}.")
    return value


@dataclass(frozen=True)
class Settings:
    root: Path
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    api_key: str = field(default="", repr=False)
    model: str = ""
    reviewer_model: str = ""
    timeout_seconds: float = 45.0
    max_output_tokens: int = 4000
    max_api_calls: int = 100
    max_input_characters: int = 20000
    max_attempts: int = 5
    min_confidence: float = 0.8
    reasoning_effort: str = ""
    cache_namespace: str = "default"
    context_tokens: int = 16384
    policy_file: str = "policies/nbim_2025.json"
    database_file: str = "artifacts/audit.sqlite"
    triage_file: str = "artifacts/triage/triage_model.joblib"
    light_workers: int = 2

    @classmethod
    def from_env(cls, root=None, environ=None):
        location = project_root(root)
        if environ is None:
            from dotenv import load_dotenv

            load_dotenv(location / ".env", override=False)
        env = dict(os.environ if environ is None else environ)
        provider = env.get("LLM_PROVIDER", "ollama").strip().lower()
        if provider not in ("ollama", "openai"):
            raise ConfigurationError("LLM_PROVIDER må være ollama eller openai.")
        base_url = env.get(
            "LLM_BASE_URL",
            "http://127.0.0.1:11434" if provider == "ollama" else "https://api.openai.com/v1",
        ).rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError(
                "LLM_BASE_URL skal ikke inneholde passord, query eller fragment."
            )
        if provider == "ollama" and (
            parsed.scheme != "http"
            or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.path not in ("", "/")
        ):
            raise ConfigurationError(
                "Lokal Ollama krever http://localhost:11434 uten /v1. Eksterne verter er ikke aktivert."
            )
        if provider == "openai" and base_url != "https://api.openai.com/v1":
            raise ConfigurationError(
                "OpenAI bruker https://api.openai.com/v1. Velg ollama for lokal kjøring."
            )
        effort = env.get("OPENAI_REASONING_EFFORT", "").strip()
        if effort not in ("", "low", "medium", "high"):
            raise ConfigurationError("OPENAI_REASONING_EFFORT må være tom, low, medium eller high.")
        model = (
            env.get("LLM_MODEL")
            or env.get("OPENAI_MODEL")
            or ("qwen2.5:7b" if provider == "ollama" else "")
        ).strip()
        reviewer = (
            env.get("LLM_REVIEWER_MODEL") or env.get("OPENAI_REVIEWER_MODEL") or model
        ).strip()
        if provider == "ollama" and any(":cloud" in name.lower() for name in (model, reviewer)):
            raise ConfigurationError(
                "Cloud-modeller er ikke tillatt i lokal modus. Velg en nedlastet lokal modell."
            )
        return cls(
            root=location,
            provider=provider,
            base_url=base_url,
            api_key=env.get("OPENAI_API_KEY", "").strip(),
            model=model,
            reviewer_model=reviewer,
            timeout_seconds=_number(
                env, "NBIM_API_TIMEOUT", 120 if provider == "ollama" else 45, 5, 180, float
            ),
            max_output_tokens=_number(
                env, "NBIM_MAX_OUTPUT_TOKENS", 1500 if provider == "ollama" else 4000, 500, 16000
            ),
            max_api_calls=_number(env, "NBIM_MAX_API_CALLS", 100, 1, 1000),
            max_input_characters=_number(env, "NBIM_MAX_INPUT_CHARACTERS", 20000, 100, 200000),
            max_attempts=_number(env, "NBIM_MAX_ATTEMPTS", 5, 1, 5),
            min_confidence=_number(env, "NBIM_MIN_CONFIDENCE", 0.8, 0.0, 1.0, float),
            reasoning_effort=effort,
            cache_namespace=env.get("NBIM_CACHE_NAMESPACE", "default").strip() or "default",
            context_tokens=_number(env, "NBIM_CONTEXT_TOKENS", 16384, 4096, 65536),
            policy_file=env.get("NBIM_POLICY_PATH", "policies/nbim_2025.json"),
            database_file=env.get("NBIM_DATABASE_PATH", "artifacts/audit.sqlite"),
            triage_file=env.get("NBIM_TRIAGE_MODEL_PATH", "artifacts/triage/triage_model.joblib"),
            # parallel light agent checks; Ollama queues them on smaller machines
            light_workers=_number(env, "NBIM_LIGHT_WORKERS", 2, 1, 8),
        )

    def path(self, relative):
        path = Path(relative).expanduser()
        return path if path.is_absolute() else self.root / path

    @property
    def database_path(self):
        return self.path(self.database_file)

    @property
    def policy_path(self):
        return self.path(self.policy_file)

    @property
    def triage_model_path(self):
        return self.path(self.triage_file)

    def validate_llm(self):
        if not self.model or (self.provider == "openai" and not self.api_key):
            raise ConfigurationError(
                "Fyll inn OPENAI_API_KEY og OPENAI_MODEL i .env. Kjør doctor først."
            )
        return self

    def public_info(self):
        return {
            "root": str(self.root),
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key_configured": bool(self.api_key),
            "model": self.model,
            "reviewer_model": self.reviewer_model,
            "timeout_seconds": self.timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
            "max_api_calls": self.max_api_calls,
            "max_attempts": self.max_attempts,
            "min_confidence": self.min_confidence,
            "policy_path": str(self.policy_path),
            "database_path": str(self.database_path),
            "cache_namespace": self.cache_namespace,
        }
