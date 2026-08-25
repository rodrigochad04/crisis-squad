"""LLM cost and token usage tracker.

Instruments every LangChain / LangGraph LLM call to track:
  - Token usage (prompt / completion / total) per call
  - Estimated cost in USD per call (using published Groq pricing)
  - Cost per incident run
  - Cumulative session cost

Exposed via:
  GET /metrics/dora  — cost summary embedded in the DORA response
  GET /metrics/traces — per-span token attributes

Usage
-----
Wrap any ChatGroq (or any BaseChatModel) with the tracker:

    from src.evaluation.cost_tracker import CostTracker, CostCallbackHandler
    from langchain_groq import ChatGroq

    llm = ChatGroq(model="qwen/qwen3.6-27b", callbacks=[CostCallbackHandler()])

Or use the module-level singleton (used by the graph):

    from src.evaluation.cost_tracker import cost_tracker
    cost_tracker.record_call(model, prompt_tokens, completion_tokens)

Pricing reference (as of 2025 — update as needed):
    https://console.groq.com/docs/openai
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

# ---------------------------------------------------------------------------
# Pricing table — USD per 1M tokens (input / output)
# Update whenever Groq publishes new rates.
# ---------------------------------------------------------------------------
_PRICING: dict[str, tuple[float, float]] = {
    # model_name: (input_per_1m, output_per_1m)
    "qwen/qwen3.6-27b": (0.29, 0.59),
    "qwen3-32b": (0.79, 0.99),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama3-8b-8192": (0.05, 0.08),
    "gemma2-9b-it": (0.20, 0.20),
    # Fallback for unknown models
    "__default__": (0.50, 0.50),
}


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated USD cost for a single LLM call."""
    # Normalise model name — strip provider prefix
    key = model.lower().replace("groq/", "").replace("openai/", "")
    rates = _PRICING.get(key, _PRICING["__default__"])
    cost = (prompt_tokens * rates[0] + completion_tokens * rates[1]) / 1_000_000
    return round(cost, 8)


# ---------------------------------------------------------------------------
# Call record
# ---------------------------------------------------------------------------


class LLMCallRecord:
    __slots__ = (
        "ts",
        "run_id",
        "model",
        "node",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
    )

    def __init__(
        self,
        run_id: str,
        model: str,
        node: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        self.ts = datetime.now(UTC).isoformat()
        self.run_id = run_id
        self.model = model
        self.node = node
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.cost_usd = _estimate_cost_usd(model, prompt_tokens, completion_tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "run_id": self.run_id,
            "model": self.model,
            "node": self.node,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
        }


# ---------------------------------------------------------------------------
# CostTracker — thread-safe singleton
# ---------------------------------------------------------------------------


class CostTracker:
    """Accumulates LLM call records and exposes aggregate cost metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[LLMCallRecord] = []

    def record_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        run_id: str = "",
        node: str = "",
    ) -> LLMCallRecord:
        record = LLMCallRecord(run_id, model, node, prompt_tokens, completion_tokens)
        with self._lock:
            self._calls.append(record)
        return record

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        with self._lock:
            calls = list(self._calls)
        if not calls:
            return {"total_calls": 0, "total_tokens": 0, "total_cost_usd": 0.0, "calls": []}

        total_tokens = sum(c.total_tokens for c in calls)
        total_cost = round(sum(c.cost_usd for c in calls), 6)

        # Per-model breakdown
        by_model: dict[str, dict[str, Any]] = {}
        for c in calls:
            if c.model not in by_model:
                by_model[c.model] = {"calls": 0, "tokens": 0, "cost_usd": 0.0}
            by_model[c.model]["calls"] += 1
            by_model[c.model]["tokens"] += c.total_tokens
            by_model[c.model]["cost_usd"] = round(by_model[c.model]["cost_usd"] + c.cost_usd, 6)

        # Per-run breakdown
        by_run: dict[str, dict[str, Any]] = {}
        for c in calls:
            rid = c.run_id or "unknown"
            if rid not in by_run:
                by_run[rid] = {"calls": 0, "tokens": 0, "cost_usd": 0.0}
            by_run[rid]["calls"] += 1
            by_run[rid]["tokens"] += c.total_tokens
            by_run[rid]["cost_usd"] = round(by_run[rid]["cost_usd"] + c.cost_usd, 6)

        return {
            "total_calls": len(calls),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "avg_cost_per_call_usd": round(total_cost / len(calls), 6),
            "by_model": by_model,
            "by_run": by_run,
            "recent_calls": [c.to_dict() for c in calls[-10:]],
        }

    def cost_for_run(self, run_id: str) -> float:
        with self._lock:
            return round(sum(c.cost_usd for c in self._calls if c.run_id == run_id), 6)

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()


# ---------------------------------------------------------------------------
# LangChain callback handler — auto-records usage from LLM responses
# ---------------------------------------------------------------------------


class CostCallbackHandler(BaseCallbackHandler):
    """Attach to any LangChain LLM to capture token usage automatically.

    Example:
        llm = ChatGroq(model="qwen/qwen3.6-27b",
                       callbacks=[CostCallbackHandler(run_id="abc", node="playbook")])
    """

    def __init__(self, run_id: str = "", node: str = "") -> None:
        super().__init__()
        self.run_id = run_id
        self.node = node

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:  # noqa: ANN401
        """Called by LangChain after every LLM completion."""
        usage = getattr(response, "llm_output", {}) or {}
        token_usage = usage.get("token_usage", {})
        if not token_usage:
            # Some providers put it in the generation info
            for gen_list in response.generations:
                for gen in gen_list:
                    info = getattr(gen, "generation_info", {}) or {}
                    token_usage = info.get("usage", {})
                    if token_usage:
                        break
                if token_usage:
                    break

        prompt_tokens = int(token_usage.get("prompt_tokens", 0))
        completion_tokens = int(token_usage.get("completion_tokens", 0))
        if prompt_tokens == 0 and completion_tokens == 0:
            return  # No usage data available

        model = usage.get("model_name", "unknown")
        cost_tracker.record_call(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            run_id=self.run_id,
            node=self.node,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
cost_tracker = CostTracker()
