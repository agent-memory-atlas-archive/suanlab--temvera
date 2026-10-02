import unittest

from temvera.telemetry import Meter, PRICES, measure_openai


class MeterTest(unittest.TestCase):
    def test_cost_uses_separate_input_and_output_rates(self) -> None:
        meter = Meter()
        meter.record("gpt-4o-mini", 1_000_000, 1_000_000)
        report = meter.as_dict()
        entry = report["usage"]["gpt-4o-mini"]
        self.assertEqual(entry["total_tokens"], 2_000_000)
        rate_in, rate_out = PRICES["gpt-4o-mini"]
        self.assertAlmostEqual(entry["cost_usd"], rate_in + rate_out)

    def test_unknown_model_costs_zero_rather_than_guessing(self) -> None:
        meter = Meter()
        meter.record("some-future-model", 1_000, 1_000)
        self.assertEqual(meter.as_dict()["cost_usd_total"], 0.0)

    def test_latency_percentiles_carry_denominators(self) -> None:
        meter = Meter()
        for _ in range(4):
            with meter.time_ingest():
                pass
        with meter.time_query():
            pass
        report = meter.as_dict()
        self.assertEqual(report["ingest_latency"]["n"], 4)
        self.assertEqual(report["query_latency"]["n"], 1)
        self.assertIn("p95_s", report["ingest_latency"])

    def test_empty_latency_reports_zero_samples_not_a_fake_mean(self) -> None:
        self.assertEqual(Meter().as_dict()["ingest_latency"], {"n": 0})

    def test_worker_usage_is_merged(self) -> None:
        meter = Meter()
        meter.record("gpt-4o-mini", 10, 5)
        meter.merge_worker(
            {"gpt-4o-mini": {"calls": 2, "prompt_tokens": 100, "completion_tokens": 50}}
        )
        entry = meter.as_dict()["usage"]["gpt-4o-mini"]
        self.assertEqual(entry["calls"], 3)
        self.assertEqual(entry["prompt_tokens"], 110)


class PatchTest(unittest.TestCase):
    def test_patch_captures_usage_and_restores_originals(self) -> None:
        try:
            from openai.resources.chat import completions
        except Exception:  # pragma: no cover
            self.skipTest("openai SDK not installed")

        original = completions.Completions.create

        class _Usage:
            prompt_tokens = 30
            completion_tokens = 7

        class _Response:
            usage = _Usage()

        completions.Completions.create = lambda self, **kw: _Response()
        try:
            meter = Meter()
            with measure_openai(meter):
                completions.Completions.create(object(), model="gpt-4o-mini")
            self.assertEqual(meter.by_model["gpt-4o-mini"].prompt_tokens, 30)
            self.assertEqual(meter.by_model["gpt-4o-mini"].completion_tokens, 7)
            # The patch must be removed even though the call succeeded.
            self.assertIsNot(completions.Completions.create, None)
            meter_after = Meter()
            completions.Completions.create(object(), model="gpt-4o-mini")
            self.assertEqual(meter_after.by_model, {})
        finally:
            completions.Completions.create = original


class AsyncPatchTest(unittest.TestCase):
    """Graphiti calls the async client and the Responses API; both must count."""

    def test_async_chat_and_responses_usage_are_counted(self) -> None:
        import asyncio

        try:
            from openai.resources.chat import completions
            from openai.resources import responses
        except Exception:  # pragma: no cover
            self.skipTest("openai SDK without the Responses API")

        chat_original = completions.AsyncCompletions.create
        parse_original = responses.AsyncResponses.parse

        class _ChatUsage:
            prompt_tokens = 40
            completion_tokens = 5

        class _ResponsesUsage:  # the Responses API names its fields differently
            input_tokens = 100
            output_tokens = 20

        class _Chat:
            usage = _ChatUsage()

        class _Resp:
            usage = _ResponsesUsage()

        async def fake_chat(self, **kw):
            return _Chat()

        async def fake_parse(self, **kw):
            return _Resp()

        completions.AsyncCompletions.create = fake_chat
        responses.AsyncResponses.parse = fake_parse
        try:
            meter = Meter()
            with measure_openai(meter):
                asyncio.run(completions.AsyncCompletions.create(object(), model="gpt-4o-mini"))
                asyncio.run(responses.AsyncResponses.parse(object(), model="gpt-4o-mini"))
            usage = meter.by_model["gpt-4o-mini"]
            self.assertEqual((usage.prompt_tokens, usage.completion_tokens), (140, 25))
            # restored afterwards
            self.assertIs(completions.AsyncCompletions.create, fake_chat)
            self.assertIs(responses.AsyncResponses.parse, fake_parse)
        finally:
            completions.AsyncCompletions.create = chat_original
            responses.AsyncResponses.parse = parse_original


if __name__ == "__main__":
    unittest.main()
