"""Mock data for demo mode.

Todos os valores abaixo são baseados no incidente real da PoC:
    QKTtAivDTAaKvCGqvQOWpA
    Robot-Shop-EKS / mcp-gateway-mcp-stack-mcpgateway.mcp-context-forge
    18/08/2026 13:56 → 21/08/2026 06:39 (3883 min, CLOSED)
"""

INSTANA_INCIDENT_DETAILS = {
    "status": "OK",
    "incident_id": "QKTtAivDTAaKvCGqvQOWpA",
    "event_state": "CLOSED",
    "severity": "CRITICAL",
    "severity_raw": 10,
    "problem": "Erroneous call rate is too high",
    "detail": "The erroneous call rate of the service mcp-gateway has been too high for the last 3883 minutes.",
    "fix_suggestion_instana": "Investigate the service configuration and dependencies.",
    "affected_service": {
        "name": "mcp-gateway-mcp-stack-mcpgateway.mcp-context-forge",
        "service_id": "svc-mcp-gateway-001",
        "entity_type": "SERVICE",
    },
    "application": {
        "name": "Robot-Shop-EKS",
        "application_id": "app-robot-shop-001",
    },
    "timeline": {
        "start": "2026-08-18T13:56:00+00:00",
        "end": "2026-08-21T06:39:00+00:00",
        "duration_minutes": 3883,
        "duration_human": "64h43",
    },
    "root_cause": {
        "identified_by": "Instana Probable Cause Analysis",
        "found": True,
        "confidence": 0.97,
        "path": [
            {"type": "service", "steady_id": "svc-mcp-gateway-001", "name": "mcp-gateway"},
        ],
        "calls_through_root_cause": 690,
        "failed_pct_through_root_cause": 100.0,
        "calls_other_paths": 0,
        "failed_pct_other_paths": 0.0,
    },
    "impacted_upstream_services": [
        {
            "service_id": "svc-frontend-001",
            "service_name": "frontend",
            "calls_through_root_cause": 690,
            "failed_pct_through_root_cause": 100.0,
            "calls_other_paths": 0,
            "failed_pct_other_paths": 0.0,
        }
    ],
    "metrics_during_incident": {
        "calls_total": 690,
        "erroneous_calls_total": 690,
        "error_rate_pct": 100.0,
        "calls_per_minute": 0.18,
        "latency_p99_ms": 8,
        "latency_p50_ms": 4,
        "latency_mean_ms": 5,
    },
    "metrics_baseline_7d_before": {
        "calls_total": 710,
        "erroneous_calls_total": 12,
        "error_rate_pct": 1.69,
        "calls_per_minute": 0.19,
        "latency_p99_ms": 142,
        "latency_p50_ms": 38,
        "latency_mean_ms": 51,
    },
    "diagnosis": {
        "measured": {
            "error_rate_pct_during": 100.0,
            "latency_p99_ms_during": 8,
            "latency_p99_ms_baseline": 142,
            "calls_total_during": 690,
            "calls_total_baseline": 710,
        },
        "derived": {
            "latency_p99_ratio": 0.056,
            "calls_volume_ratio": 0.972,
        },
        "assessment": {
            "pattern": "FAIL_FAST",
            "reasoning": (
                "Error rate at 100.0% with p99 latency of 8ms vs baseline of 142ms (0.06x). "
                "Calls are being rejected immediately — typical of auth/config failure or "
                "dependency returning instant error. NOT resource exhaustion (saturation "
                "would increase latency, not reduce it). "
                "Call volume stable (690 vs 710, 0.97x): traffic kept arriving, "
                "the service stopped serving."
            ),
            "recommendation": (
                "Investigate service config and credentials against immediate dependencies. "
                "Compare current manifest with the one in place before the event started. "
                "Rollback only makes sense if a config change correlates with the start time."
            ),
            "thresholds_used": {
                "high_error_rate_pct": 50.0,
                "low_error_rate_pct": 10.0,
                "latency_ratio_high": 2.0,
                "latency_ratio_low": 0.5,
                "calls_ratio_stable_min": 0.8,
                "calls_ratio_stable_max": 1.2,
            },
        },
    },
    "related_events": [
        {
            "event_id": "trigger-event-001",
            "problem": "Erroneous call rate exceeds threshold",
            "severity": 10,
            "start": "2026-08-18T13:56:00+00:00",
            "is_trigger": True,
        }
    ],
    "data_provenance": {
        "source": "DEMO MODE — simulated Instana data based on real PoC incident",
        "all_fields_measured": True,
    },
    "queried_at": "2026-08-21T07:00:00+00:00",
}

