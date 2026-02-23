import os
from types import SimpleNamespace

import pytest

from backend.app.agents import concierge_agent


class TrackingNL2SQLService:
    def __init__(self):
        self.call_count = 0
        self.last_question = ""

    def query(self, question: str):
        self.call_count += 1
        self.last_question = question
        return {
            "success": True,
            "sql_query": "SELECT 1 AS booking_count",
            "row_count": 1,
            "rows": [{"booking_count": 1}],
        }

    def explain_results(self, question: str, result: dict):
        return "SQL_TOOL_USED"


class TrackingFAQSearchService:
    def __init__(self):
        self.call_count = 0
        self.last_question = ""

    def search(self, question: str, top_k: int = 10):
        self.call_count += 1
        self.last_question = question
        return [{"text": "Check-in is at 3 PM.", "score": 0.99}]

    def explain_results(self, question: str, results: list):
        return "FAQ_TOOL_USED"


class TrackingBookingService:
    def __init__(self):
        self.call_count = 0
        self.last_request = ""

    def book(self, natural_request: str):
        self.call_count += 1
        self.last_request = natural_request
        return {"message": "BOOKING_TOOL_USED"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,expected_tool",
    [
        (
            "How many bookings were made in January 2026?",
            "sql",
        ),
        (
            "What is your cancellation policy for hotel reservations?",
            "faq",
        ),
        (
            "Please book a Deluxe room for Anaya Sharma from 2026-03-15 to 2026-03-18 for 2 adults.",
            "booking",
        ),
    ],
)
async def test_openai_routes_to_expected_tool(query, expected_tool, monkeypatch):
    """Validates routing behavior using real OpenAI calls and sample query types."""
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_api_key:
        pytest.skip("OPENAI_API_KEY is not set; skipping real OpenAI routing test")

    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    monkeypatch.setattr(
        concierge_agent,
        "get_settings",
        lambda: SimpleNamespace(openai_model=openai_model, openai_api_key=openai_api_key),
    )

    nl2sql = TrackingNL2SQLService()
    search = TrackingFAQSearchService()
    booking = TrackingBookingService()

    deps = concierge_agent.ConciergeDeps(
        nl2sql=nl2sql,
        search=search,
        booking=booking,
    )
    agent = concierge_agent._build_agent()

    result = await agent.run(query, deps=deps)

    call_counts = {
        "sql": nl2sql.call_count,
        "faq": search.call_count,
        "booking": booking.call_count,
    }

    assert call_counts[expected_tool] == 1, f"Expected {expected_tool} tool to be called exactly once"
    assert sum(call_counts.values()) == 1, f"Expected exactly one tool call, got: {call_counts}"
    assert isinstance(result.output, str) and result.output.strip()

    if expected_tool == "sql":
        assert "january" in nl2sql.last_question.lower()
    elif expected_tool == "faq":
        assert "cancellation" in search.last_question.lower()
    else:
        assert "Anaya Sharma" in booking.last_request
