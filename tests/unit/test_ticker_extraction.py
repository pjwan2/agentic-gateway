# tests/unit/test_ticker_extraction.py
"""
Unit tests for the _extract_ticker() helper in main.py.
Pure logic, no external dependencies.
"""
import pytest


@pytest.fixture(scope="module")
def extract():
    # Import only the helper — avoids spinning up the full FastAPI app
    import importlib, sys
    # We need to import main but it triggers litellm / settings at module level.
    # Use a direct import of the function by loading main as a module.
    import main as m
    return m._extract_ticker


class TestExtractTicker:
    def test_dollar_notation_preferred(self, extract):
        assert extract("Analyze $NVDA options") == "NVDA"

    def test_dollar_notation_beats_plain_uppercase(self, extract):
        # "$SPY" should win over any plain uppercase word
        assert extract("What is $SPY doing vs QQQ") == "SPY"

    def test_plain_uppercase_fallback(self, extract):
        assert extract("Analyze AAPL stock") == "AAPL"

    def test_stop_words_are_filtered(self, extract):
        # "I", "A", "AI", "US" etc. must not be picked up as tickers
        result = extract("I want AI advice on US markets")
        assert result == "SPY"   # no valid ticker → default

    def test_default_is_spy(self, extract):
        assert extract("what should i do today") == "SPY"

    def test_five_letter_ticker(self, extract):
        assert extract("Analyze $GOOGL options") == "GOOGL"

    def test_lowercase_query_returns_default(self, extract):
        # No uppercase words at all
        assert extract("analyze options for some company") == "SPY"

    def test_multiple_dollar_tickers_returns_first(self, extract):
        # re.search returns the first match
        result = extract("Compare $AAPL vs $MSFT")
        assert result == "AAPL"
