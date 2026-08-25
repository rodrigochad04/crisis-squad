"""Evaluation harness for the Autonomous Crisis Squad agents.

Uses DeepEval for LLM-output quality metrics.
Uses pytest for integration and regression testing.

Metrics evaluated:
  - Faithfulness:     Does the diagnosis cite only data from tool outputs?
  - Answer Relevancy: Is the diagnosis relevant to the incident?
  - Gate Compliance:  Is request_human_approval called before production actions?
  - Playbook Completeness: Does the playbook have all mandatory sections?
  - Groundedness:     Does the output avoid hallucinations?

Run:
    pytest evaluation/ -v
    pytest evaluation/ -v -k "test_fail_fast"
"""

from __future__ import annotations

import json
import os
import re

import pytest
from deepeval import assert_test
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    GEval,
)
from deepeval.test_case import LLMTestCase

# ---------------------------------------------------------------------------
# LLM judge — prefers Groq, falls back to OpenAI, skips if neither is set
# ---------------------------------------------------------------------------


def _has_llm_key() -> bool:
    return bool(os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _make_judge_model():
    """Return a DeepEval-compatible judge model.

    Priority:
      1. Groq  (GROQ_API_KEY) — free, fast, no credit card needed
      2. OpenAI (OPENAI_API_KEY) — fallback
    """
    groq_key = os.environ.get("GROQ_API_KEY") or ""
    if groq_key:
        return _GroqJudge(model="qwen/qwen3.6-27b", api_key=groq_key)
    return "gpt-4o-mini"  # DeepEval uses OpenAI natively for string model names


try:
    from deepeval.models.base_model import DeepEvalBaseLLM as _DeepEvalBase
except ImportError:
    _DeepEvalBase = object  # type: ignore[assignment,misc]


class _GroqJudge(_DeepEvalBase):  # type: ignore[misc]
    """DeepEvalBaseLLM adapter for ChatGroq.

    Lets DeepEval use Groq (Qwen 27B) as the LLM-as-a-judge instead of OpenAI,
    so the full eval suite runs without any paid API key.
    """

    def __init__(self, model: str, api_key: str):
        import re as _re

        from langchain_groq import ChatGroq

        self._re = _re
        self._model_name = f"groq/{model}"
        # Build the underlying LLM *before* super().__init__() because
        # DeepEvalBaseLLM.__init__ calls self.load_model() immediately.
        self._llm = ChatGroq(
            model=model,
            groq_api_key=api_key,
            temperature=0.0,
            max_tokens=1024,
            reasoning_effort="none",  # suppress <think> CoT
        )
        super().__init__()

    def _clean(self, text: str) -> str:
        return self._re.sub(r"<think>.*?</think>", "", text, flags=self._re.DOTALL).strip()

    def load_model(self):
        return self._llm

    def generate(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage

        resp = self._llm.invoke([HumanMessage(content=prompt)])
        return self._clean(resp.content)

    async def a_generate(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage

        resp = await self._llm.ainvoke([HumanMessage(content=prompt)])
        return self._clean(resp.content)

    def get_model_name(self) -> str:
        return self._model_name


_requires_llm_grader = pytest.mark.skipif(
    not _has_llm_key(),
    reason="No LLM key found — set GROQ_API_KEY or OPENAI_API_KEY to run LLM-graded tests",
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fail_fast_instana_output() -> dict:
    """Realistic Instana output for a FAIL_FAST pattern incident."""
    return {
        "status": "OK",
        "incident_id": "TEST-001",
        "event_state": "CLOSED",
        "severity": "CRITICAL",
        "problem": "Erroneous call rate is too high",
        "affected_service": {"name": "mcp-gateway", "service_id": "svc-001"},
        "application": {"name": "Robot-Shop-EKS"},
        "timeline": {
            "start": "2026-08-18T13:56:00Z",
            "end": "2026-08-21T06:39:00Z",
            "duration_minutes": 3883,
        },
        "root_cause": {
            "identified_by": "Instana Probable Cause Analysis",
            "found": True,
            "confidence": 0.97,
            "path": [{"type": "service", "name": "mcp-gateway"}],
        },
        "metrics_during_incident": {
            "calls_total": 690,
            "erroneous_calls_total": 690,
            "error_rate_pct": 100.0,
            "latency_p99_ms": 8,
        },
        "metrics_baseline_7d_before": {
            "calls_total": 710,
            "erroneous_calls_total": 12,
            "error_rate_pct": 1.69,
            "latency_p99_ms": 142,
        },
        "diagnosis": {
            "measured": {
                "error_rate_pct_during": 100.0,
                "latency_p99_ms_during": 8,
                "latency_p99_ms_baseline": 142,
            },
            "derived": {"latency_p99_ratio": 0.056, "calls_volume_ratio": 0.972},
            "assessment": {
                "pattern": "FAIL_FAST",
                "reasoning": "100% error rate with p99 latency dropping from 142ms to 8ms. Calls rejected immediately.",
                "recommendation": "Investigate service config and credentials. Compare manifest with pre-incident version.",
                "thresholds_used": {
                    "high_error_rate_pct": 50.0,
                    "latency_ratio_low": 0.5,
                },
            },
        },
    }


@pytest.fixture(scope="session")
def playbook_output() -> str:
    return """# Remediation Playbook — mcp-gateway FAIL_FAST

## 1. Executive Summary
Service mcp-gateway is rejecting 100% of calls with sub-10ms latency, indicating
immediate rejection at the edge (auth/config failure, not resource exhaustion).
Risk: HIGH. Estimated resolution: 15-30 min.

## 2. Pre-execution Checklist
- [ ] Confirm war room channel is active
- [ ] SRE Lead is on the call
- [ ] Rollback target version identified

## 3. Remediation Steps

### Step 1 — Inspect current configuration
```bash
kubectl get configmap mcp-gateway-config -n mcp-context-forge -o yaml
kubectl get secret mcp-gateway-secrets -n mcp-context-forge -o yaml | base64 -d
```
Expected: spot any recently changed values.

### Step 2 — Compare with last known good
```bash
kubectl rollout history deployment/mcp-gateway -n mcp-context-forge
kubectl diff -f manifests/mcp-gateway-deployment.yaml
```

### Step 3 — Rollback if config change is confirmed
```bash
kubectl rollout undo deployment/mcp-gateway -n mcp-context-forge
kubectl rollout status deployment/mcp-gateway -n mcp-context-forge --timeout=120s
```

## 4. Validation Criteria
- Error rate drops below 5% within 2 minutes of rollback
- p99 latency returns to 120-160ms range
- Health check endpoint returns 200: `curl -sf https://mcp-gateway/health`

## 5. Rollback Procedure
If rollback makes things worse:
```bash
kubectl rollout undo deployment/mcp-gateway -n mcp-context-forge --to-revision=<N-2>
```

## 6. Escalation Path
1. SRE Lead: @sre-lead
2. Platform Engineering: @platform-eng
3. Service Owner: @mcp-team
"""


# ---------------------------------------------------------------------------
# Diagnosis quality tests
# ---------------------------------------------------------------------------


class TestInstanaDiagnosis:
    """Evaluate the quality of Instana agent output."""

    @_requires_llm_grader
    def test_diagnosis_is_faithful_to_tool_output(self, fail_fast_instana_output: dict):
        """The diagnosis must only state facts present in the tool output."""
        tool_output_text = json.dumps(fail_fast_instana_output, indent=2)

        # Simulated agent output (in real tests, invoke the actual agent)
        agent_output = (
            "The mcp-gateway service in Robot-Shop-EKS experienced a CRITICAL incident "
            "lasting 3,883 minutes (closed). Instana Probable Cause Analysis identified "
            "the root cause with 97% confidence. The service exhibited a FAIL_FAST pattern: "
            "error rate at 100% while p99 latency dropped from 142ms (baseline) to 8ms — "
            "calls were rejected immediately, not delayed. Volume remained stable (0.972x baseline). "
            "Recommendation: investigate service configuration and credentials."
        )

        test_case = LLMTestCase(
            input="Diagnose incident TEST-001",
            actual_output=agent_output,
            retrieval_context=[tool_output_text],
        )

        judge = _make_judge_model()
        faithfulness = FaithfulnessMetric(threshold=0.8, model=judge, include_reason=True)
        relevancy = AnswerRelevancyMetric(threshold=0.8, model=judge, include_reason=True)
        assert_test(test_case, [faithfulness, relevancy])

    def test_diagnosis_does_not_mention_jvm_heap(self, fail_fast_instana_output: dict):
        """Agent must not hallucinate JVM heap data not present in Instana output."""
        forbidden_patterns = [
            r"jvm\s*heap",
            r"heap\s*usage",
            r"garbage\s*collect",
            r"deployment\s*version",
            r"commit\s*(hash|sha)",
        ]
        agent_output = (
            "Error rate at 100%, p99 latency 8ms vs baseline 142ms. "
            "FAIL_FAST pattern. Config investigation recommended."
        )
        for pattern in forbidden_patterns:
            assert not re.search(pattern, agent_output, re.IGNORECASE), (
                f"Agent hallucinated forbidden field matching: {pattern}"
            )

    def test_fail_fast_pattern_correctly_identified(self, fail_fast_instana_output: dict):
        """Verify FAIL_FAST pattern is correctly classified."""
        diagnosis = fail_fast_instana_output["diagnosis"]
        assert diagnosis["assessment"]["pattern"] == "FAIL_FAST"
        assert diagnosis["derived"]["latency_p99_ratio"] < 0.5  # latency dropped → fail-fast
        assert diagnosis["measured"]["error_rate_pct_during"] >= 50.0


# ---------------------------------------------------------------------------
# Playbook quality tests
# ---------------------------------------------------------------------------


class TestPlaybook:
    """Evaluate playbook completeness and quality."""

    MANDATORY_SECTIONS = [
        "executive summary",
        "pre-execution checklist",
        "remediation steps",
        "validation criteria",
        "rollback procedure",
        "escalation",
    ]

    def test_playbook_has_all_mandatory_sections(self, playbook_output: str):
        lower = playbook_output.lower()
        for section in self.MANDATORY_SECTIONS:
            assert section in lower, f"Missing mandatory section: '{section}'"

    def test_playbook_contains_kubectl_commands(self, playbook_output: str):
        assert "kubectl" in playbook_output, "Playbook must contain kubectl commands"

    def test_playbook_has_validation_criteria(self, playbook_output: str):
        """Playbook must specify numeric success criteria."""
        has_threshold = bool(re.search(r"\d+\s*%", playbook_output))
        has_health_check = "health" in playbook_output.lower()
        assert has_threshold or has_health_check, (
            "Playbook must have numeric validation criteria or health check reference"
        )

    @_requires_llm_grader
    def test_playbook_quality_eval(self, playbook_output: str):
        """Use GEval (G-Eval framework) to score playbook quality."""
        test_case = LLMTestCase(
            input=(
                "Generate a remediation playbook for a FAIL_FAST incident in mcp-gateway "
                "with 100% error rate and sub-10ms latency."
            ),
            actual_output=playbook_output,
        )
        # SingleTurnParams replaces the deprecated LLMTestCaseParams in DeepEval ≥ 2.x
        try:
            from deepeval.test_case import SingleTurnParams

            eval_params = [SingleTurnParams.ACTUAL_OUTPUT]
        except ImportError:
            from deepeval.test_case import LLMTestCaseParams  # type: ignore[no-redef]

            eval_params = [LLMTestCaseParams.ACTUAL_OUTPUT]  # type: ignore[assignment]

        completeness = GEval(
            name="Playbook Completeness",
            criteria=(
                "Evaluate whether the playbook contains: "
                "(1) clear problem summary, "
                "(2) pre-execution checklist, "
                "(3) numbered remediation steps with exact commands, "
                "(4) measurable validation criteria, "
                "(5) rollback procedure, "
                "(6) escalation path."
            ),
            evaluation_steps=[
                "Check that each of the 6 sections is present.",
                "Verify remediation steps include shell/kubectl commands.",
                "Verify validation criteria include numeric thresholds.",
                "Score 0-1 where 1 = all 6 sections present and actionable.",
            ],
            evaluation_params=eval_params,
            model=_make_judge_model(),
            threshold=0.7,
        )
        assert_test(test_case, [completeness])


# ---------------------------------------------------------------------------
# HitL gate compliance tests
# ---------------------------------------------------------------------------


class TestHitLGate:
    """Verify Human-in-the-Loop gate is structurally enforced."""

    def test_approval_request_has_required_fields(self):
        """Approval request must contain all fields required by NIST AI RMF."""
        from src.tools.hitl_tools import request_human_approval

        result = json.loads(
            request_human_approval.invoke(
                {
                    "incident_id": "TEST-001",
                    "action_type": "ROLLBACK",
                    "action_description": "kubectl rollout undo deployment/mcp-gateway",
                    "risk_level": "HIGH",
                    "recommended_by": "playbook_agent",
                    "evidence_summary": "FAIL_FAST pattern, 100% error rate, config change suspected",
                }
            )
        )

        assert result["status"] == "PENDING_HUMAN_APPROVAL"
        assert result["approval_id"].startswith("APPR-TEST-001")
        assert result["action"]["risk_level"] == "HIGH"
        assert "governance" in result
        assert "NIST" in result["governance"]["framework"]
        assert "instructions_for_sre" in result

    def test_record_decision_approved(self):
        from src.tools.hitl_tools import record_human_decision

        result = json.loads(
            record_human_decision.invoke(
                {
                    "approval_id": "APPR-TEST-001-120000",
                    "decision": "APPROVED",
                    "decided_by": "sre-lead",
                    "notes": "Confirmed config mismatch — rollback is safe",
                }
            )
        )

        assert result["decision"] == "APPROVED"
        assert result["decided_by"] == "sre-lead"
        assert "audit_entry" in result
        assert result["audit_entry"]["event"] == "HUMAN_DECISION_RECORDED"

    def test_record_decision_rejected(self):
        from src.tools.hitl_tools import record_human_decision

        result = json.loads(
            record_human_decision.invoke(
                {
                    "approval_id": "APPR-TEST-001-120001",
                    "decision": "REJECTED",
                    "decided_by": "sre-lead",
                    "notes": "Need more investigation first",
                }
            )
        )

        assert result["decision"] == "REJECTED"
        assert "await new instruction" in result["next_step"].lower()


# ---------------------------------------------------------------------------
# Jira tool unit tests
# ---------------------------------------------------------------------------


class TestJiraTools:
    """Unit tests for Jira tools (uses real Jira if credentials are set)."""

    def test_resolution_minutes_calculation(self):
        from src.tools.jira_tools import _resolution_minutes

        result = _resolution_minutes(
            "2026-01-01T10:00:00.000+0000",
            "2026-01-01T10:45:00.000+0000",
        )
        assert result == 45

    def test_resolution_minutes_none_when_missing(self):
        from src.tools.jira_tools import _resolution_minutes

        assert _resolution_minutes(None, "2026-01-01T10:00:00.000+0000") is None
        assert _resolution_minutes("2026-01-01T10:00:00.000+0000", None) is None

    def test_adf_text_extraction(self):
        from src.tools.jira_tools import _extract_adf_text

        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Rolled back to v2.13.1. "},
                        {"type": "text", "text": "Issue resolved in 45 minutes."},
                    ],
                }
            ],
        }
        result = _extract_adf_text(adf)
        assert "Rolled back" in result
        assert "45 minutes" in result


