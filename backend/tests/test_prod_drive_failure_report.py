"""Tests for redacted production Drive failure aggregation helpers."""

from app.ops.prod_drive_failure_report import _normalized_message


def test_normalized_message_redacts_object_name_uuid_and_email():
    message = (
        "bad activity.fit user@example.com "
        "550e8400-e29b-41d4-a716-446655440000"
    )
    assert _normalized_message(message, "activity.fit") == (
        "bad <object> <email> <uuid>"
    )
