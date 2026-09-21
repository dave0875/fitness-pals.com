"""Guard backend startup dependencies used by Garmin modules."""

from importlib import import_module


def test_garmin_activity_fit_runtime_dependency_is_importable():
    """Backend startup must not fail while activity_fit still uses fitparse."""
    module = import_module("app.services.garmin.activity_fit")
    assert module.FitFile is not None
