"""Instana tools — LangChain @tool wrappers around the shared client.

Uses `src.tools.instana_client` for all HTTP calls.
When DEMO_MODE=true, returns realistic mock data instead of calling Instana.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import requests
from langchain_core.tools import tool

from src.config import settings
from src.tools import instana_client as ic


@tool
def instana_get_incident_details(incident_id: str) -> str:
    """Fetch complete diagnosis for a real IBM Instana incident.

    Returns exclusively measured data: incident window, root cause identified
    by the platform (Probable Cause Analysis), service metrics during the failure,
    7-day baseline, impacted upstream services, and failure pattern classification.

    Args:
        incident_id: Instana event ID (e.g. QKTtAivDTAaKvCGqvQOWpA)
    """
    if settings.demo_mode:
        from src.demo.mocks import mock_instana_get_incident_details

        return mock_instana_get_incident_details(incident_id)

    try:
        ev = ic.call("GET", f"/api/events/{incident_id}")

        start_ms = ev.get("start")
        end_ms = ev.get("end")
        state = ev.get("state", "unknown")
        service_id = ev.get("serviceId")
        app_id = ev.get("applicationId")

        if end_ms and state != "open":
            ref_to_ms = end_ms
            window_ms = end_ms - start_ms
        else:
            ref_to_ms = ic.now_ms()
            window_ms = ref_to_ms - start_ms
        duration_min = max(int(window_ms / 60000), 1)

        sev_raw = ev.get("severity")
        severity = {10: "CRITICAL", 5: "WARNING", 3: "INFO"}.get(sev_raw, f"SEV-{sev_raw}")

        app_label = ic.resolve_application(app_id, ref_to_ms, window_ms) if app_id else None
        id2name = ic.resolve_services(app_id, ref_to_ms, window_ms) if app_id else {}

        # Root cause — Instana Probable Cause Analysis
        pc = ev.get("probableCause") or {}
        root = (pc.get("currentRootCause") or [{}])[0]

        root_path = [
            {
                "type": hop.get("pluginId", "").split(".")[-1],
                "steady_id": hop.get("steadyId"),
                "name": id2name.get(hop.get("steadyId")),
            }
            for hop in root.get("topology", {}).get("shortestPath", [])
        ]

        upstream = []
        for e in root.get("explainability", []):
            cid = e.get("connectedServiceId")
            if cid in ("all", "incoming"):
                continue
            upstream.append(
                {
                    "service_id": cid,
                    "service_name": id2name.get(cid),
                    "calls_through_root_cause": e.get("numCallsInAggregationThroughRC"),
                    "failed_pct_through_root_cause": round(
                        (e.get("percentageFailedThroughRC") or 0) * 100, 1
                    ),
                    "calls_other_paths": e.get("numCallsInAggregationNotThroughRC"),
                    "failed_pct_other_paths": round(
                        (e.get("percentageFailedNotThroughRC") or 0) * 100, 1
                    ),
                }
            )

        aggregate: dict = next(
            (e for e in root.get("explainability", []) if e.get("connectedServiceId") == "all"),
            {},
        )

        during = ic.service_metrics(service_id, ref_to_ms, window_ms) if service_id else {}
        baseline = (
            ic.service_metrics(service_id, ref_to_ms - ic.BASELINE_OFFSET_MS, window_ms)
            if service_id
            else {}
        )
        diagnosis = ic.diagnose(during, baseline)

        # Causal event chain
        related = []
        for r in ev.get("recentEvents", []):
            rid = r.get("eventId")
            try:
                rel = ic.call("GET", f"/api/events/{rid}")
                related.append(
                    {
                        "event_id": rid,
                        "problem": rel.get("problem"),
                        "severity": rel.get("severity"),
                        "start": ic.iso(rel.get("start")),
                        "is_trigger": rid == ev.get("triggeringEventId"),
                    }
                )
            except requests.RequestException:
                related.append({"event_id": rid, "problem": None, "fetch_failed": True})

        result = {
            "status": "OK",
            "incident_id": incident_id,
            "event_state": state.upper(),
            "severity": severity,
            "severity_raw": sev_raw,
            "problem": ev.get("problem"),
            "detail": ev.get("detail"),
            "fix_suggestion_instana": ev.get("fixSuggestion"),
            "affected_service": {
                "name": ev.get("entityLabel"),
                "service_id": service_id,
                "entity_type": ev.get("entityType"),
            },
            "application": {"name": app_label, "application_id": app_id},
            "timeline": {
                "start": ic.iso(start_ms),
                "end": ic.iso(end_ms),
                "duration_minutes": duration_min,
                "duration_human": f"{duration_min // 60}h{duration_min % 60:02d}",
            },
            "root_cause": {
                "identified_by": "Instana Probable Cause Analysis",
                "found": pc.get("found", False),
                "confidence": root.get("probFailure"),
                "path": root_path,
                "calls_through_root_cause": aggregate.get("numCallsInAggregationThroughRC"),
                "failed_pct_through_root_cause": round(
                    (aggregate.get("percentageFailedThroughRC") or 0) * 100, 1
                ),
            },
            "impacted_upstream_services": upstream,
            "metrics_during_incident": during,
            "metrics_baseline_7d_before": baseline,
            "diagnosis": diagnosis,
            "related_events": related,
            "data_provenance": {
                "source": "IBM Instana REST API",
                "all_fields_measured": True,
                "note": (
                    "All values come from Instana queries. Metrics measured in the real "
                    "incident window; baseline in the same window 7 days prior. "
                    "The 'diagnosis' classification is derived from numeric comparison."
                ),
            },
            "queried_at": datetime.now(UTC).isoformat(),
        }

    except requests.HTTPError as exc:
        result = {
            "status": "ERROR",
            "error": f"Instana returned HTTP {exc.response.status_code}",
            "detail": exc.response.text[:500] if exc.response is not None else None,
            "incident_id": incident_id,
        }
    except requests.RequestException as exc:
        result = {"status": "ERROR", "error": f"Network error: {exc}", "incident_id": incident_id}
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "incident_id": incident_id,
        }

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def instana_get_blast_radius(incident_id: str) -> str:
    """Measure incident blast radius: which services in the same application showed
    anomalous error rates during the incident window vs. their own 7-day baseline.

    Args:
        incident_id: Instana event ID (e.g. QKTtAivDTAaKvCGqvQOWpA)
    """
    if settings.demo_mode:
        from src.demo.mocks import mock_instana_get_blast_radius

        return mock_instana_get_blast_radius(incident_id)

    try:
        ev = ic.call("GET", f"/api/events/{incident_id}")

        start_ms = ev.get("start")
        end_ms = ev.get("end")
        state = ev.get("state", "unknown")
        app_id = ev.get("applicationId")

        if end_ms and state != "open":
            to_ms, window_ms = end_ms, end_ms - start_ms
        else:
            to_ms = ic.now_ms()
            window_ms = to_ms - start_ms

        app_label = ic.resolve_application(app_id, to_ms, window_ms) if app_id else None
        during = ic.app_services_metrics(app_id, to_ms, window_ms)
        baseline = ic.app_services_metrics(app_id, to_ms - ic.BASELINE_OFFSET_MS, window_ms)

        T = ic.THRESHOLDS
        services: list[dict] = []
        for name, cur in during.items():
            base = baseline.get(name, {})
            err_now = cur.get("error_rate_pct")
            err_base = base.get("error_rate_pct")
            delta = (
                round(err_now - err_base, 2)
                if err_now is not None and err_base is not None
                else None
            )
            lat_now = cur.get("latency_p99_ms")
            lat_base_v = base.get("latency_p99_ms")
            lat_ratio = round(lat_now / lat_base_v, 3) if lat_now and lat_base_v else None

            _DELTA_THRESHOLD = 5.0  # 5 pp delta = anomaly
            if delta is not None:
                anomalous = delta >= _DELTA_THRESHOLD
                anomaly_reason = f"error_rate_delta={delta}pp >= threshold {_DELTA_THRESHOLD}pp"
            else:
                anomalous = (err_now or 0) >= T["high_error_rate_pct"]
                anomaly_reason = (
                    f"error_rate={err_now}% >= threshold {T['high_error_rate_pct']}% (no baseline)"
                )

            services.append(
                {
                    "service": name,
                    "measured": {
                        "calls": cur.get("calls"),
                        "erroneous_calls": cur.get("erroneous_calls"),
                        "error_rate_pct": err_now,
                        "latency_p99_ms": lat_now,
                        "error_rate_pct_baseline": err_base,
                        "latency_p99_ms_baseline": lat_base_v,
                        "baseline_available": bool(base),
                    },
                    "derived": {"error_rate_delta_pp": delta, "latency_p99_ratio": lat_ratio},
                    "assessment": {"anomalous": anomalous, "anomaly_reason": anomaly_reason},
                }
            )

        anomalous_services = sorted(
            [s for s in services if s["assessment"]["anomalous"]],
            key=lambda s: (
                s["derived"].get("error_rate_delta_pp") or s["measured"].get("error_rate_pct") or 0
            ),
            reverse=True,
        )

        result = {
            "status": "OK",
            "incident_id": incident_id,
            "application": {"name": app_label, "application_id": app_id},
            "window": {
                "start": ic.iso(start_ms),
                "end": ic.iso(end_ms),
                "duration_minutes": max(int(window_ms / 60000), 1),
            },
            "services_analyzed": len(services),
            "services_anomalous": len(anomalous_services),
            "anomaly_criterion": "error_rate_delta >= 5pp vs 7-day baseline (editorial threshold)",
            "anomalous_services": anomalous_services,
            "all_services": sorted(
                services, key=lambda s: s["measured"].get("error_rate_pct") or 0, reverse=True
            ),
            "queried_at": datetime.now(UTC).isoformat(),
        }

    except requests.HTTPError as exc:
        result = {
            "status": "ERROR",
            "error": f"Instana returned HTTP {exc.response.status_code}",
            "detail": exc.response.text[:500] if exc.response is not None else None,
            "incident_id": incident_id,
        }
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "incident_id": incident_id,
        }

    return json.dumps(result, ensure_ascii=False, indent=2)


INSTANA_TOOLS = [instana_get_incident_details, instana_get_blast_radius]
