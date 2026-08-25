"""Tests for SpecificationAgent and CostTracker."""

from __future__ import annotations

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------


class TestCostTracker:
    def test_records_call_and_estimates_cost(self):
        from src.evaluation.cost_tracker import CostTracker

        tracker = CostTracker()
        record = tracker.record_call(
            model="qwen/qwen3.6-27b",
            prompt_tokens=1000,
            completion_tokens=500,
            run_id="test-run",
            node="playbook",
        )
        assert record.prompt_tokens == 1000
        assert record.completion_tokens == 500
        assert record.total_tokens == 1500
        assert record.cost_usd > 0.0

    def test_summary_aggregates_correctly(self):
        from src.evaluation.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record_call("qwen/qwen3.6-27b", 1000, 200, run_id="run-1")
        tracker.record_call("qwen/qwen3.6-27b", 800, 150, run_id="run-1")
        tracker.record_call("qwen/qwen3.6-27b", 500, 100, run_id="run-2")

        summary = tracker.summary()
        assert summary["total_calls"] == 3
        assert summary["total_tokens"] == 1200 + 950 + 600
        assert "run-1" in summary["by_run"]
        assert summary["by_run"]["run-1"]["calls"] == 2

    def test_cost_for_run(self):
        from src.evaluation.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record_call("qwen/qwen3.6-27b", 1000, 200, run_id="run-abc")
        cost = tracker.cost_for_run("run-abc")
        assert cost > 0.0

    def test_unknown_model_uses_default_pricing(self):
        from src.evaluation.cost_tracker import _estimate_cost_usd

        cost = _estimate_cost_usd("unknown-model-xyz", 1000, 500)
        assert cost > 0.0

    def test_reset_clears_all_calls(self):
        from src.evaluation.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record_call("qwen/qwen3.6-27b", 100, 50)
        tracker.reset()
        assert tracker.summary()["total_calls"] == 0


# ---------------------------------------------------------------------------
# SpecificationAgent tests (unit — mocked LLM)
# ---------------------------------------------------------------------------

_MOCK_PARSE_JSON = """{
    "intent": "Allow users to export incident reports as PDF",
    "constraints": ["must work offline", "no external PDF service"],
    "acceptance_criteria": ["PDF generated in < 3s", "includes all phase timings"],
    "ambiguities": ["Which pages to include?"],
    "warnings": []
}"""

_MOCK_SPEC_MD = """\
# Feature: PDF Export for Incident Reports

## Summary
Generates a downloadable PDF from the incident response data.

## Acceptance Criteria
- [ ] PDF generated in < 3s
- [ ] Includes all phase timings

## Technical Approach
Use WeasyPrint or ReportLab to render the incident JSON as PDF.

## Out of Scope
Real-time streaming to PDF.
"""

_MOCK_TASKS_JSON = """[
    {"id": "T-01", "title": "Add PDF generation utility", "description": "...",
     "files_likely_affected": ["src/api/server.py"], "estimated_minutes": 60, "depends_on": []},
    {"id": "T-02", "title": "Add GET /incidents/{id}/pdf endpoint", "description": "...",
     "files_likely_affected": ["src/api/server.py"], "estimated_minutes": 30, "depends_on": ["T-01"]}
]"""


class TestSpecificationAgent:
    def _make_mock_llm(self, responses: list[str]):
        """Returns a mock LLM that returns responses in sequence."""
        mock_llm = MagicMock()
        mock_responses = [MagicMock(content=r) for r in responses]
        mock_llm.invoke.side_effect = mock_responses
        return mock_llm

    def test_generate_returns_structured_result(self):
        from src.agents.specification_agent import SpecificationAgent, SpecificationResult

        llm = self._make_mock_llm([_MOCK_PARSE_JSON, _MOCK_SPEC_MD, _MOCK_TASKS_JSON])
        agent = SpecificationAgent(llm=llm)
        result = agent.generate("Allow users to export incident reports as PDF")

        assert isinstance(result, SpecificationResult)
        assert result.intent == "Allow users to export incident reports as PDF"
        assert len(result.constraints) == 2
        assert len(result.acceptance_criteria) == 2
        assert len(result.clarifying_questions) == 1
        assert "PDF Export" in result.spec_markdown
        assert len(result.tasks) == 2

    def test_generate_handles_invalid_json_gracefully(self):
        from src.agents.specification_agent import SpecificationAgent

        # LLM returns garbage JSON for parse phase
        llm = self._make_mock_llm(["NOT VALID JSON", _MOCK_SPEC_MD, "[]"])
        agent = SpecificationAgent(llm=llm)
        result = agent.generate("Some feature")
        # Should not raise; warnings should note the parse failure
        assert isinstance(result.warnings, list)
        assert len(result.warnings) > 0

    def test_tasks_have_required_fields(self):
        from src.agents.specification_agent import SpecificationAgent

        llm = self._make_mock_llm([_MOCK_PARSE_JSON, _MOCK_SPEC_MD, _MOCK_TASKS_JSON])
        agent = SpecificationAgent(llm=llm)
        result = agent.generate("Export PDF")
        for task in result.tasks:
            assert "id" in task
            assert "title" in task
            assert "estimated_minutes" in task

    def test_to_dict_is_serialisable(self):
        import json

        from src.agents.specification_agent import SpecificationAgent

        llm = self._make_mock_llm([_MOCK_PARSE_JSON, _MOCK_SPEC_MD, _MOCK_TASKS_JSON])
        agent = SpecificationAgent(llm=llm)
        result = agent.generate("Export PDF")
        # Should not raise
        serialised = json.dumps(result.to_dict())
        assert len(serialised) > 10
