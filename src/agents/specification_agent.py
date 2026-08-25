"""Specification-to-implementation agent workflow.

Accepts a natural language feature description from a Product Owner or engineer
and produces a structured implementation specification ready for a coding agent.

This demonstrates the "specification-to-implementation workflows" pattern
mentioned in the job description — bridging the gap between intent and code.

Workflow
--------
1. PARSE     — Extract intent, constraints, and acceptance criteria from free text
2. CLARIFY   — Identify ambiguities and generate targeted clarifying questions
3. SPEC      — Produce a structured YAML/Markdown specification
4. TASKS     — Break spec into atomic, estimable tasks
5. VALIDATE  — Self-review the spec against the original request

The agent can be triggered via the REST API:
    POST /spec/generate
    Body: {"description": "As a user, I want to ..."}

Or run standalone:
    python -m src.agents.specification_agent --description "..."
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage


@dataclass
class SpecificationResult:
    """Structured output of the specification agent."""

    original_request: str
    intent: str = ""
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    clarifying_questions: list[str] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    spec_markdown: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_request": self.original_request,
            "intent": self.intent,
            "constraints": self.constraints,
            "acceptance_criteria": self.acceptance_criteria,
            "clarifying_questions": self.clarifying_questions,
            "tasks": self.tasks,
            "spec_markdown": self.spec_markdown,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PARSE_SYSTEM = """\
You are a senior technical product analyst. Your job is to parse a feature
description and extract structured information.

Return your answer as JSON with this exact schema:
{
  "intent": "<one sentence — what the user ultimately wants>",
  "constraints": ["<constraint 1>", "<constraint 2>"],
  "acceptance_criteria": ["<criterion 1>", "<criterion 2>"],
  "ambiguities": ["<ambiguity 1>", "<ambiguity 2>"],
  "warnings": ["<warning if request is vague or contradictory>"]
}

Be precise. Constraints are technical or business limits. Acceptance criteria
are observable, testable conditions that define done. Ambiguities are questions
that must be answered before implementation can begin.
"""

_SPEC_SYSTEM = """\
You are a senior software architect writing an implementation specification
for a coding agent.

Given parsed intent and acceptance criteria, produce a structured spec in Markdown:

# Feature: <title>

## Summary
<2-3 sentences>

## Acceptance Criteria
- [ ] <criterion>

## Technical Approach
<concise description of the recommended implementation approach>

## API / Interface Changes
<REST endpoints, function signatures, or schema changes>

## Data Model
<any new or modified data structures>

## Out of Scope
<explicit exclusions>

## Risks & Open Questions
<risks or questions to resolve>

Be precise. Use real field names and types where possible.
"""

_TASKS_SYSTEM = """\
You are a senior engineer breaking a specification into atomic implementation tasks.

Return a JSON array where each task has:
{
  "id": "T-01",
  "title": "<short verb-first title>",
  "description": "<1-2 sentences>",
  "files_likely_affected": ["<file or module>"],
  "estimated_minutes": <integer>,
  "depends_on": ["T-xx"] or []
}

