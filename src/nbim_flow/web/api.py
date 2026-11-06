"""Same-origin local React application and upload API; no cloud fallback."""

import csv
import io
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..config import Settings
from .analytics import bootstrap
from .ingestion import MAX_BYTES
from .service import AgendaService


def create_app(settings=None, service=None):
    settings = settings or Settings.from_env()
    owned = service is None
    service = service or AgendaService(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned:
            service.close()

    app = FastAPI(
        title="STEM · NBIM voting workspace",
        version="0.3.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.service = service
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.netloc not in (
                request.headers.get("host"),
                "127.0.0.1:5173",
                "localhost:5173",
            ):
                return JSONResponse(
                    {"detail": "Denne handlingen må utføres fra den lokale appen."}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "Sakslisten finnes ikke."}, status_code=404)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.3.0"}

    @app.get("/api/bootstrap")
    def info():
        return bootstrap(settings)

    @app.get("/api/model")
    def triage_model():
        # Triage model card: validated 2024 numbers, lane thresholds, threshold curve, catalogue.
        return service.triage_card()

    @app.get("/api/jobs")
    def jobs():
        return {
            "jobs": [
                {k: j.get(k) for k in ("id", "filename", "status", "done", "total", "created_at")}
                for j in service.list()
            ]
        }

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return service.get(job_id)

    @app.post("/api/agenda", status_code=201)
    def upload(file: UploadFile = File(...)):
        raw = file.file.read(MAX_BYTES + 1)
        try:
            job, cached = service.submit(raw, file.filename or "agenda")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception:
            raise HTTPException(
                503, "Modellen er ikke klar. Start Ollama og kontroller at modellen er lastet ned."
            ) from None
        finally:
            file.file.close()
        return {"job": job, "reused": cached}

    @app.post("/api/jobs/{job_id}/items/{index}/decision")
    def decide(job_id: str, index: int, body: dict = Body(...)):
        try:
            job = service.decide(job_id, index, body.get("vote"), body.get("note", ""))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"job": job}

    @app.get("/api/jobs/{job_id}/export.csv")
    def export(job_id: str):
        job = service.get(job_id)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "sak",
                "forslag",
                "stemme",
                "konfidens",
                "status",
                "begrunnelse",
                "retningslinjer",
                "forsøk",
                "run_key",
            ]
        )
        for item in job.get("items", []):
            result = item.get("result")
            if not result:
                continue
            values = [
                item["item_no"],
                item["proposal_text"],
                result["vote"],
                result["confidence"],
                result["status"],
                result["reason"],
                "; ".join(c.get("policy_id", "") for c in result["citations"]),
                result["attempts"],
                result["run_key"],
            ]
            writer.writerow(
                [
                    "'" + v
                    if isinstance(v, str)
                    and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                    else v
                    for v in values
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="stemmeanbefalinger.csv"'},
        )

    dist = settings.root / "frontend/dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Ukjent API-endepunkt.")
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {"detail": "React-appen er ikke bygget. Kjør python3 run.py --setup."}, status_code=503
        )

    return app
