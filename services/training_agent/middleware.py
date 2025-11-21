"""Prometheus instrumentation middleware for the training agent."""

from __future__ import annotations

import time

from fastapi import Request
from prometheus_client import Counter, Histogram

METRICS_NAMESPACE = "training_agent"
REQUEST_COUNTER = Counter(
    f"{METRICS_NAMESPACE}_requests_total",
    "HTTP requests processed",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    f"{METRICS_NAMESPACE}_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path", "status"],
)


async def metrics_middleware(request: Request, call_next):
    """Capture request latency and counts for observability."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route_template = getattr(request.scope.get("route"), "path", request.url.path)
    labels = {
        "method": request.method,
        "path": route_template,
        "status": str(response.status_code),
    }
    REQUEST_COUNTER.labels(**labels).inc()
    REQUEST_LATENCY.labels(**labels).observe(elapsed)
    return response
