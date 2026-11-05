"""Local immutable model runs and an atomic active-model pointer."""

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .files import atomic_json


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register_run(working, destination, metadata):
    working, destination = Path(working), Path(destination)
    _archive_legacy(destination)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    folder = destination / "runs" / run_id
    folder.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "files": {p.name: sha256(p) for p in working.iterdir() if p.is_file()},
    }
    atomic_json(working / "manifest.json", manifest)
    shutil.move(str(working), str(folder))
    activate_run(destination, run_id)
    return manifest


def _archive_legacy(destination):
    names = ("model.joblib", "report.json", "test_predictions.csv")
    if (destination / "active.json").exists() or not all(
        (destination / name).is_file() for name in names
    ):
        return
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-legacy"
    folder = destination / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(destination / name, folder / name)
    atomic_json(
        folder / "manifest.json",
        {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"legacy": True, "note": "Bevart før innføring av modellregisteret."},
            "files": {name: sha256(folder / name) for name in names},
        },
    )
    return run_id


def adopt_legacy_model(destination):
    """Preserve and register the current model without retraining or changing it."""
    run_id = _archive_legacy(Path(destination))
    if run_id:
        activate_run(destination, run_id)
    return run_id


def verify_run(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest.get("files"), dict) or "model.joblib" not in manifest["files"]:
        raise ValueError("Ugyldig modellmanifest.")
    for name, expected in manifest["files"].items():
        if Path(name).name != name or sha256(folder / name) != expected:
            raise ValueError(
                "Modellfilene er endret eller skadet. Velg en intakt kjøring eller tren på nytt."
            )
    return manifest


def activate_run(destination, run_id):
    destination = Path(destination)
    if not run_id or Path(run_id).name != run_id:
        raise ValueError("Ugyldig modellkjørings-ID.")
    folder = destination / "runs" / run_id
    verify_run(folder)
    # Convenience copies keep the existing IDE paths usable. Readers use the
    # active pointer, which changes only after all files have been published.
    for name in ("model.joblib", "report.json", "test_predictions.csv"):
        fd, temporary = tempfile.mkstemp(dir=destination, prefix=".publish-")
        os.close(fd)
        try:
            shutil.copyfile(folder / name, temporary)
            os.replace(temporary, destination / name)
        finally:
            Path(temporary).unlink(missing_ok=True)
    atomic_json(destination / "active.json", {"run_id": run_id})


def resolve_model(path):
    path = Path(path)
    folder = path if path.is_dir() else path.parent
    pointer = folder / "active.json"
    if pointer.exists():
        run_id = json.loads(pointer.read_text(encoding="utf-8"))["run_id"]
        if Path(run_id).name != run_id:
            raise ValueError("Ugyldig aktiv modellpeker.")
        folder = folder / "runs" / run_id
        verify_run(folder)
        return folder / "model.joblib"
    location = path / "model.joblib" if path.is_dir() else path
    if (location.parent / "manifest.json").exists():
        verify_run(location.parent)
    return location


def list_runs(destination):
    root = Path(destination)
    pointer = root / "active.json"
    active = json.loads(pointer.read_text())["run_id"] if pointer.exists() else None
    result = []
    for path in sorted((root / "runs").glob("*/manifest.json"), reverse=True):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        result.append(dict(manifest, active=manifest["run_id"] == active))
    return result


def read_report(destination):
    location = resolve_model(destination)
    return json.loads((location.parent / "report.json").read_text(encoding="utf-8"))
