"""Regression tests for deploy env normalization."""

from __future__ import annotations

from pathlib import Path

from scripts import merge_env


def write_env(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_merge_env_derives_runtrainer_postgres_fields_from_database_url(
    tmp_path: Path,
) -> None:
    base_env = tmp_path / "base.env"
    overlay_env = tmp_path / "overlay.env"
    merged_env = tmp_path / "merged.env"

    write_env(
        base_env,
        [
            "RUNTRAINER_DATABASE_URL=postgresql://runner:secret@db.internal:5432/runtrainer",
            "RUNTRAINER_JWT_SECRET=test-secret",
        ],
    )
    write_env(
        overlay_env,
        [
            "AUTHENTIK_SECRET_KEY=authentik-secret",
        ],
    )

    merge_env.merge_env_files(merged_env, [base_env, overlay_env])

    merged = merged_env.read_text(encoding="utf-8")

    assert "RUNTRAINER_POSTGRES_USER=runner\n" in merged
    assert "RUNTRAINER_POSTGRES_PASSWORD=secret\n" in merged
    assert "RUNTRAINER_POSTGRES_DB=runtrainer\n" in merged


def test_merge_env_preserves_explicit_postgres_fields(tmp_path: Path) -> None:
    base_env = tmp_path / "base.env"
    merged_env = tmp_path / "merged.env"

    write_env(
        base_env,
        [
            "RUNTRAINER_DATABASE_URL=postgresql://runner:secret@db.internal:5432/runtrainer",
            "RUNTRAINER_POSTGRES_USER=explicit-user",
            "RUNTRAINER_POSTGRES_PASSWORD=explicit-password",
            "RUNTRAINER_POSTGRES_DB=explicit-db",
        ],
    )

    merge_env.merge_env_files(merged_env, [base_env])

    merged = merged_env.read_text(encoding="utf-8")

    assert "RUNTRAINER_POSTGRES_USER=explicit-user\n" in merged
    assert "RUNTRAINER_POSTGRES_PASSWORD=explicit-password\n" in merged
    assert "RUNTRAINER_POSTGRES_DB=explicit-db\n" in merged
