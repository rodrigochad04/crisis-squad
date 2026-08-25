"""DORA & SPACE metrics engine.

Computes incident-level engineering productivity metrics from the
data already flowing through the system:

  DORA:
    - MTTR (Mean Time to Recovery)         ← incident duration
    - Deployment Frequency                 ← Jira ticket creation rate
    - Change Failure Rate                  ← incidents / total changes
    - Lead Time for Changes                ← detection → resolution

  SPACE (proxy metrics from incident data):
    - Satisfaction: approval rate (APPROVED vs REJECTED)
    - Performance: MTTR vs historical target
    - Activity: incidents handled / period
    - Collaboration: agents involved per incident
    - Efficiency: time in each phase

All values are stored in-memory and exposed via /metrics/dora.
In production, push to Prometheus / Grafana / Datadog.
"""

from __future__ import annotations

import statistics
import threading
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any


class MetricsStore:
    """In-memory store for incident metrics.

    Guarded by a re-entrant lock. The API writes from the event-loop thread and
    from the executor threads that run graph nodes, so the old docstring's claim
    of thread safety needed to become an actual one.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._incidents: dict[str, dict] = {}
        self._phase_times: dict[str, dict[str, float]] = defaultdict(dict)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_incident_start(self, incident_id: str, run_id: str, service: str = "unknown"):
        with self._lock:
            self._incidents[run_id] = {
                "run_id": run_id,
                "incident_id": incident_id,
                "service": service,
                "started_at": _now_iso(),
                "started_ts": _now_ts(),
                "resolved_at": None,
                "resolved_ts": None,
                "mttr_minutes": None,
                "decision": None,
                "decided_by": None,
                "agents_involved": [],
                "phase_durations_ms": {},
                "approval_requested": False,
                "approval_decision": None,
            }

    def record_phase_start(self, run_id: str, phase: str):
        with self._lock:
            self._phase_times[run_id][f"{phase}_start"] = _now_ts()

    def record_phase_end(self, run_id: str, phase: str):
        with self._lock:
            start_key = f"{phase}_start"
            if run_id in self._phase_times and start_key in self._phase_times[run_id]:
                duration_ms = round((_now_ts() - self._phase_times[run_id][start_key]) * 1000, 1)
                if run_id in self._incidents:
                    self._incidents[run_id]["phase_durations_ms"][phase] = duration_ms

    def record_agent_invoked(self, run_id: str, agent_name: str):
        with self._lock:
            if run_id in self._incidents:
                agents = self._incidents[run_id]["agents_involved"]
                if agent_name not in agents:
                    agents.append(agent_name)

    def record_approval(self, run_id: str, decision: str, decided_by: str):
        with self._lock:
            if run_id in self._incidents:
                self._incidents[run_id]["approval_requested"] = True
                self._incidents[run_id]["approval_decision"] = decision
                self._incidents[run_id]["decided_by"] = decided_by

    def record_resolution(self, run_id: str, service: str = ""):
        with self._lock:
            if run_id in self._incidents:
                ts = _now_ts()
                started_ts = self._incidents[run_id]["started_ts"]
                elapsed_secs = ts - started_ts
                mttr_minutes = round(elapsed_secs / 60, 1)
                # Demo sessions complete in <1 min; store seconds for UI precision
                mttr_seconds = round(elapsed_secs, 1)
                self._incidents[run_id].update(
                    {
                        "resolved_at": _now_iso(),
                        "resolved_ts": ts,
                        "mttr_minutes": max(mttr_minutes, 0.1),  # floor at 0.1 min to show non-zero
                        "mttr_seconds": mttr_seconds,
                        "service": service or self._incidents[run_id].get("service", "unknown"),
                    }
                )

    # ------------------------------------------------------------------
    # DORA metrics
    # ------------------------------------------------------------------

    def dora_metrics(self) -> dict[str, Any]:
        with self._lock:
            resolved = [i for i in self._incidents.values() if i.get("mttr_minutes") is not None]
            all_runs = list(self._incidents.values())

            mttr_values = [i["mttr_minutes"] for i in resolved]
            approved = [i for i in all_runs if i.get("approval_decision") == "APPROVED"]
            rejected = [i for i in all_runs if i.get("approval_decision") == "REJECTED"]

            # MTTR — also expose seconds for sub-minute demo precision
            avg_mttr = round(statistics.mean(mttr_values), 1) if mttr_values else None
            p50_mttr = round(statistics.median(mttr_values), 1) if mttr_values else None
            secs_values = [i.get("mttr_seconds", i["mttr_minutes"] * 60) for i in resolved]
            avg_mttr_secs = round(statistics.mean(secs_values), 1) if secs_values else None

            # Change Failure Rate proxy — incidents with APPROVED rollback / total incidents
            cfr = round(len(approved) / len(all_runs) * 100, 1) if all_runs else None

            # Collaboration — avg agents per incident
            agent_counts = [len(i.get("agents_involved", [])) for i in all_runs]
            avg_agents = round(statistics.mean(agent_counts), 1) if agent_counts else 0

            # Approval rate
            total_decisions = len(approved) + len(rejected)
            approval_rate = (
                round(len(approved) / total_decisions * 100, 1) if total_decisions else None
            )

            return {
                "computed_at": _now_iso(),
                "incidents_tracked": len(all_runs),
                "incidents_resolved": len(resolved),
                "dora": {
                    "mttr": {
                        "avg_minutes": avg_mttr,
                        "avg_seconds": avg_mttr_secs,
                        "p50_minutes": p50_mttr,
                        "target_minutes": 30,
                        "unit": "minutes",
                        "description": "Mean Time to Recovery — lower is better",
                        "all_values": mttr_values,
                    },
                    "change_failure_rate": {
                        "value_pct": cfr,
                        "description": "% of incidents requiring production action (ROLLBACK/RESTART)",
                    },
                    "deployment_frequency": {
                        "incidents_per_session": len(all_runs),
                        "description": "Proxy: incidents handled per demo session",
                    },
                },
                "space": {
                    "satisfaction": {
                        "approval_rate_pct": approval_rate,
                        "approved": len(approved),
                        "rejected": len(rejected),
                        "description": "% of recommended actions approved by SRE",
                    },
                    "performance": {
                        "avg_mttr_minutes": avg_mttr,
                        "target_minutes": 30,
                        "meets_target": avg_mttr <= 30 if avg_mttr else None,
                    },
                    "activity": {
                        "total_incidents": len(all_runs),
                        "resolved": len(resolved),
                    },
                    "collaboration": {
                        "avg_agents_per_incident": avg_agents,
                        "description": "Average number of specialist agents involved per incident",
                    },
                    "efficiency": {
                        "phase_breakdown_sample": (
                            list(all_runs[-1]["phase_durations_ms"].items())
                            if all_runs and all_runs[-1].get("phase_durations_ms")
                            else []
                        ),
                    },
                },
                "per_incident": [
                    {
                        "run_id": i["run_id"],
                        "incident_id": i["incident_id"],
                        "service": i["service"],
                        "started_at": i["started_at"],
                        "resolved_at": i.get("resolved_at"),
                        "mttr_minutes": i.get("mttr_minutes"),
                        "approval_decision": i.get("approval_decision"),
                        "agents_involved": i.get("agents_involved", []),
                        "phase_durations_ms": i.get("phase_durations_ms", {}),
                    }
                    for i in all_runs
                ],
            }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_ts() -> float:
    return datetime.now(UTC).timestamp()


# Module-level singleton
metrics = MetricsStore()
