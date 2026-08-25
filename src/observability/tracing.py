"""Observability layer — OpenTelemetry spans + LangSmith integration.

Every agent node execution emits an OTEL span with:
  - node name, phase, duration
  - token usage (prompt / completion / total)
  - tool calls made and their latencies
  - LangGraph thread_id and run_id for cross-reference

LangSmith is enabled transparently via env vars:
  LANGCHAIN_TRACING_V2=true
  LANGCHAIN_API_KEY=ls__...
  LANGCHAIN_PROJECT=gcb-crisis-squad
"""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from functools import wraps
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.config import settings

# ---------------------------------------------------------------------------
# In-memory exporter — makes spans available to the dashboard API without
# needing a running collector. In production, swap for OTLP exporter.
# ---------------------------------------------------------------------------
_memory_exporter = InMemorySpanExporter()

_resource = Resource.create(
    {
        "service.name": "gcb-crisis-squad",
        "service.version": "0.1.0",
        "deployment.environment": "demo" if settings.demo_mode else "production",
    }
)

_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(BatchSpanProcessor(_memory_exporter))
# Console export is opt-in (OTEL_CONSOLE_EXPORT=true). It used to be tied to
# DEMO_MODE, which flooded the demo's stdout with span JSON and made the server
# log unreadable. Spans are always available at GET /metrics/traces.
if os.getenv("OTEL_CONSOLE_EXPORT", "").lower() in ("1", "true", "yes"):
    _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

trace.set_tracer_provider(_provider)
tracer = trace.get_tracer("gcb.crisis_squad")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_finished_spans() -> list[dict]:
    """Return all finished spans as serialisable dicts — used by dashboard."""
    spans = []
    for span in _memory_exporter.get_finished_spans():
        ctx = span.get_span_context()
        spans.append(
            {
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
                "name": span.name,
                "start_time_ms": span.start_time // 1_000_000,
                "end_time_ms": span.end_time // 1_000_000,
                "duration_ms": (span.end_time - span.start_time) // 1_000_000,
                "status": span.status.status_code.name,
                "attributes": dict(span.attributes or {}),
            }
        )
    return sorted(spans, key=lambda s: s["start_time_ms"])


@contextmanager
def agent_span(
    node_name: str,
    incident_id: str,
    thread_id: str = "",
    extra: dict | None = None,
) -> Generator[Any, None, None]:
    """Context manager — wraps a graph node execution in an OTEL span."""
    with tracer.start_as_current_span(f"agent/{node_name}") as span:
        span.set_attribute("gcb.node", node_name)
        span.set_attribute("gcb.incident_id", incident_id)
        span.set_attribute("gcb.thread_id", thread_id)
        if extra:
            for k, v in extra.items():
                span.set_attribute(f"gcb.{k}", str(v))
        t0 = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise
        finally:
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            span.set_attribute("gcb.duration_ms", elapsed)


def instrument_tool(tool_name: str):
    """Decorator — wraps a LangChain tool call in an OTEL span."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(f"tool/{tool_name}") as span:
                span.set_attribute("gcb.tool", tool_name)
                t0 = time.perf_counter()
                try:
                    result = fn(*args, **kwargs)
                    span.set_attribute("gcb.result_len", len(str(result)))
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    raise
                finally:
                    span.set_attribute(
                        "gcb.duration_ms", round((time.perf_counter() - t0) * 1000, 1)
                    )

        return wrapper

    return decorator


@contextmanager
def span(name: str, **attributes: Any) -> Generator[Any, None, None]:
    """Generic OTEL span helper.

    Thin wrapper used by graph nodes that do not need the full agent_span
    contract. Attributes are namespaced under `gcb.` and stringified.
    """
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(f"gcb.{key}", str(value))
        t0 = time.perf_counter()
        try:
            yield current
        except Exception as exc:
            current.record_exception(exc)
            current.set_status(trace.StatusCode.ERROR, str(exc))
            raise
        finally:
            current.set_attribute("gcb.duration_ms", round((time.perf_counter() - t0) * 1000, 1))
