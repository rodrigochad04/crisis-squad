"""Microsoft Teams tools — LangChain @tool wrappers.
When DEMO_MODE=true, skips Graph API and returns mock responses.

Uses Microsoft Graph API v1.0 via MSAL (client credentials flow).
Covers:
  - teams_create_war_room: creates a channel and posts initial diagnosis
  - teams_post_update:     posts chunked updates (UPDATE / APPROVAL_REQUEST / RESOLUTION)
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import requests
from langchain_core.tools import tool

from src.config import settings

if TYPE_CHECKING:  # pragma: no cover — typing only, never imported at runtime
    import msal

# ---------------------------------------------------------------------------
# Auth — MSAL confidential client, thread-safe token cache
# ---------------------------------------------------------------------------

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["https://graph.microsoft.com/.default"]
_HTTP_TIMEOUT = 20
_POST_RETRIES = 3
_TEAMS_MSG_LIMIT = 20_000
_INVALID_CHARS = re.compile(r"[~#%&*{}+/\\:<>?|'\"\[\]]")

_token_lock = threading.Lock()
_app: msal.ConfidentialClientApplication | None = None


def _get_app() -> msal.ConfidentialClientApplication:
    """Lazily build the MSAL client.

    Imported inside the function so DEMO_MODE, which mocks Teams entirely, does
    not require the Azure auth library to be installed.
    """
    global _app
    import msal  # noqa: PLC0415 — deliberate lazy import, see docstring

    with _token_lock:
        if _app is None:
            _app = msal.ConfidentialClientApplication(
                settings.teams_client_id,
                authority=f"https://login.microsoftonline.com/{settings.teams_tenant_id}",
                client_credential=settings.teams_client_secret,
            )
    return _app


def _get_token() -> str:
    app = _get_app()
    result = app.acquire_token_silent(_SCOPES, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=_SCOPES)
    if "access_token" not in result:
        raise RuntimeError(f"MSAL token acquisition failed: {result.get('error_description')}")
    return result["access_token"]


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}


def _request(method: str, url: str, **kwargs) -> requests.Response:
    resp = requests.request(method, url, headers=_headers(), timeout=_HTTP_TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# Teams helpers
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return _INVALID_CHARS.sub("-", text).strip("-")[:50]


def _build_channel_name(incident_id: str, service_name: str) -> str:
    return f"INC-{_slug(incident_id)}-{_slug(service_name)}"


def _find_channel(channel_name: str) -> dict | None:
    r = _request(
        "GET", f"{GRAPH_BASE}/teams/{settings.teams_team_id}/channels?$select=id,displayName,webUrl"
    )
    for ch in r.json().get("value", []):
        if ch.get("displayName") == channel_name:
            return ch
    return None


def _get_or_create_channel(channel_name: str, description: str) -> tuple[dict, bool]:
    existing = _find_channel(channel_name)
    if existing:
        return existing, False
    body = {"displayName": channel_name, "description": description, "membershipType": "standard"}
    r = _request("POST", f"{GRAPH_BASE}/teams/{settings.teams_team_id}/channels", json=body)
    return r.json(), True


def _resolve_users(upns: list[str]) -> list[dict]:
    users = []
    for upn in upns:
        try:
            r = _request("GET", f"{GRAPH_BASE}/users/{upn}?$select=id,displayName")
            users.append(r.json())
        except Exception:
            pass
    return users


def _post_message(
    channel_id: str, content_html: str, mention_users: list[dict] | None = None
) -> str:
    mentions = []
    mention_html = ""
    if mention_users:
        for i, u in enumerate(mention_users):
            mentions.append(
                {
                    "id": i,
                    "mentionText": u.get("displayName", ""),
                    "mentioned": {"user": {"id": u.get("id"), "displayName": u.get("displayName")}},
                }
            )
            mention_html += f'<at id="{i}">{html.escape(u.get("displayName", ""))}</at> '

    body_html = (mention_html + content_html) if mention_html else content_html
    payload: dict = {
        "body": {"contentType": "html", "content": body_html},
    }
    if mentions:
        payload["mentions"] = mentions

    last_error: Exception | None = None
    for attempt in range(_POST_RETRIES):
        try:
            r = _request(
                "POST",
                f"{GRAPH_BASE}/teams/{settings.teams_team_id}/channels/{channel_id}/messages",
                json=payload,
            )
            return r.json().get("id", "")
        except requests.HTTPError as exc:
            last_error = exc
            if attempt < _POST_RETRIES - 1:
                # Exponential backoff. Without it the three attempts fired back to
                # back, which is useless against the 429s Graph actually returns.
                time.sleep(2**attempt)
    raise last_error or RuntimeError("teams_post_message failed with no recorded error")


def _severity_emoji(severity: str) -> str:
    return {"P0": "🔴", "P1": "🟠", "P2": "🟡", "CRITICAL": "🔴", "WARNING": "🟠"}.get(
        severity.upper(), "🔵"
    )


def _esc(text: str) -> str:
    return html.escape(str(text))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _error_payload(exc: Exception) -> dict:
    return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Markdown → Teams HTML converter
# ---------------------------------------------------------------------------


def _inline_md(text: str) -> str:
    text = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text


def _md_to_html(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []

    for line in lines:
        if line.startswith("```"):
            if not in_code:
                lang = line[3:].strip() or "bash"
                in_code = True
                code_buf = [f'<pre><code class="language-{_esc(lang)}">']
            else:
                code_buf.append("</code></pre>")
                out.append("".join(code_buf))
                code_buf = []
                in_code = False
            continue
        if in_code:
            code_buf.append(_esc(line) + "\n")
            continue
        if line.startswith("### "):
            out.append(f"<h3>{_esc(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{_esc(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{_esc(line[2:])}</h1>")
        elif re.match(r"^-{3,}$", line.strip()):
            out.append("<hr>")
        elif m := re.match(r"^- \[(x| )\] (.+)", line):
            checked = ' checked=""' if m.group(1) == "x" else ""
            out.append(
                f'<p><input type="checkbox"{checked} disabled=""> {_inline_md(_esc(m.group(2)))}</p>'
            )
        elif re.match(r"^- ", line):
            out.append(f"<p>• {_inline_md(_esc(line[2:]))}</p>")
        elif line.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p>{_inline_md(_esc(line))}</p>")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def teams_create_war_room(
    incident_id: str,
    service_name: str,
    severity: str,
    summary: str,
    oncall_squad: str,
    oncall_emails: str = "",
) -> str:
    """Create a war room channel in Microsoft Teams and post the initial diagnosis.

    Args:
        incident_id: Incident ticket ID (e.g. INC-5042)
        service_name: Affected service name
        severity: Severity (P0, P1, P2)
        summary: Initial AI diagnosis summary to post in the channel
        oncall_squad: On-call squad name
        oncall_emails: Comma-separated on-call email addresses for @mention
    """
    if settings.demo_mode:
        from src.demo.mocks import mock_teams_create_war_room

        return mock_teams_create_war_room(
            incident_id, service_name, severity, summary, oncall_squad, oncall_emails
        )

    try:
        emails = oncall_emails or settings.teams_oncall_emails
        channel_name = _build_channel_name(incident_id, service_name)
        description = f"War Room — {severity} | {service_name} | {incident_id}"
        channel, created = _get_or_create_channel(channel_name, description)

        emoji = _severity_emoji(severity)
        hora = datetime.now(UTC).strftime("%H:%M")
        html_msg = (
            f"<h2>{emoji} INCIDENT {_esc(severity)} — {_esc(service_name)}</h2>"
            f"<p>📋 Ticket: <strong>{_esc(incident_id)}</strong><br>"
            f"🕐 Detected: {hora} UTC<br>"
            f"👥 On-call squad: <strong>{_esc(oncall_squad)}</strong></p>"
            f"<h3>Initial AI Diagnosis:</h3><p>{_esc(summary)}</p><hr>"
            f"<p>⚠️ <em>All production actions require explicit human approval in this channel.</em><br>"
            f"Respond <strong>APPROVE</strong> or <strong>REJECT</strong> when prompted.</p>"
        )

        upns = [e.strip() for e in emails.split(",") if e.strip()]
        mention_users = _resolve_users(upns) if upns else None
        message_id = _post_message(channel["id"], html_msg, mention_users)

        result = {
            "status": "CREATED" if created else "REUSED",
            "channel": {
                "id": channel["id"],
                "name": channel_name,
                "url": channel.get("webUrl"),
                "team_id": settings.teams_team_id,
            },
            "initial_message": {
                "posted": True,
                "message_id": message_id,
                "mentioned": [u["displayName"] for u in (mention_users or [])],
            },
            "incident_id": incident_id,
            "created_at": _now_iso(),
        }
    except Exception as exc:  # noqa: BLE001
        result = _error_payload(exc)

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def teams_post_update(
    channel_id: str,
    message: str,
    message_type: str = "UPDATE",
) -> str:
    """Post an update to an incident war room channel in Microsoft Teams.

    Converts Markdown to Teams HTML and automatically chunks messages longer
    than 20,000 characters to preserve the full content of long playbooks.

    Args:
        channel_id: Channel ID returned by teams_create_war_room
        message: Message content (Markdown accepted)
        message_type: UPDATE | APPROVAL_REQUEST | RESOLUTION
    """
    if settings.demo_mode:
        from src.demo.mocks import mock_teams_post_update

        return mock_teams_post_update(channel_id, message, message_type)

    icons = {"UPDATE": "📢", "APPROVAL_REQUEST": "✋", "RESOLUTION": "✅"}
    icon = icons.get(message_type, "📢")
    hora = datetime.now(UTC).strftime("%H:%M")
    header = f"<p>{icon} <strong>[{_esc(message_type)}]</strong> — {hora} UTC</p>"

    html_body = _md_to_html(message)

    chunks: list[str] = []
    remaining = html_body
    while len(remaining) > _TEAMS_MSG_LIMIT:
        cut = remaining.rfind("<br>", 0, _TEAMS_MSG_LIMIT)
        if cut == -1:
            cut = remaining.rfind("<p>", 0, _TEAMS_MSG_LIMIT)
        if cut == -1:
            cut = _TEAMS_MSG_LIMIT
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    chunks.append(remaining)

    try:
        message_ids = []
        for i, chunk in enumerate(chunks):
            mid = _post_message(channel_id, (header if i == 0 else "") + chunk)
            message_ids.append(mid)
        result = {
            "status": "POSTED",
            "channel_id": channel_id,
            "message_ids": message_ids,
            "parts": len(message_ids),
            "message_type": message_type,
            "posted_at": _now_iso(),
        }
    except Exception as exc:  # noqa: BLE001
        result = _error_payload(exc)

    return json.dumps(result, ensure_ascii=False, indent=2)


TEAMS_TOOLS = [teams_create_war_room, teams_post_update]
