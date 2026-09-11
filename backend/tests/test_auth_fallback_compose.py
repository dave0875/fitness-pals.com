"""Deployment contract for broker-first authentication."""

from pathlib import Path


def test_direct_google_fallback_is_optional_and_worker_independent():
    compose_text = (Path(__file__).resolve().parents[2] / "compose.yml").read_text(
        encoding="utf-8"
    )
    backend_block, worker_block = compose_text.split("  worker:", maxsplit=1)

    assert "RUNTRAINER_GOOGLE_FALLBACK_ENABLED=${RUNTRAINER_GOOGLE_FALLBACK_ENABLED:-false}" in backend_block
    assert "RUNTRAINER_GOOGLE_CLIENT_ID=${RUNTRAINER_GOOGLE_CLIENT_ID:-}" in backend_block
    assert "RUNTRAINER_GOOGLE_CLIENT_SECRET=${RUNTRAINER_GOOGLE_CLIENT_SECRET:-}" in backend_block
    assert "RUNTRAINER_GOOGLE_REDIRECT_URI=${RUNTRAINER_GOOGLE_REDIRECT_URI:-}" in backend_block
    assert "RUNTRAINER_GOOGLE_CLIENT_ID" not in worker_block
    assert "RUNTRAINER_GOOGLE_CLIENT_SECRET" not in worker_block
    assert "RUNTRAINER_GOOGLE_REDIRECT_URI" not in worker_block


def test_authentik_bootstrap_does_not_receive_direct_google_credentials():
    compose_text = (Path(__file__).resolve().parents[2] / "compose.yml").read_text(
        encoding="utf-8"
    )
    bootstrap_block = compose_text.split("  authentik-bootstrap:", maxsplit=1)[1].split(
        "  frontend:", maxsplit=1
    )[0]

    assert "AUTHENTIK_GOOGLE_CLIENT_ID" in bootstrap_block
    assert "AUTHENTIK_GOOGLE_CLIENT_SECRET" in bootstrap_block
    assert "RUNTRAINER_GOOGLE_CLIENT_ID" not in bootstrap_block
    assert "RUNTRAINER_GOOGLE_CLIENT_SECRET" not in bootstrap_block
