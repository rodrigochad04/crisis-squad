"""Mock tool implementations for DEMO_MODE=true.

Quando DEMO_MODE=true, estas funções substituem as chamadas reais às APIs.
Cada mock retorna JSON idêntico ao formato que a API real retornaria,
baseado nos dados do incidente real da PoC.

Uso: as tools verificam settings.demo_mode e chamam os mocks automaticamente.
"""

from __future__ import annotations

import json

from src.demo.mock_data import (
    INSTANA_BLAST_RADIUS,
    INSTANA_INCIDENT_DETAILS,
    JIRA_CREATED_TICKET,
    JIRA_SEARCH_RESULTS,
    TEAMS_WAR_ROOM,
)


def mock_instana_get_incident_details(incident_id: str) -> str:
    """Retorna dados reais do incidente QKTtAivDTAaKvCGqvQOWpA (DEMO)."""
    data = {**INSTANA_INCIDENT_DETAILS, "incident_id": incident_id}
    return json.dumps(data, ensure_ascii=False, indent=2)


def mock_instana_get_blast_radius(incident_id: str) -> str:
    """Retorna blast radius do incidente da PoC (DEMO)."""
    data = {**INSTANA_BLAST_RADIUS, "incident_id": incident_id}
    return json.dumps(data, ensure_ascii=False, indent=2)


def mock_jira_search_related_issues(
    service_name: str, error_keywords: str, days_back: int = 30
) -> str:
    """Retorna precedentes históricos simulados (DEMO)."""
    data = {
        **JIRA_SEARCH_RESULTS,
        "query": {
            "service": service_name,
            "keywords": error_keywords,
            "jql": f'project = "KAN" AND text ~ "{service_name}" AND status in (Done)',
        },
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def mock_jira_create_incident_ticket(
    title: str, service_name: str, severity: str, description: str, alert_id: str
) -> str:
    """Simula criação de ticket no Jira (DEMO)."""
    import random

    ticket_num = random.randint(200, 299)
    data = {
        **JIRA_CREATED_TICKET,
        "key": f"KAN-{ticket_num}",
        "title": title,
        "service": service_name,
        "linked_alert": alert_id,
        "url": f"https://demo.atlassian.net/browse/KAN-{ticket_num}",
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def mock_teams_create_war_room(
    incident_id: str,
    service_name: str,
    severity: str,
    summary: str,
    oncall_squad: str,
    oncall_emails: str = "",
) -> str:
    """Simula criação de canal no Teams (DEMO — apenas loga no console)."""
    data = {
        **TEAMS_WAR_ROOM,
        "incident_id": incident_id,
        "channel": {
            **dict(TEAMS_WAR_ROOM["channel"]),  # type: ignore[arg-type]
            "name": f"INC-{incident_id[:8]}-{service_name[:20]}",
        },
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def mock_teams_post_update(channel_id: str, message: str, message_type: str = "UPDATE") -> str:
    """Simula post no Teams (DEMO — apenas loga no console)."""
    import random

    data = {
        "status": "POSTED",
        "channel_id": channel_id,
        "message_ids": [f"demo-msg-{random.randint(100, 999)}"],
        "parts": 1,
        "message_type": message_type,
        "posted_at": "2026-08-21T07:02:00Z",
        "note": "DEMO MODE — message not actually sent to Teams",
    }
    return json.dumps(data, ensure_ascii=False, indent=2)
