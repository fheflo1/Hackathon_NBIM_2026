"""Set up once, then serve React and its local API with one command."""

import argparse
import errno
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import venv
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent


def app_already_running(port):
    """Check before building or creating an API service, which can mutate job state."""
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return False
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise RuntimeError(f"Kan ikke bruke lokal port {port}: {exc.strerror}.") from exc
    url = f"http://127.0.0.1:{port}"
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(url + "/api/health", timeout=2) as response:
            health = json.load(response)
        with opener.open(url + "/openapi.json", timeout=2) as response:
            schema = json.load(response)
        if (
            health.get("status") == "ok"
            and schema.get("info", {}).get("title") == "STEM · NBIM voting workspace"
        ):
            print(f"Appen kjører allerede. Åpne {url}", flush=True)
            print(
                "Stopp den eksisterende serveren før du starter på nytt etter kodeendringer.",
                flush=True,
            )
            return True
    except (OSError, URLError, ValueError, AttributeError):
        pass
    raise RuntimeError(
        f"Port {port} er opptatt av en annen eller utilgjengelig server. "
        f"Stopp den, eller velg en annen port: python3 run.py --port {port + 1 if port < 65535 else 8765}"
    )


def build_frontend(force=False):
    frontend = ROOT / "frontend"
    files = [
        p
        for p in frontend.rglob("*")
        if p.is_file() and not {"node_modules", "dist"} & set(p.relative_to(frontend).parts)
    ]
    digest = hashlib.sha256(
        b"".join(
            p.relative_to(frontend).as_posix().encode() + p.read_bytes() for p in sorted(files)
        )
    ).hexdigest()
    marker = frontend / "dist/.source.sha256"
    if (
        not force
        and marker.exists()
        and marker.read_text() == digest
        and (frontend / "dist/index.html").exists()
    ):
        return
    npm, node = shutil.which("npm"), shutil.which("node")
    if not npm or not node:
        raise RuntimeError("Installer Node.js 24 LTS først. React bygges én gang ved oppsett.")
    version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    parts = tuple(map(int, version.split(".")[:2]))
    if parts < (22, 12):
        raise RuntimeError("Node.js 22.12 eller nyere er nødvendig. Bruk Node.js 24 LTS.")
    print("Klargjør React-appen …", flush=True)
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True)
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)
    marker.write_text(digest)


def main():
    parser = argparse.ArgumentParser(
        description="Start STEM · lokal React-app for stemmeanbefalinger"
    )
    group = parser.add_mutually_exclusive_group()
    for name, help_text in [
        ("setup", "Installer Python-miljø og bygg React-appen"),
        ("doctor", "Kontroller oppsett uten modellkall"),
        ("probe", "Test modelltilgang på en syntetisk kontrollsak uten å lagre den"),
        ("init", "Opprett .env uten å overskrive eksisterende"),
        ("check", "Kjør automatiske tester uten modelltilgang"),
    ]:
        group.add_argument("--" + name, action="store_true", help=help_text)
    group.add_argument("--cli", nargs=argparse.REMAINDER, help="Kjør nbim-flow-kommando")
    parser.add_argument("--dev", action="store_true", help="Installer utviklingsverktøy")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.exit(1, "Python 3.11 eller nyere er nødvendig.\n")
    if not 1024 <= args.port <= 65535:
        parser.error("Velg port mellom 1024 og 65535.")
    launch = not any(
        (
            args.setup,
            args.doctor,
            args.probe,
            args.init,
            args.check,
            args.cli is not None,
        )
    )
    if launch and app_already_running(args.port):
        return 0
    os.chdir(ROOT)
    env = ROOT / ".venv"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("Oppretter lokalt Python-miljø …", flush=True)
        venv.EnvBuilder(with_pip=True).create(env)
    digest = hashlib.sha256(
        (ROOT / "requirements.txt").read_bytes() + (ROOT / "pyproject.toml").read_bytes()
    ).hexdigest()
    marker, dev_marker = env / ".nbim-package.sha256", env / ".nbim-dev-installed"
    if (
        not marker.exists()
        or marker.read_text().strip() != digest
        or (args.dev and not dev_marker.exists())
    ):
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", ".[dev]" if args.dev else "."],
            cwd=ROOT,
            check=True,
        )
        marker.write_text(digest)
        if args.dev:
            dev_marker.touch()
    if args.setup or launch:
        build_frontend()
        # Triage model (artifacts/ is not in git): train once from data/real_votes.csv, ~10 s.
        if (
            not (ROOT / "artifacts/triage/triage_model.joblib").exists()
            and (ROOT / "data/real_votes.csv").exists()
        ):
            print("Trener triagemodellen …", flush=True)
            subprocess.run([str(python), "-m", "nbim_flow", "triage-train"], cwd=ROOT, check=True)
    if args.setup:
        print(
            "Klart. Kjør python3 run.py for å åpne appen på http://127.0.0.1:8765",
            flush=True,
        )
        return 0
    if args.check:
        command = ["-m", "unittest", "discover", "-s", "tests", "-v"]
    elif args.cli is not None:
        command = ["-m", "nbim_flow", *args.cli]
    elif args.doctor or args.probe or args.init:
        command = [
            "-m",
            "nbim_flow",
            "doctor" if args.doctor else "probe" if args.probe else "init-env",
        ]
    else:
        print(f"Åpne http://127.0.0.1:{args.port} · Stopp med Ctrl+C", flush=True)
        command = [
            "-m",
            "uvicorn",
            "nbim_flow.web.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ]
    return subprocess.call([str(python), *command], cwd=ROOT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(getattr(exc, "returncode", 1))
