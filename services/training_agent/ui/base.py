"""Shared UI helpers and static action metadata for the training agent harness."""

from __future__ import annotations

import html
import os
from typing import List, TypedDict

ActionParam = TypedDict(
    "ActionParam",
    {
        "name": str,
        "default": object,
        "description": str,
        "type": str,
        "min": object,
        "max": object,
        "step": object,
    },
    total=False,
)

ActionSpec = TypedDict(
    "ActionSpec",
    {
        "name": str,
        "path": str,
        "description": str,
        "params": List[ActionParam],
    },
    total=False,
)

API_KEY_NAME = os.environ.get("TRAINING_API_KEY_HEADER", "x-api-key")

ACTIONS: List[ActionSpec] = [
    {
        "name": "Health Check",
        "path": "/health",
        "description": "Lightweight probe used by Docker/Kubernetes to confirm the service is running.",
        "params": [],
    },
    {
        "name": "Weekly Summary",
        "path": "/weekly-summary",
        "description": "Aggregated distance, calories, and average resting HR for the requested time window.",
        "params": [
            {
                "name": "days",
                "default": 7,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "Sleep Summary",
        "path": "/sleep-summary",
        "description": "Average nightly sleep, stress, HRV, SpO₂, and stage durations for the time window.",
        "params": [
            {
                "name": "days",
                "default": 7,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "VO2 Trend",
        "path": "/vo2-trend",
        "description": "Latest and average VO₂ max value across the rolling window.",
        "params": [
            {
                "name": "days",
                "default": 30,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "HRV Trend",
        "path": "/hrv-trend",
        "description": "Latest and average overnight HRV values.",
        "params": [
            {
                "name": "days",
                "default": 30,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "Last Run",
        "path": "/last-run",
        "description": "Most recent outdoor, treadmill, or trail running activity with summary metrics, running dynamics, and a run-type label.",
        "params": [],
    },
    {
        "name": "Recovery Score",
        "path": "/recovery-score",
        "description": "Latest body battery change and sleep stress metrics.",
        "params": [],
    },
    {
        "name": "Training Log",
        "path": "/training-log",
        "description": "Latest activities within the window including distance, speed, HR, training effect, and running dynamics when present.",
        "params": [
            {
                "name": "limit",
                "default": 20,
                "description": "Maximum number of activities to return.",
                "type": "number",
                "min": 1,
            },
            {
                "name": "days",
                "default": 42,
                "description": "Look-back window for activities (must be >= 1).",
                "type": "number",
                "min": 1,
            },
        ],
    },
    {
        "name": "Training Load Focus",
        "path": "/training-load",
        "description": "Latest low/high aerobic and anaerobic load values.",
        "params": [
            {
                "name": "days",
                "default": 14,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "Running Dynamics",
        "path": "/running-dynamics",
        "description": "Most recent advanced running dynamics such as cadence, stride, and contact time.",
        "params": [
            {
                "name": "days",
                "default": 30,
                "description": "Number of days to include when searching for the latest run.",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "Recovery Time",
        "path": "/recovery-time",
        "description": "Latest prescribed recovery period from Training Status.",
        "params": [
            {
                "name": "days",
                "default": 7,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "Sleep Metrics",
        "path": "/sleep-metrics",
        "description": "Most recent sleep stage durations, resting HR, and score.",
        "params": [
            {
                "name": "days",
                "default": 7,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "Stress & Battery",
        "path": "/stress-battery",
        "description": "Combined stress percentage and body battery charge/drain metrics.",
        "params": [
            {
                "name": "days",
                "default": 7,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "Lactate Threshold",
        "path": "/lactate-threshold",
        "description": "Most recent threshold heart rate and pace.",
        "params": [],
    },
    {
        "name": "Race Predictions",
        "path": "/race-predictions",
        "description": "Latest estimated finish times for common race distances.",
        "params": [
            {
                "name": "days",
                "default": 30,
                "description": "Number of days to include (must be >= 1).",
                "type": "number",
                "min": 1,
            }
        ],
    },
    {
        "name": "Race Schedule",
        "path": "/race-schedule",
        "description": "Upcoming calendar items with location and start time.",
        "params": [
            {
                "name": "limit",
                "default": 5,
                "description": "Maximum number of future events to return.",
                "type": "number",
                "min": 1,
            },
            {
                "name": "days",
                "default": 365,
                "description": "Look-ahead window for calendar items (must be >= 1).",
                "type": "number",
                "min": 1,
            },
        ],
    },
]


def render_field(param: ActionParam) -> str:
    """Render a single harness form field."""
    input_type = html.escape(str(param.get("type", "text")))
    default = html.escape(str(param.get("default", "")))
    name = html.escape(str(param["name"]))
    desc = html.escape(str(param.get("description", "")))
    attrs = []
    for attr_name in ("min", "max", "step"):
        if attr_name in param:
            attrs.append(f" {attr_name}='{param[attr_name]}'")
    attr_str = "".join(attrs)
    return (
        "<label class='field'>"
        f"<span>{name}</span>"
        f"<input type='{input_type}' name='{name}' value='{default}'{attr_str}>"
        f"<small>{desc}</small>"
        "</label>"
    )


def render_action_card(spec: ActionSpec) -> str:
    """Build the markup for a single action card."""
    path = html.escape(str(spec["path"]))
    name = html.escape(str(spec["name"]))
    description = html.escape(str(spec.get("description", "")))
    params_obj = spec.get("params") or []
    params_list = params_obj if isinstance(params_obj, list) else []
    if params_list:
        fields = "".join(render_field(p) for p in params_list)
        form_html = f"""
            <form class="api-form" data-endpoint="{path}">
                <div class="fields">
                    {fields}
                </div>
                <div class="form-actions">
                    <button type="submit">Send via harness</button>
                    <a href="{path}" target="_blank" rel="noreferrer">Open without header</a>
                </div>
            </form>
        """
    else:
        form_html = f"""
            <p class="no-params">No query parameters</p>
            <div class="form-actions no-fields">
                <button class="button-link ghost no-param" data-endpoint="{path}" type="button">Send via harness</button>
                <a class="button-link" href="{path}" target="_blank" rel="noreferrer">Open without header</a>
            </div>
        """
    return f"""
    <section class="card">
        <header>
            <h2>{name}</h2>
            <code>GET {path}</code>
        </header>
        <p class="description">{description}</p>
        {form_html}
    </section>
    """


__all__ = ["ACTIONS", "API_KEY_NAME", "ActionParam", "ActionSpec", "render_action_card", "render_field"]
