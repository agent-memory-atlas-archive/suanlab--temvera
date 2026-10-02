"""Measured cost and latency for external-system runs.

VLDB reviewers expect a cost and latency dimension, and an earlier draft
described one extractor as "costlier" with no measurement behind it. This module
measures rather than estimates.

Token usage is captured by patching the two OpenAI resource methods every
in-process system ultimately calls (`chat.completions.create` and
`embeddings.create`) and accumulating the `usage` block each response carries.
That covers Mem0 and Graphiti, which run in this process. LangMem runs behind a
stdio worker, so its worker reports its own usage and the adapter adds it in.

Prices are per million tokens and must be kept in sync with the provider's
published rates; they are recorded in the run so a stale price is visible rather
than silently baked into a dollar figure.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

# USD per million tokens. Update alongside provider pricing changes; the run
# records these values so any figure can be recomputed at a different rate.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
}


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int) -> None:
        self.calls += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion

    def cost(self, model: str) -> float:
        rate_in, rate_out = PRICES.get(model, (0.0, 0.0))
        return (
            self.prompt_tokens * rate_in + self.completion_tokens * rate_out
        ) / 1_000_000


@dataclass
class Meter:
    """Accumulates per-model token usage and per-operation latency."""

    by_model: dict[str, Usage] = field(default_factory=dict)
    ingest_seconds: list[float] = field(default_factory=list)
    query_seconds: list[float] = field(default_factory=list)

    def record(self, model: str, prompt: int, completion: int) -> None:
        self.by_model.setdefault(model, Usage()).add(prompt, completion)

    def merge_worker(self, payload: dict[str, Any]) -> None:
        """Fold in usage reported by an out-of-process worker."""
        for model, entry in (payload or {}).items():
            usage = self.by_model.setdefault(model, Usage())
            usage.calls += int(entry.get("calls", 0))
            usage.prompt_tokens += int(entry.get("prompt_tokens", 0))
            usage.completion_tokens += int(entry.get("completion_tokens", 0))

    @contextmanager
    def time_ingest(self):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.ingest_seconds.append(time.perf_counter() - start)

    @contextmanager
    def time_query(self):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.query_seconds.append(time.perf_counter() - start)

    def as_dict(self) -> dict[str, Any]:
        def percentiles(values: list[float]) -> dict[str, float]:
            if not values:
                return {"n": 0}
            ordered = sorted(values)

            def at(q: float) -> float:
                index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
                return ordered[index]

            return {
                "n": len(ordered),
                "mean_s": sum(ordered) / len(ordered),
                "p50_s": at(0.50),
                "p95_s": at(0.95),
                "total_s": sum(ordered),
            }

        return {
            "prices_usd_per_million": PRICES,
            "usage": {
                model: {
                    "calls": usage.calls,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "cost_usd": usage.cost(model),
                }
                for model, usage in sorted(self.by_model.items())
            },
            "cost_usd_total": sum(u.cost(m) for m, u in self.by_model.items()),
            "ingest_latency": percentiles(self.ingest_seconds),
            "query_latency": percentiles(self.query_seconds),
        }


def _record(meter: Meter, kwargs: dict, response) -> None:
    """Count a response's tokens, whichever API shape returned it.

    Chat completions report ``prompt_tokens``/``completion_tokens``; the
    Responses API reports ``input_tokens``/``output_tokens``.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    prompt = getattr(usage, "prompt_tokens", None)
    if prompt is None:
        prompt = getattr(usage, "input_tokens", 0)
    completion = getattr(usage, "completion_tokens", None)
    if completion is None:
        completion = getattr(usage, "output_tokens", 0)
    meter.record(str(kwargs.get("model", "unknown")), int(prompt or 0), int(completion or 0))


@contextmanager
def measure_openai(meter: Meter):
    """Patch OpenAI resource methods so every in-process call is counted.

    Patching the resource classes rather than a client instance catches all
    clients, including ones a library constructs internally. Both the sync and
    the async clients are covered, and the Responses API alongside chat
    completions: Graphiti calls ``AsyncOpenAI().responses.parse``, and an
    earlier version that patched only the sync ``create`` methods recorded its
    runs at $0.00 while it was making hundreds of calls. If the SDK is not
    importable the block is a no-op, so offline tests still run.
    """
    try:
        from openai.resources.chat import completions as chat_completions
        from openai.resources import embeddings as embeddings_module
    except Exception:  # pragma: no cover - SDK absent
        yield meter
        return

    sync_targets = [
        (chat_completions.Completions, "create"),
        (embeddings_module.Embeddings, "create"),
    ]
    async_targets = [
        (chat_completions.AsyncCompletions, "create"),
        (embeddings_module.AsyncEmbeddings, "create"),
    ]
    try:
        from openai.resources import responses as responses_module

        sync_targets += [(responses_module.Responses, "create"),
                         (responses_module.Responses, "parse")]
        async_targets += [(responses_module.AsyncResponses, "create"),
                          (responses_module.AsyncResponses, "parse")]
    except Exception:  # pragma: no cover - SDK predates the Responses API
        pass
    sync_targets = [(c, n) for c, n in sync_targets if hasattr(c, n)]
    async_targets = [(c, n) for c, n in async_targets if hasattr(c, n)]
    originals = [(cls, name, getattr(cls, name)) for cls, name in sync_targets + async_targets]

    def wrap(original):
        def wrapped(self, *args, **kwargs):
            response = original(self, *args, **kwargs)
            _record(meter, kwargs, response)
            return response

        return wrapped

    def wrap_async(original):
        async def wrapped(self, *args, **kwargs):
            response = await original(self, *args, **kwargs)
            _record(meter, kwargs, response)
            return response

        return wrapped

    try:
        for cls, name in sync_targets:
            setattr(cls, name, wrap(getattr(cls, name)))
        for cls, name in async_targets:
            setattr(cls, name, wrap_async(getattr(cls, name)))
        yield meter
    finally:
        for cls, name, original in originals:
            setattr(cls, name, original)
