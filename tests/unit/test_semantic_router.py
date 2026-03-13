# tests/unit/test_semantic_router.py
"""
Unit tests for the semantic intent router.

These tests load the real BAAI/bge-small-en-v1.5 model, which takes ~5 s on
first run (downloaded to .model_cache/).  They are marked @pytest.mark.slow
and can be skipped with: pytest --fast
"""
import pytest


@pytest.fixture(scope="module")
def router():
    """Load the singleton router once for the whole test module."""
    from agents.semantic_router import semantic_router
    return semantic_router


# ── Return-type contract ───────────────────────────────────────
@pytest.mark.slow
class TestReturnContract:
    def test_returns_two_element_tuple(self, router):
        result = router.classify_intent("hello")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_intent_is_string(self, router):
        intent, _ = router.classify_intent("hello")
        assert isinstance(intent, str)

    def test_confidence_is_float(self, router):
        _, conf = router.classify_intent("hello")
        assert isinstance(conf, float)

    def test_confidence_in_unit_interval(self, router):
        _, conf = router.classify_intent("Write a Python class")
        assert 0.0 <= conf <= 1.0

    def test_confidence_rounded_to_3dp(self, router):
        _, conf = router.classify_intent("debug my React component")
        # round() to 3 decimal places means at most 3 sig figs after the point
        assert conf == round(conf, 3)


# ── Intent routing accuracy ────────────────────────────────────
@pytest.mark.slow
class TestIntentRouting:
    def test_financial_quant_options(self, router):
        intent, conf = router.classify_intent(
            "What is the implied volatility of NVDA options?"
        )
        assert intent == "financial_quant"
        assert conf >= 0.5

    def test_financial_quant_bull_put(self, router):
        intent, _ = router.classify_intent(
            "Calculate the max loss for a bull put spread on SPY"
        )
        assert intent == "financial_quant"

    def test_code_assistant_python(self, router):
        intent, conf = router.classify_intent("Write a Python script to parse JSON")
        assert intent == "code_assistant"
        assert conf >= 0.5

    def test_code_assistant_debug(self, router):
        intent, _ = router.classify_intent("Debug this React component for me")
        assert intent == "code_assistant"

    def test_code_assistant_regex(self, router):
        intent, _ = router.classify_intent("Explain this regex pattern to me")
        assert intent == "code_assistant"

    def test_casual_chat_greeting(self, router):
        intent, _ = router.classify_intent("Hello, how are you today?")
        assert intent == "casual_chat"

    def test_casual_chat_joke(self, router):
        intent, _ = router.classify_intent("Tell me a joke")
        assert intent == "casual_chat"

    def test_low_confidence_falls_back_to_casual(self, router):
        # Gibberish — no anchor matches well, must fall back to casual_chat
        intent, _ = router.classify_intent("xzqw bzzk pllm 12345 %%%%")
        assert intent == "casual_chat"

    def test_known_routes_are_registered(self, router):
        expected = {"casual_chat", "financial_quant", "code_assistant"}
        assert set(router.routes.keys()) == expected

    def test_clear_query_beats_vague(self, router):
        _, conf_clear = router.classify_intent(
            "calculate the max loss for this bull put spread"
        )
        _, conf_vague = router.classify_intent("some random words here maybe")
        assert conf_clear >= conf_vague
