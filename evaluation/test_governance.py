"""Governance tests — the Human-in-the-Loop gate must be unbypassable.

Every claim the README makes about the gate is asserted here. If a future change
lets an incident reach a production action without a recorded human decision,
one of these tests fails.

These tests are deterministic: no LLM, no network, no credentials.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("API_AUTH_ENABLED", "false")

from src.graph.crisis_graph import (  # noqa: E402
    INTERRUPT_AFTER,
    NODE_SEQUENCE,
    build_graph,
    default_state,
    graph_definition,
    record_decision_node,
)

DEMO_INCIDENT = "QKTtAivDTAaKvCGqvQOWpA"


def _run_to_gate(graph, thread_id: str) -> dict:
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
    graph.invoke(default_state(DEMO_INCIDENT), config=config)
    return config


# ---------------------------------------------------------------------------
# Graph-level guarantees
# ---------------------------------------------------------------------------


class TestGraphTopology:
    """The compiled graph is the single source of truth for the topology."""

    def test_interrupt_is_configured_after_hitl(self):
        assert INTERRUPT_AFTER == ["hitl"]

    def test_definition_is_introspected_not_hardcoded(self):
        """`/graph/definition` must read from the compiled graph.

        Guards the specific regression where the endpoint returned a hand-written
        dict that had drifted from the graph that actually executed.
        """
        definition = graph_definition()
        assert definition["source"].startswith("introspected")
        node_ids = {n["id"] for n in definition["nodes"]}
        assert node_ids == {name for name, _ in NODE_SEQUENCE}

    def test_hitl_is_the_only_path_to_record_decision(self):
        """No edge may reach the audit node without passing the gate."""
        definition = graph_definition()
        inbound = [e["from"] for e in definition["edges"] if e["to"] == "record_decision"]
        assert inbound == ["hitl"]


class TestGateHalting:
    """The graph stops at the gate and stays stopped."""

    def test_graph_pauses_before_record_decision(self):
        graph = build_graph()
        config = _run_to_gate(graph, "gate-pause")
        snapshot = graph.get_state(config)

        assert snapshot.next == ("record_decision",), "graph did not stop at the gate"
        assert snapshot.values["approval_status"] == "PENDING"
        assert snapshot.values["approval_id"], "gate must register an approval request"
        assert snapshot.values["audit_entry"] == {}, "audit written before any decision"

    def test_reinvoking_without_a_decision_raises(self):
        """A caller cannot brute-force past the gate by re-invoking the graph.

        Resuming an interrupted graph is a legitimate LangGraph operation, so the
        interrupt alone does not stop this. The audit node's own precondition
        does — which is exactly why that second layer exists.
        """
        graph = build_graph()
        config = _run_to_gate(graph, "gate-reinvoke")
        with pytest.raises(RuntimeError, match="cannot be bypassed"):
            graph.invoke(None, config=config)
        assert graph.get_state(config).values["audit_entry"] == {}

    def test_record_decision_refuses_without_a_human_decision(self):
        """Defence in depth: the node itself rejects an un-decided state.

        Even if the interrupt were removed from the topology, this raises.
        """
        state = default_state(DEMO_INCIDENT)
        state["approval_status"] = "PENDING"
        with pytest.raises(RuntimeError, match="cannot be bypassed"):
            record_decision_node(state, {})

    @pytest.mark.parametrize("decision", ["APPROVED", "REJECTED"])
    def test_resume_records_the_decision(self, decision: str):
        graph = build_graph()
        config = _run_to_gate(graph, f"gate-resume-{decision}")
        graph.update_state(config, {"approval_status": decision, "decided_by": "sre-lead"})
        graph.invoke(None, config=config)
        values = graph.get_state(config).values

        assert values["phase"] == ("RESOLVED" if decision == "APPROVED" else "REJECTED")
        assert values["audit_entry"]["decision"] == decision
        assert values["audit_entry"]["decided_by"] == "sre-lead"
        entry = values["audit_entry"]["audit_entry"]
        assert entry["event"] == "HUMAN_DECISION_RECORDED"
        assert entry["action"] == decision
        assert entry["actor"] == "sre-lead"
        assert entry["timestamp"], "audit entries must be timestamped"


class TestActionGrounding:
    """The action shown at the gate must come from the playbook, not a constant."""

    def test_approval_action_is_extracted_from_the_playbook(self):
        graph = build_graph()
        config = _run_to_gate(graph, "gate-action")
        values = graph.get_state(config).values

        ui = [e for e in values["ui_events"] if e["phase"] == "hitl"][0]["result"]
        action = ui["action_description"]
        assert action, "no action presented to the human"
        assert values["service_name"] in action, (
            "the gate must describe an action for the service actually diagnosed"
        )
        assert action in values["playbook"], (
            "the action shown to the human is not present in the playbook"
        )


# ---------------------------------------------------------------------------
# API-level guarantees
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    from src.api.server import app

    return TestClient(app)


class TestApprovalEndpoint:
    """The API cannot be talked into approving something it should not."""

    def test_unknown_run_is_404(self, client: TestClient):
        resp = client.post(
            "/incidents/does-not-exist/approve",
            json={"decision": "APPROVED", "decided_by": "someone"},
        )
        assert resp.status_code == 404

    def test_approval_before_the_gate_is_rejected(self, client: TestClient):
        """A decision that arrives before the gate is reached must not be accepted.

        This is the regression that mattered most: the old endpoint returned 200
        and wrote an audit entry with an empty approval_id.
        """
        trigger = client.post("/incidents", json={"incident_id": DEMO_INCIDENT})
        run_id = trigger.json()["run_id"]
        # The background task has not run yet, so the run is still STARTING.
        resp = client.post(
            f"/incidents/{run_id}/approve",
            json={"decision": "APPROVED", "decided_by": "too-early"},
        )
        assert resp.status_code == 409
        assert "not reached" in resp.json()["detail"].lower()

    def test_decision_is_immutable(self, client: TestClient):
        """The first decision wins; a contradicting second call gets 409."""
        from src.api import server

        run_id = "immutable-test"
        server._incidents[run_id] = {
            "run_id": run_id,
            "thread_id": "t-immutable",
            "phase": "RESOLVED",
            "approval_status": "APPROVED",
            "approval_id": "APPR-x",
            "decided_by": "first-responder",
            "decided_at": "2026-01-01T00:00:00Z",
            "events": [],
        }
        resp = client.post(
            f"/incidents/{run_id}/approve",
            json={"decision": "REJECTED", "decided_by": "second-responder"},
        )
        assert resp.status_code == 409
        assert "already decided" in resp.json()["detail"].lower()
        assert server._incidents[run_id]["approval_status"] == "APPROVED"

    def test_decision_field_is_validated(self, client: TestClient):
        resp = client.post(
            "/incidents/whatever/approve",
            json={"decision": "MAYBE", "decided_by": "someone"},
        )
        assert resp.status_code == 422


class TestAuthentication:
    """require_auth must actually be wired to the mutating endpoints."""

    def test_mutating_endpoints_depend_on_require_auth(self):
        """Guards the regression where require_auth existed but was never used."""
        from src.api.server import app, require_auth

        guarded = set()
        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            if any(dep.call is require_auth for dep in dependant.dependencies):
                for method in getattr(route, "methods", set()):
                    guarded.add((route.path, method))
        assert ("/incidents", "POST") in guarded
        assert ("/incidents/{run_id}/approve", "POST") in guarded

    def test_auth_rejects_missing_token_when_enabled(self, monkeypatch):
        from src.api.server import app
        from src.config import settings

        monkeypatch.setattr(settings, "api_auth_enabled", True)
        monkeypatch.setattr(settings, "api_secret_key", "a-real-secret")
        client = TestClient(app)

        assert client.post("/incidents", json={"incident_id": DEMO_INCIDENT}).status_code == 401
        assert (
            client.post(
                "/incidents",
                json={"incident_id": DEMO_INCIDENT},
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 401
        )

    def test_placeholder_secret_fails_loudly(self, monkeypatch):
        """Auth on + placeholder key must 500, never silently allow the request."""
        from src.api.server import app
        from src.config import settings

        monkeypatch.setattr(settings, "api_auth_enabled", True)
        monkeypatch.setattr(settings, "api_secret_key", "change-me-in-production")
        client = TestClient(app)

        resp = client.post(
            "/incidents",
            json={"incident_id": DEMO_INCIDENT},
            headers={"Authorization": "Bearer change-me-in-production"},
        )
        assert resp.status_code == 500
        assert "placeholder" in resp.json()["detail"].lower()
