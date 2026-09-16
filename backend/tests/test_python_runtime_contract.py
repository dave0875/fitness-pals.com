"""Contracts for the repository-wide Python runtime baseline."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYTHON_VERSION = "3.14"


def _read(path: str) -> str:
    return (REPOSITORY_ROOT / path).read_text(encoding="utf-8")


def test_repository_and_deployable_images_use_python_314():
    assert _read(".python-version").strip() == PYTHON_VERSION

    for dockerfile in (
        "backend/Dockerfile",
        "services/training_agent/Dockerfile",
    ):
        assert _read(dockerfile).splitlines()[0] == f"FROM python:{PYTHON_VERSION}-slim"


def test_ci_lint_and_typecheck_target_python_314():
    workflow = _read(".github/workflows/ci-cd.yml")

    assert workflow.count('python-version: "3.14"') == 3
    assert 'python-version: "3.11"' not in workflow
    assert "--target-version=py314" in workflow
    assert "python_version = 3.14" in _read("mypy.ini")


def test_python_314_compatible_dependency_floors_are_pinned():
    backend_requirements = _read("backend/requirements.txt").splitlines()
    training_requirements = _read(
        "services/training_agent/requirements.txt"
    ).splitlines()

    assert "pydantic[email]==2.13.5" in backend_requirements
    assert "psycopg2-binary==2.9.11" in backend_requirements
    assert "garth==0.8.0" in backend_requirements
    assert "garminconnect==0.3.15" in backend_requirements
    assert "psycopg2-binary==2.9.11" in training_requirements