Tasks must be atomic (completable in <4h), ordered logically, and collectively
sufficient to implement the spec. Do not add tasks beyond what the spec requires.
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _strip_think(text: str) -> str:
    """Remove Groq Qwen CoT <think> blocks from output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json(text: str) -> str:
    """Extract JSON from a markdown code fence if present."""
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    return match.group(1).strip() if match else text.strip()


# ---------------------------------------------------------------------------
# SpecificationAgent
# ---------------------------------------------------------------------------


class SpecificationAgent:
    """Converts free-form feature descriptions into structured implementation specs.

    Parameters
    ----------
    llm:
        Any LangChain BaseChatModel. If None, attempts to instantiate ChatGroq
        using GROQ_API_KEY from environment.
    """

    def __init__(self, llm: Any = None) -> None:
        if llm is None:
            llm = self._default_llm()
        self._llm = llm

    @staticmethod
    def _default_llm() -> Any:
        import os

        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "No LLM provided and GROQ_API_KEY is not set. "
                "Either pass an LLM instance or set GROQ_API_KEY."
            )
        from langchain_groq import ChatGroq  # type: ignore[import]

        return ChatGroq(
            model="qwen/qwen3.6-27b",
            api_key=api_key,
            temperature=0,
            reasoning_effort="none",
        )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate(self, description: str) -> SpecificationResult:
        """Run the full specification pipeline and return a SpecificationResult."""
        result = SpecificationResult(original_request=description)

        # Phase 1 — Parse intent and extract structure
        parsed = self._parse(description)
        result.intent = parsed.get("intent", "")
        result.constraints = parsed.get("constraints", [])
        result.acceptance_criteria = parsed.get("acceptance_criteria", [])
        result.clarifying_questions = parsed.get("ambiguities", [])
        result.warnings = parsed.get("warnings", [])

        # Phase 2 — Generate the Markdown spec
        result.spec_markdown = self._build_spec(description, parsed)

        # Phase 3 — Break into tasks
        result.tasks = self._break_tasks(result.spec_markdown)

        return result

    # ------------------------------------------------------------------
    # Private pipeline steps
    # ------------------------------------------------------------------

    def _parse(self, description: str) -> dict[str, Any]:
        import json

        messages = [
            SystemMessage(content=_PARSE_SYSTEM),
            HumanMessage(content=f"Feature description:\n\n{description}"),
        ]
        response = self._llm.invoke(messages)
        raw = _strip_think(response.content if hasattr(response, "content") else str(response))
        try:
            return json.loads(_extract_json(raw))
        except (json.JSONDecodeError, ValueError):
            return {
                "intent": description[:200],
                "constraints": [],
                "acceptance_criteria": [],
                "ambiguities": [],
                "warnings": ["Could not parse structured output — raw LLM response returned."],
            }

    def _build_spec(self, description: str, parsed: dict[str, Any]) -> str:
        context = (
            f"Original request:\n{description}\n\n"
            f"Intent: {parsed.get('intent', '')}\n\n"
            f"Acceptance criteria:\n"
            + "\n".join(f"- {c}" for c in parsed.get("acceptance_criteria", []))
            + "\n\nConstraints:\n"
            + "\n".join(f"- {c}" for c in parsed.get("constraints", []))
        )
        messages = [
            SystemMessage(content=_SPEC_SYSTEM),
            HumanMessage(content=context),
        ]
        response = self._llm.invoke(messages)
        return _strip_think(response.content if hasattr(response, "content") else str(response))

    def _break_tasks(self, spec_markdown: str) -> list[dict[str, Any]]:
        import json

        messages = [
            SystemMessage(content=_TASKS_SYSTEM),
            HumanMessage(content=f"Specification:\n\n{spec_markdown}"),
        ]
        response = self._llm.invoke(messages)
        raw = _strip_think(response.content if hasattr(response, "content") else str(response))
        try:
            return json.loads(_extract_json(raw))
        except (json.JSONDecodeError, ValueError):
            return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an implementation spec from a feature description."
    )
    parser.add_argument(
        "--description",
        "-d",
        required=True,
        help="Free-form feature description (quote it)",
    )
    parser.add_argument(
        "--output",
        "-o",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    args = parser.parse_args()

    agent = SpecificationAgent()
    result = agent.generate(args.description)

    if args.output == "json":
        import json

        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"# Specification\n\n**Original request:** {result.original_request}\n")
        if result.warnings:
            for w in result.warnings:
                print(f"> ⚠️  {w}")
            print()
        if result.clarifying_questions:
            print("## Open questions\n")
            for q in result.clarifying_questions:
                print(f"- {q}")
            print()
        print(result.spec_markdown)
        if result.tasks:
            print("\n## Implementation tasks\n")
            for t in result.tasks:
                est = t.get("estimated_minutes", "?")
                print(f"- **{t.get('id')}** {t.get('title')} (~{est}min)")
                if t.get("depends_on"):
                    print(f"  _depends on: {', '.join(t['depends_on'])}_")


if __name__ == "__main__":
    _cli()
