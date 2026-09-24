"""Guard Garmin FIT runtime dependencies and parser cleanup."""

from importlib import import_module
from pathlib import Path


def test_garmin_activity_fit_runtime_dependency_is_importable():
    """Backend startup must have the official Garmin FIT SDK parser path."""
    module = import_module("app.services.garmin.activity_fit")
    sdk = import_module("app.services.garmin.fit_sdk")
    assert module.decode_fit_bytes is sdk.decode_fit_bytes


def test_fitparse_is_not_a_runtime_dependency():
    """The old compatibility parser must not creep back into runtime code."""
    repository_root = Path(__file__).resolve().parents[2]
    requirements = (repository_root / "backend" / "requirements.txt").read_text()
    assert "garmin-fit-sdk==21.217.0" in requirements
    assert "fitparse" not in requirements.lower()

    runtime_paths = [
        repository_root / "backend" / "app",
        repository_root / "scripts",
    ]
    offenders = []
    for root in runtime_paths:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "from fitparse" in text or "import fitparse" in text:
                offenders.append(str(path.relative_to(repository_root)))
    assert offenders == []