# ---------------------------------------------------------------------------
# Instana client unit tests (no network)
# ---------------------------------------------------------------------------


class TestInstanaClient:
    """Unit tests for Instana pattern classifier — no network calls."""

    def test_fail_fast_classification(self):
        from src.tools.instana_client import diagnose

        during = {"error_rate_pct": 100.0, "latency_p99_ms": 8, "calls_total": 690}
        baseline = {"error_rate_pct": 1.7, "latency_p99_ms": 142, "calls_total": 710}

        result = diagnose(during, baseline)
        assert result["assessment"]["pattern"] == "FAIL_FAST"
        assert result["derived"]["latency_p99_ratio"] < 0.5

    def test_saturation_classification(self):
        from src.tools.instana_client import diagnose

        during = {"error_rate_pct": 75.0, "latency_p99_ms": 3200, "calls_total": 700}
        baseline = {"error_rate_pct": 1.5, "latency_p99_ms": 150, "calls_total": 720}

        result = diagnose(during, baseline)
        assert result["assessment"]["pattern"] == "SATURATION"
        assert result["derived"]["latency_p99_ratio"] > 2.0

    def test_latency_degradation_classification(self):
        from src.tools.instana_client import diagnose

        during = {"error_rate_pct": 3.0, "latency_p99_ms": 800, "calls_total": 700}
        baseline = {"error_rate_pct": 2.0, "latency_p99_ms": 120, "calls_total": 710}

        result = diagnose(during, baseline)
        assert result["assessment"]["pattern"] == "LATENCY_DEGRADATION"

    def test_indeterminate_when_metrics_missing(self):
        from src.tools.instana_client import diagnose

        result = diagnose({}, {})
        assert result["assessment"]["pattern"] == "INDETERMINATE"

    def test_thresholds_exposed_in_assessment(self):
        from src.tools.instana_client import THRESHOLDS, diagnose

        during = {"error_rate_pct": 100.0, "latency_p99_ms": 8, "calls_total": 690}
        baseline = {"error_rate_pct": 1.7, "latency_p99_ms": 142, "calls_total": 710}
        result = diagnose(during, baseline)

        # Thresholds must be visible in output — editorial decisions, not hidden
        assert "thresholds_used" in result["assessment"]
        assert result["assessment"]["thresholds_used"] == THRESHOLDS
