"""Safe provider errors, call budgets and lightweight operational telemetry."""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone


class CallBudgetExceeded(RuntimeError):
    pass


@dataclass
class CallBudget:
    limit: int
    used: int = 0

    def reserve(self):
        if self.used >= self.limit:
            raise CallBudgetExceeded("Grensen for API-kall i denne batchen er nådd.")
        self.used += 1


def provider_error(exc):
    """Never put raw provider messages, prompts or credentials in app logs."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if isinstance(exc, CallBudgetExceeded):
        category, stop, message = (
            "call_budget",
            True,
            "API-budsjettet er brukt opp. Fortsett i en ny batch.",
        )
    elif status in (401, 403) or name in ("AuthenticationError", "PermissionDeniedError"):
        category, stop, message = (
            "authentication",
            True,
            "Kontroller API-nøkkel og modelltilgang i .env.",
        )
    elif status == 429 or name == "RateLimitError":
        category, stop, message = (
            "rate_limit",
            True,
            "Leverandørens grense eller kvote er nådd. Kontroller kvote før ny kjøring.",
        )
    elif status in (400, 404, 422) or name in ("BadRequestError", "NotFoundError"):
        category, stop, message = (
            "configuration",
            True,
            "Modellen eller API-innstillingene støttes ikke. Kjør probe og kontroller oppsettet.",
        )
    elif (
        isinstance(exc, (ConnectionError, TimeoutError))
        or name
        in (
            "APIConnectionError",
            "APITimeoutError",
            "ConnectError",
            "ConnectTimeout",
            "ReadTimeout",
            "ReadError",
        )
        or (isinstance(status, int) and status >= 500)
    ):
        category, stop, message = (
            "transient",
            False,
            "Midlertidig nettverks- eller leverandørfeil. Saken kan forsøkes igjen.",
        )
    else:
        category, stop, message = (
            "invalid_response",
            False,
            "Modellen leverte ikke et gyldig, fullført svar. Kontroller modell og tokengrense.",
        )
    return {
        "type": name,
        "category": category,
        "stop_batch": stop,
        "message": message,
        "request_id": getattr(exc, "request_id", None),
        "status_code": status,
    }


def log_event(event, **fields):
    """Only pass operational IDs/counts here; source text lives in the audit DB."""
    logger = logging.getLogger("nbim_flow.operations")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(os.getenv("NBIM_LOG_LEVEL", "INFO").upper())
        logger.propagate = False
    logger.info(
        json.dumps(
            {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **fields},
            ensure_ascii=False,
        )
    )
