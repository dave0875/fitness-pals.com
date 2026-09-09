"""Contracts that keep CI optimization from reducing validation coverage."""

from __future__ import annotations

from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (REPOSITORY_ROOT / ".github/workflows/ci-cd.yml").read_text(
    encoding="utf-8"
)
TEST_JOB = WORKFLOW.split("  test:\n", maxsplit=1)[1].split(
    "  deploy-dev:\n", maxsplit=1
)[0]


def test_ci_summary_keeps_the_exact_validation_matrix():
    summary_match = re.search(
        r'"checks": \{(?P<checks>.*?)\n\s+\}', TEST_JOB, flags=re.DOTALL
    )
    assert summary_match is not None
    keys = set(re.findall(r'"([a-z_]+)":', summary_match.group("checks")))

    assert keys == {
        "backend_tests",
        "backend_lint",
        "backend_typecheck",
        "frontend_build",
        "frontend_tests",
        "frontend_lint",
        "docker_build",
        "compose_config",
    }


def test_dependency_caches_follow_both_lockfile_sets():
    assert "cache: pip" in TEST_JOB
    assert "backend/requirements.txt" in TEST_JOB
    assert "services/training_agent/requirements.txt" in TEST_JOB
    assert "services/training_agent/requirements-dev.txt" in TEST_JOB
    assert "uses: actions/setup-node@v6" in TEST_JOB
    assert "cache: npm" in TEST_JOB
    assert "cache-dependency-path: frontend/package-lock.json" in TEST_JOB


def test_deployable_images_use_buildkit_and_run_concurrently():
    assert "DOCKER_BUILDKIT: 1" in TEST_JOB
    assert "BUILDKIT_PROGRESS: plain" in TEST_JOB
    assert "uses: docker/setup-buildx-action@v3" in TEST_JOB
    assert "start_image_build" in TEST_JOB
    assert "wait_for_image_build" in TEST_JOB
    assert "image_build_pids" in TEST_JOB
    assert re.search(r"\) &\n\s+image_build_pids", TEST_JOB)

    for dockerfile in (
        "frontend/Dockerfile",
        "backend/Dockerfile",
        "services/training_agent/Dockerfile",
    ):
        assert dockerfile in TEST_JOB


def test_frontend_production_build_runs_once_inside_the_deployable_image():
    frontend_dockerfile = (REPOSITORY_ROOT / "frontend/Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "RUN npm run build" in frontend_dockerfile
    assert "npm run build --if-present" not in TEST_JOB
    assert 'frontend_build_status="$frontend_image_status"' in TEST_JOB


def test_root_build_context_contains_only_training_agent_sources():
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert dockerignore.splitlines() == [
        "**",
        "!services/",
        "!services/training_agent/",
        "!services/training_agent/**",
    ]


def test_test_lint_typecheck_migration_and_compose_commands_are_unchanged():
    required_commands = (
        "docker compose --env-file .env.production config -q",
        "COMPOSE_FILE=compose.yml:compose.dev.yml",
        "python -m compileall backend services/training_agent",
        "ruff check --select=E9,F63,F7,F82",
        "mypy --ignore-missing-imports --implicit-optional",
        "alembic upgrade head --sql",
        "pytest -vv --maxfail=1 --disable-warnings --cov=backend",
        "npm run lint --if-present",
        "npm test --if-present -- --watch=false",
    )

    for command in required_commands:
        assert command in TEST_JOB
