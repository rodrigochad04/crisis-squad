"""Jira tools — LangChain @tool wrappers.
When DEMO_MODE=true, returns mock precedent data without calling Jira.

Covers:
  - jira_search_related_issues: JQL precedent search with resolution time
  - jira_create_incident_ticket: creates a ticket in Atlassian Document Format (ADF)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import requests
from langchain_core.tools import tool

from src.config import settings as _settings

settings = _settings


def _auth() -> tuple[str, str]:
    return (settings.jira_user_email, settings.jira_api_token)


def _base() -> str:
    return settings.jira_base_url.rstrip("/")


def _project() -> str:
    return settings.jira_project_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_adf_text(node: dict | str) -> str:
    """Recursively extract plain text from Atlassian Document Format."""
    if not isinstance(node, dict):
        return str(node)
    if node.get("type") == "text":
        return node.get("text", "")
    return " ".join(
        p for child in node.get("content", []) if (p := _extract_adf_text(child))
    ).strip()


def _resolution_minutes(created_str: str | None, resolved_str: str | None) -> int | None:
    if not created_str or not resolved_str:
        return None
    try:
        from dateutil import parser as _dp  # type: ignore[import]

        c = _dp.parse(created_str)
        r = _dp.parse(resolved_str)
        return max(0, int((r - c).total_seconds() / 60))
    except Exception:
        pass
    # Fallback: manual ISO-8601 parse (handles +0000 / +00:00 variants)
    try:
        import re as _re

        def _parse(s: str) -> datetime:
            s = _re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)  # +0000 → +00:00
            return datetime.fromisoformat(s)

        return max(0, int((_parse(resolved_str) - _parse(created_str)).total_seconds() / 60))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def jira_search_related_issues(
    service_name: str,
    error_keywords: str,
    days_back: int = 30,
) -> str:
    """Search Jira for past issues related to the affected service and error pattern.

    Finds resolved precedents and their resolution details to inform the current
    incident response.

    Args:
        service_name: Affected service name (e.g. checkout-service)
        error_keywords: Space-separated error keywords (e.g. OutOfMemoryError heap)
        days_back: Search window in days (default: 30)
    """
    if settings.demo_mode:
        from src.demo.mocks import mock_jira_search_related_issues

        return mock_jira_search_related_issues(service_name, error_keywords, days_back)

    since = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    kw_clause = " OR ".join(f'text ~ "{kw.strip()}"' for kw in error_keywords.split() if kw.strip())
    jql = (
        f'project = "{_project()}" '
        f'AND ({kw_clause} OR text ~ "{service_name}") '
        f'AND created >= "{since}" '
        f'AND status in (Done, "In Review") '
        f"ORDER BY created DESC"
    )

    url = f"{_base()}/rest/api/3/search/jql"
    params = {
        "jql": jql,
        "maxResults": "10",
        "fields": "summary,status,priority,created,resolutiondate,resolution,labels,comment,issuetype",
    }

    try:
        resp = requests.get(
            url, auth=_auth(), headers={"Accept": "application/json"}, params=params, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        return json.dumps({"error": f"Jira request failed: {exc}"}, ensure_ascii=False)

    issues = []
    for issue in data.get("issues", []):
        f = issue.get("fields", {})
        comments = (f.get("comment") or {}).get("comments", [])
        last_comment = comments[-1].get("body", {}) if comments else {}
        resolution_detail = (
            _extract_adf_text(last_comment) if isinstance(last_comment, dict) else str(last_comment)
        )
        resolution_name = (f.get("resolution") or {}).get("name", "")

        issues.append(
            {
                "key": issue.get("key"),
                "type": (f.get("issuetype") or {}).get("name", ""),
                "priority": (f.get("priority") or {}).get("name", ""),
                "title": f.get("summary", ""),
                "status": (f.get("status") or {}).get("name", ""),
                "created": (f.get("created") or "")[:10],
                "resolved": (f.get("resolutiondate") or "")[:10],
                "resolution_time_min": _resolution_minutes(
                    f.get("created"), f.get("resolutiondate")
                ),
                "resolution": f"{resolution_name}. {resolution_detail}".strip(". "),
                "labels": f.get("labels", []),
                "url": f"{_base()}/browse/{issue.get('key')}",
            }
        )

    return json.dumps(
        {
            "query": {"service": service_name, "keywords": error_keywords, "jql": jql},
            "total_found": data.get("total", 0),
            "issues": issues,
            "summary": (
                f"Found {len(issues)} precedents for '{service_name}' "
                f"with keywords '{error_keywords}' in the last {days_back} days."
                if issues
                else f"No precedents found for '{service_name}' with keywords '{error_keywords}'."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


@tool
def jira_create_incident_ticket(
    title: str,
    service_name: str,
    severity: str,
    description: str,
    alert_id: str,
) -> str:
    """Create a Jira ticket for the current incident for traceability.

    Args:
        title: Incident title
        service_name: Affected service
        severity: Severity level (P0, P1, P2)
        description: Incident description and initial diagnosis
        alert_id: Instana incident ID for cross-reference
    """
    if settings.demo_mode:
        from src.demo.mocks import mock_jira_create_incident_ticket

        return mock_jira_create_incident_ticket(
            title, service_name, severity, description, alert_id
        )

    priority_map = {"P0": "Highest", "P1": "High", "P2": "Medium"}
    priority_name = priority_map.get(severity.upper(), "High")

    payload = {
        "fields": {
            "project": {"key": _project()},
            "summary": title,
            "issuetype": {"name": "Task"},
            "priority": {"name": priority_name},
            "labels": [service_name, alert_id, severity.upper(), "autonomous-crisis-squad"],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": description}]},
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": f"Instana Incident: {alert_id}"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": f"Affected service: {service_name}"}],
                    },
                ],
            },
        }
    }

    url = f"{_base()}/rest/api/3/issue"
    try:
        resp = requests.post(
            url,
            auth=_auth(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        created = resp.json()
    except requests.RequestException as exc:
        return json.dumps({"error": f"Failed to create Jira ticket: {exc}"}, ensure_ascii=False)

    key = created.get("key", "")
    return json.dumps(
        {
            "key": key,
            "priority": priority_name,
            "title": title,
            "service": service_name,
            "status": "In Progress",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "url": f"{_base()}/browse/{key}",
            "linked_alert": alert_id,
        },
        ensure_ascii=False,
        indent=2,
    )


JIRA_TOOLS = [jira_search_related_issues, jira_create_incident_ticket]