INSTANA_BLAST_RADIUS = {
    "status": "OK",
    "incident_id": "QKTtAivDTAaKvCGqvQOWpA",
    "application": {"name": "Robot-Shop-EKS", "application_id": "app-robot-shop-001"},
    "window": {
        "start": "2026-08-18T13:56:00+00:00",
        "end": "2026-08-21T06:39:00+00:00",
        "duration_minutes": 3883,
    },
    "services_analyzed": 8,
    "services_anomalous": 2,
    "anomaly_criterion": "error_rate_delta >= 5pp vs 7-day baseline (editorial threshold)",
    "anomalous_services": [
        {
            "service": "mcp-gateway-mcp-stack-mcpgateway.mcp-context-forge",
            "measured": {
                "calls": 690,
                "erroneous_calls": 690,
                "error_rate_pct": 100.0,
                "latency_p99_ms": 8,
                "error_rate_pct_baseline": 1.69,
                "latency_p99_ms_baseline": 142,
                "baseline_available": True,
            },
            "derived": {"error_rate_delta_pp": 98.31, "latency_p99_ratio": 0.056},
            "assessment": {
                "anomalous": True,
                "anomaly_reason": "error_rate_delta=98.31pp >= threshold 5pp",
            },
        },
        {
            "service": "frontend",
            "measured": {
                "calls": 1840,
                "erroneous_calls": 690,
                "error_rate_pct": 37.5,
                "latency_p99_ms": 320,
                "error_rate_pct_baseline": 1.1,
                "latency_p99_ms_baseline": 95,
                "baseline_available": True,
            },
            "derived": {"error_rate_delta_pp": 36.4, "latency_p99_ratio": 3.37},
            "assessment": {
                "anomalous": True,
                "anomaly_reason": "error_rate_delta=36.4pp >= threshold 5pp",
            },
        },
    ],
    "all_services": [
        {
            "service": "mcp-gateway-mcp-stack-mcpgateway.mcp-context-forge",
            "measured": {"error_rate_pct": 100.0},
            "assessment": {"anomalous": True},
        },
        {
            "service": "frontend",
            "measured": {"error_rate_pct": 37.5},
            "assessment": {"anomalous": True},
        },
        {
            "service": "cart",
            "measured": {"error_rate_pct": 2.1},
            "assessment": {"anomalous": False},
        },
        {
            "service": "catalogue",
            "measured": {"error_rate_pct": 1.8},
            "assessment": {"anomalous": False},
        },
        {
            "service": "payment",
            "measured": {"error_rate_pct": 1.5},
            "assessment": {"anomalous": False},
        },
        {
            "service": "shipping",
            "measured": {"error_rate_pct": 0.9},
            "assessment": {"anomalous": False},
        },
        {
            "service": "user",
            "measured": {"error_rate_pct": 0.4},
            "assessment": {"anomalous": False},
        },
        {
            "service": "ratings",
            "measured": {"error_rate_pct": 0.2},
            "assessment": {"anomalous": False},
        },
    ],
    "queried_at": "2026-08-21T07:00:00+00:00",
}

