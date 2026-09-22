"""Shared Garmin FIT SDK decoding helpers."""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

from garmin_fit_sdk import Decoder, Stream


def _first_number(value: Any, default: float) -> float:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _scale_developer_value(value: Any, *, scale: Any, offset: Any) -> Any:
    if isinstance(value, list):
        return [
            _scale_developer_value(item, scale=scale, offset=offset)
            for item in value
        ]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    divisor = _first_number(scale, 1.0)
    subtract = _first_number(offset, 0.0)
    if divisor == 0:
        divisor = 1.0
    return (float(value) / divisor) - subtract


def decode_fit_bytes(
    content: bytes,
) -> tuple[Mapping[str, Any], dict[Any, dict[str, Any]]]:
    """Decode FIT bytes and retain developer-field metadata for normalization."""
    if not content:
        raise ValueError("FIT content is empty")

    field_descriptions: dict[Any, dict[str, Any]] = {}

    def capture_field_description(
        key: Any,
        _developer_data_id: dict[str, Any],
        description: dict[str, Any],
    ) -> None:
        field_descriptions[key] = description

    stream = Stream.from_bytes_io(io.BytesIO(content))
    try:
        decoder = Decoder(stream)
        if not decoder.is_fit():
            raise ValueError("Content is not a valid FIT file")
        messages, errors = decoder.read(
            field_description_listener=capture_field_description
        )
        if errors:
            error = errors[0]
            if isinstance(error, Exception):
                raise error
            raise RuntimeError(str(error))
        return messages, field_descriptions
    finally:
        stream.close()


def normalized_developer_fields(
    message: Mapping[str, Any],
    field_descriptions: Mapping[Any, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return developer fields using their FIT names and declared scaling."""
    raw_fields = message.get("developer_fields")
    if not isinstance(raw_fields, Mapping):
        return {}

    normalized: dict[str, Any] = {}
    for key, raw_value in raw_fields.items():
        description = field_descriptions.get(key, {})
        raw_name = description.get("name")
        name = str(raw_name).strip() if raw_name not in (None, "") else f"developer_{key}"
        value = _scale_developer_value(
            raw_value,
            scale=description.get("scale"),
            offset=description.get("offset"),
        )
        normalized[name.lower().replace(" ", "_")] = value
    return normalized
