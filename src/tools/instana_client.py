"""Shared Instana REST API client.

Single source of truth for all Instana HTTP communication.
Both tool modules import from here — no duplication.
"""

from __future__ import annotations

from datetime import UTC, datetime

import requests
from requests import Response

from src.config import settings

_TIMEOUT = 30
# Baseline window = same duration, 7 days earlier
BASELINE_OFFSET_MS = 7 * 24 * 3600 * 1000

# ---------------------------------------------------------------------------
# Failure-pattern thresholds — exposed in every payload for auditability.
# These are editorial decisions, not Instana data.
# ---------------------------------------------------------------------------
THRESHOLDS: dict[str, float] = {
    "high_error_rate_pct": 50.0,
    "low_error_rate_pct": 10.0,
    "latency_ratio_high": 2.0,  # p99_during / p99_baseline ≥ this → elevated latency
    "latency_ratio_low": 0.5,  # p99_during / p99_baseline < this → fail-fast pattern
    "calls_ratio_stable_min": 0.8,
    "calls_ratio_stable_max": 1.2,
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"apiToken {settings.instana_api_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def call(method: str, path: str, **kwargs) -> dict:
    """Single HTTP call to Instana. Raises on any failure — no silent fallback."""
    resp: Response = requests.request(
        method,
        f"{settings.instana_base_url}{path}",
        headers=_headers(),
        timeout=_TIMEOUT,
        **kwargs,
    )
    resp.raise_for_status()
    return resp.json()


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def last(series: list | None):
    """Extract last value from an Instana time series [[ts, value], ...]."""
    if not series:
        return None
    try:
        return series[-1][1]
    except (IndexError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Metric queries
# ---------------------------------------------------------------------------


def service_metrics(service_id: str, to_ms: int, window_ms: int) -> dict:
    """Aggregate metrics for one service in a time window.

    Instana's API accepts at most 5 metrics per call — two batches required.
    """

    def _query(metrics: list[dict]) -> dict:
        body = {
            "timeFrame": {"to": to_ms, "windowSize": window_ms},
            "group": {"groupbyTag": "service.name"},
            "tagFilterExpression": {
                "type": "TAG_FILTER",
                "name": "service.id",
                "operator": "EQUALS",
                "stringValue": service_id,
                "value": service_id,
                "entity": "DESTINATION",
            },
            "metrics": metrics,
            "pagination": {"retrievalSize": 5},
        }
        data = call("POST", "/api/application-monitoring/analyze/call-groups", json=body)
        items = data.get("items", [])
        return items[0].get("metrics", {}) if items else {}

    m = _query(
        [
            {"metric": "latency", "aggregation": "P99"},
            {"metric": "latency", "aggregation": "P50"},
            {"metric": "latency", "aggregation": "MEAN"},
            {"metric": "calls", "aggregation": "SUM"},
            {"metric": "errors", "aggregation": "MEAN"},
        ]
    )
    m.update(_query([{"metric": "erroneousCalls", "aggregation": "SUM"}]))

    calls = last(m.get("calls.sum"))
    erroneous = last(m.get("erroneousCalls.sum"))
    duration_s = window_ms / 1000

    return {
        "calls_total": calls,
        "erroneous_calls_total": erroneous,
        "error_rate_pct": round(erroneous / calls * 100, 2) if calls else None,
        "calls_per_minute": round(calls / (duration_s / 60), 2) if calls and duration_s else None,
        "latency_p99_ms": last(m.get("latency.p99")),
        "latency_p50_ms": last(m.get("latency.p50")),
        "latency_mean_ms": last(m.get("latency.mean")),
    }


def app_services_metrics(app_id: str, to_ms: int, window_ms: int) -> dict[str, dict]:
    """Metrics for every service in an application. Returns {service_name: metrics}."""
    body = {
        "timeFrame": {"to": to_ms, "windowSize": window_ms},
        "group": {"groupbyTag": "service.name"},
        "tagFilterExpression": {
            "type": "TAG_FILTER",
            "name": "application.id",
            "operator": "EQUALS",
            "stringValue": app_id,
            "value": app_id,
            "entity": "DESTINATION",
        },
        "metrics": [
            {"metric": "calls", "aggregation": "SUM"},
            {"metric": "erroneousCalls", "aggregation": "SUM"},
            {"metric": "latency", "aggregation": "P99"},
        ],
        "pagination": {"retrievalSize": 50},
    }
    data = call("POST", "/api/application-monitoring/analyze/call-groups", json=body)

    out: dict[str, dict] = {}
    for item in data.get("items", []):
        m = item.get("metrics", {})
        calls = last(m.get("calls.sum"))
        erroneous = last(m.get("erroneousCalls.sum"))
        out[item.get("name")] = {
            "calls": calls,
            "erroneous_calls": erroneous,
            "error_rate_pct": round(erroneous / calls * 100, 2) if calls else None,
            "latency_p99_ms": last(m.get("latency.p99")),
        }
    return out


def resolve_services(app_id: str, to_ms: int, window_ms: int) -> dict[str, str]:
    """Return {service_id: label} map for an application."""
    data = call(
        "GET",
        f"/api/application-monitoring/applications;id={app_id}/services"
        f"?to={to_ms}&windowSize={window_ms}&pageSize=200",
    )
    return {s.get("id"): s.get("label") for s in data.get("items", [])}


def resolve_application(app_id: str, to_ms: int, window_ms: int) -> str | None:
    data = call(
        "GET",
        f"/api/application-monitoring/applications?to={to_ms}&windowSize={window_ms}&pageSize=200",
    )
    for a in data.get("items", []):
        if a.get("id") == app_id:
            return a.get("label")
    return None


# ---------------------------------------------------------------------------
# Pattern classifier
# ---------------------------------------------------------------------------


def diagnose(during: dict, baseline: dict) -> dict:
    """Classify failure pattern by comparing incident metrics vs. baseline.

    Returns three layers:
      measured   — raw API values, no transformation
      derived    — pure arithmetic (ratios, deltas) on measured values
      assessment — editorial judgment with thresholds explicitly listed
    """
    T = THRESHOLDS
    err = during.get("error_rate_pct")
    lat = during.get("latency_p99_ms")
    lat_base = baseline.get("latency_p99_ms")
    calls = during.get("calls_total")
    calls_base = baseline.get("calls_total")

    measured = {
        "error_rate_pct_during": err,
        "latency_p99_ms_during": lat,
        "latency_p99_ms_baseline": lat_base,
        "calls_total_during": calls,
        "calls_total_baseline": calls_base,
    }

    lat_ratio = round(lat / lat_base, 3) if lat and lat_base else None
    calls_ratio = round(calls / calls_base, 3) if calls and calls_base else None
    derived = {"latency_p99_ratio": lat_ratio, "calls_volume_ratio": calls_ratio}

    if err is None or lat is None or lat_base is None:
        return {
            "measured": measured,
            "derived": derived,
            "assessment": {
                "pattern": "INDETERMINATE",
                "reasoning": "Insufficient metrics to classify.",
                "recommendation": "Verify Instana metric collection for this service.",
                "thresholds_used": T,
            },
        }

    if (
        err >= T["high_error_rate_pct"]
        and lat_ratio is not None
        and lat_ratio < T["latency_ratio_low"]
    ):
        pattern = "FAIL_FAST"
        reasoning = (
            f"Error rate {err}% with p99 latency {lat}ms vs baseline {lat_base}ms "
            f"({lat_ratio:.2f}x). Calls are being rejected immediately — typical of "
            "auth/config failure or dependency returning instant error. "
            "NOT resource exhaustion (that would increase latency, not reduce it)."
        )
        recommendation = (
            "Investigate service config and credentials against its immediate dependencies. "
            "Compare current manifest with the one in place before the event started. "
            "Rollback only makes sense if a config change correlates with the start time."
        )
    elif (
        err >= T["high_error_rate_pct"]
        and lat_ratio is not None
        and lat_ratio > T["latency_ratio_high"]
    ):
        pattern = "SATURATION"
        reasoning = (
            f"Error rate {err}% with p99 rising from {lat_base}ms to {lat}ms ({lat_ratio:.2f}x). "
            "Errors combined with slowness indicate resource exhaustion: connection pool, "
            "memory, threads, or an overloaded downstream dependency."
        )
        recommendation = (
            "Check service resource utilization and downstream dependency health. "
            "Evaluate horizontal scaling and pool limits."
        )
    elif (
        err < T["low_error_rate_pct"]
        and lat_ratio is not None
        and lat_ratio > T["latency_ratio_high"]
    ):
        pattern = "LATENCY_DEGRADATION"
        reasoning = (
            f"p99 latency rose from {lat_base}ms to {lat}ms ({lat_ratio:.2f}x) "
            f"while error rate is still low ({err}%). Progressive degradation."
        )
        recommendation = (
            "Act before latency crosses timeout thresholds and triggers cascading errors."
        )
    else:
        pattern = "MIXED"
        reasoning = f"Error rate {err}%, p99 {lat}ms vs baseline {lat_base}ms. Does not fit a single pattern."
        recommendation = "Manual analysis of timeline and dependencies required."

    if calls_ratio is not None:
        if T["calls_ratio_stable_min"] <= calls_ratio <= T["calls_ratio_stable_max"]:
            reasoning += (
                f" Call volume stable ({calls} vs {calls_base}, {calls_ratio:.2f}x): "
                "traffic kept arriving but the service stopped serving."
            )
        else:
            reasoning += f" Call volume at {calls_ratio:.2f}x baseline ({calls} vs {calls_base})."

    return {
        "measured": measured,
        "derived": derived,
        "assessment": {
            "pattern": pattern,
            "reasoning": reasoning,
            "recommendation": recommendation,
            "thresholds_used": T,
        },
    }
