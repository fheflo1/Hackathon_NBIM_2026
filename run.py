"""Cross-platform entry point: set up once, then launch CLI or dashboard."""

import argparse
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Start NBIM lokalt med demo eller egen modell")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--setup", action="store_true", help="Installer lokalt miljø og src-pakken")
    group.add_argument("--doctor", action="store_true", help="Kontroller oppsett uten modellkall")
    group.add_argument(
        "--probe", action="store_true", help="Test to faktiske modellkall på syntetiske data"
    )
    group.add_argument(
        "--init", action="store_true", help="Opprett .env uten å overskrive eksisterende"
    )
    group.add_argument(
        "--demo", action="store_true", help="Reproduser demo og modellbaseline uten LLM-kall"
    )
    group.add_argument(
        "--check", action="store_true", help="Kjør alle tester uten nettverk eller ekte modellkall"
    )
    group.add_argument("--cli", nargs=argparse.REMAINDER, help="Kjør en nbim-flow-kommando")
    parser.add_argument(
        "--dev", action="store_true", help="Installer Ruff og coverage for utvikling"
    )
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.exit(1, "Python 3.11 eller nyere er nødvendig.\n")
    os.chdir(ROOT)
    env = ROOT / ".venv"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("Oppretter lokalt Python-miljø …", flush=True)
        venv.EnvBuilder(with_pip=True).create(env)
    digest = hashlib.sha256(
        (ROOT / "requirements.txt").read_bytes() + (ROOT / "pyproject.toml").read_bytes()
    ).hexdigest()
    marker = env / ".nbim-package.sha256"
    dev_marker = env / ".nbim-dev-installed"
    if (
        not marker.exists()
        or marker.read_text().strip() != digest
        or (args.dev and not dev_marker.exists())
    ):
        print("Installerer prosjektet og nødvendige biblioteker …", flush=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", ".[dev]" if args.dev else "."],
            cwd=ROOT,
            check=True,
        )
        marker.write_text(digest)
        if args.dev:
            dev_marker.touch()
    if args.setup:
        print("Klart. Kjør python3 run.py --doctor eller python3 run.py for dashboard.", flush=True)
        return 0
    if args.check:
        command = ["-m", "unittest", "discover", "-s", "tests", "-v"]
    elif args.cli is not None:
        command = ["-m", "nbim_flow", *args.cli]
    elif args.doctor or args.probe or args.init or args.demo:
        name = (
            "doctor"
            if args.doctor
            else "probe"
            if args.probe
            else "init-env"
            if args.init
            else "demo"
        )
        command = ["-m", "nbim_flow", name]
    else:
        command = ["-m", "streamlit", "run", str(ROOT / "app.py")]
    return subprocess.call([str(python), *command], cwd=ROOT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
