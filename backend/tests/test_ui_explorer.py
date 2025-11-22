"""Tests for the training agent Explorer UI template."""

from services.training_agent.ui import render_action_index


def test_render_action_includes_token_cards():
    html = render_action_index("http://localhost", None, "google-client-id")
    assert "Google Token" in html
    assert "Garmin Token" in html
    assert "Generate Garmin token" in html