JIRA_SEARCH_RESULTS = {
    "query": {
        "service": "mcp-gateway",
        "keywords": "erroneous call rate config authentication",
        "jql": 'project = "KAN" AND (text ~ "erroneous" OR text ~ "mcp-gateway") AND status in (Done, "In Review")',
    },
    "total_found": 3,
    "issues": [
        {
            "key": "KAN-142",
            "type": "Task",
            "priority": "High",
            "title": "[INC] mcp-gateway 100% error rate — expired API key",
            "status": "Done",
            "created": "2026-05-14",
            "resolved": "2026-05-14",
            "resolution_time_min": 28,
            "resolution": (
                "Done. Rotated expired mcp-context-forge API key in Kubernetes secret "
                "`mcp-gateway-secrets`. Applied with `kubectl rollout restart`. "
                "Error rate dropped to baseline within 90 seconds."
            ),
            "labels": ["mcp-gateway", "auth", "CRITICAL", "autonomous-crisis-squad"],
            "url": "https://demo.atlassian.net/browse/KAN-142",
        },
        {
            "key": "KAN-118",
            "type": "Task",
            "priority": "High",
            "title": "[INC] mcp-gateway FAIL_FAST — ConfigMap misconfiguration after deploy",
            "status": "Done",
            "created": "2026-03-22",
            "resolved": "2026-03-22",
            "resolution_time_min": 45,
            "resolution": (
                "Done. ConfigMap `mcp-gateway-config` had wrong upstream URL after deploy v1.9.2. "
                "Rolled back with `kubectl rollout undo deployment/mcp-gateway`. "
                "Config patched in hotfix v1.9.3."
            ),
            "labels": ["mcp-gateway", "config", "CRITICAL"],
            "url": "https://demo.atlassian.net/browse/KAN-118",
        },
        {
            "key": "KAN-099",
            "type": "Task",
            "priority": "Medium",
            "title": "mcp-gateway intermittent 401 errors — service mesh cert renewal",
            "status": "Done",
            "created": "2026-01-08",
            "resolved": "2026-01-08",
            "resolution_time_min": 67,
            "resolution": (
                "Done. Istio mTLS certificate expired. Renewed with "
                "`istioctl upgrade` and `kubectl rollout restart`. "
                "Added cert-manager alert for 30d before expiry."
            ),
            "labels": ["mcp-gateway", "mtls", "istio"],
            "url": "https://demo.atlassian.net/browse/KAN-099",
        },
    ],
    "summary": (
        "Found 3 precedents for 'mcp-gateway' with keywords 'erroneous call rate config authentication'. "
        "Most similar: KAN-142 (expired API key, resolved in 28 min). "
        "Average MTTR from history: ~47 minutes."
    ),
}

JIRA_CREATED_TICKET = {
    "key": "KAN-201",
    "priority": "Highest",
    "title": "[P0] mcp-gateway — 100% error rate FAIL_FAST pattern",
    "service": "mcp-gateway",
    "status": "In Progress",
    "created_at": "2026-08-21T07:01:00Z",
    "url": "https://demo.atlassian.net/browse/KAN-201",
    "linked_alert": "QKTtAivDTAaKvCGqvQOWpA",
}

TEAMS_WAR_ROOM = {
    "status": "CREATED",
    "channel": {
        "id": "demo-channel-id-mcp-gateway-001",
        "name": "INC-QKTtAivDTAaKvCGqvQOWpA-mcp-gateway",
        "url": "https://teams.microsoft.com/l/channel/demo-channel-id-mcp-gateway-001",
        "team_id": "demo-team-id",
    },
    "initial_message": {
        "posted": True,
        "message_id": "demo-msg-001",
        "mentioned": ["SRE Lead", "Platform Engineering"],
        "posted_by": "Autonomous Crisis Squad (AI)",
    },
    "incident_id": "QKTtAivDTAaKvCGqvQOWpA",
    "created_at": "2026-08-21T07:01:30Z",
}
