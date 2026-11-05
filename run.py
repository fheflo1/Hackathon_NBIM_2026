"""One-command setup and launch: python3 run.py [--demo | --check]."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Installer og start den lokale NBIM-prototypen")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--demo", action="store_true", help="Reproduser hovedresultatet uten API-nøkkel")
    choice.add_argument("--check", action="store_true", help="Kjør prosjektets tester")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.exit(1, "Python 3.11 eller nyere er nødvendig.\n")
    os.chdir(ROOT)
    environment = ROOT / ".venv"
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.exists():
        print("Oppretter lokalt Python-miljø …", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    requirements = ROOT / "requirements.txt"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = environment / ".nbim-requirements.sha256"
    if not marker.exists() or marker.read_text().strip() != digest:
        print("Installerer nødvendige biblioteker (første kjøring krever internett) …", flush=True)
        subprocess.run([str(interpreter), "-m", "pip", "install", "-r", str(requirements)], check=True)
        marker.write_text(digest)
    if args.demo:
        command = ["-m", "nbim_flow", "demo"]
    elif args.check:
        command = ["-m", "unittest", "discover", "-s", "tests", "-v"]
    else:
        command = ["-m", "streamlit", "run", str(ROOT / "app.py")]
    return subprocess.call([str(interpreter), *command], cwd=ROOT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
