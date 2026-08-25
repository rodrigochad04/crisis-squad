#!/usr/bin/env python3
"""Terminal demo — drives the real graph, no browser required.

This script is deliberately thin. It does not re-implement the pipeline: it
starts the same compiled LangGraph the API and the MCP server use, prints each
node as it completes, stops at the governance gate, asks the operator for a
decision, and resumes. If this file and the API ever disagree about what the
pipeline does, that is a bug in this file.

Usage::

    python demo/run_demo.py                        # built-in demo incident
    python demo/run_demo.py --incident-id ABC123
    python demo/run_demo.py --decision APPROVED    # non-interactive (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings  # noqa: E402
from src.graph.crisis_graph import (  # noqa: E402
    default_state,
    get_graph,
    llm_available,
    resume_with_decision,
)

DEMO_INCIDENT = "QKTtAivDTAaKvCGqvQOWpA"

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    _console: Console | None = Console()
except ImportError:  # pragma: no cover - rich is optional
    _console = None


def out(text: str = "") -> None:
    if _console:
        _console.print(text)
    else:
        print(_strip_markup(text))


def _strip_markup(text: str) -> str:
    import re

    return re.sub(r"\[/?[a-z0-9 #]+\]", "", text)


def panel(title: str, body: str) -> None:
    if _console:
        _console.print(Panel(body, title=title, border_style="cyan"))
    else:
        print(f"\n=== {title} ===\n{body}\n")


def render_result(node: str, result: dict) -> None:
    out(f"\n[bold cyan]▸ {node}[/bold cyan]")
    for key, value in result.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        text = str(value)
        if len(text) > 160:
            text = text[:157] + "..."
        out(f"    {key:20} {text}")


def main() -> int:
    parser = argparse.ArgumentParser(description="GCB Crisis Squad terminal demo")
    parser.add_argument("--incident-id", default=DEMO_INCIDENT)
    parser.add_argument(
        "--decision",
        choices=["APPROVED", "REJECTED"],
        help="Skip the interactive prompt (useful in CI).",
    )
    parser.add_argument("--decided-by", default="demo-operator")
    parser.add_argument("--show-playbook", action="store_true")
    args = parser.parse_args()

    out("[bold]GCB Autonomous Crisis Squad[/bold] — terminal demo")
    out(f"  demo_mode      {settings.demo_mode}")
    out(f"  llm_configured {llm_available()} ({settings.llm_model})")
    if not llm_available():
        out("  [yellow]No LLM key set — the playbook node uses its static fallback.[/yellow]")

    graph = get_graph()
    thread_id = f"cli-{args.incident_id}"
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

    for chunk in graph.stream(
        default_state(args.incident_id), config=config, stream_mode="updates"
    ):
        for node, update in chunk.items():
            if not isinstance(update, dict):
                continue
            for event in update.get("ui_events", []):
                render_result(node, event.get("result", {}))

    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    if args.show_playbook:
        if _console:
            _console.print(Markdown(values.get("playbook", "")))
        else:
            print(values.get("playbook", ""))

    panel(
        "⛔ Human-in-the-Loop gate",
        f"approval_id : {values.get('approval_id')}\n"
        f"graph paused: interrupt_after=['hitl'] — next node is "
        f"{list(snapshot.next)}\n"
        f"Nothing runs in production until a decision is written to the checkpoint.",
    )

    decision = args.decision
    if not decision:
        try:
            answer = input("Approve this action? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            out("\nAborted — the run stays paused at the gate.")
            return 1
        decision = "APPROVED" if answer in ("y", "yes") else "REJECTED"

    final = resume_with_decision(thread_id, decision, args.decided_by)
    panel(
        "Audit trail",
        json.dumps(final.get("audit_entry", {}).get("audit_entry", {}), indent=2),
    )
    out(f"\nFinal phase: [bold]{final.get('phase')}[/bold]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
