"""
Test script for NL2SQL service (OpenAI-only).

Run directly:
    python scripts/test_nl2sql.py

Run via pytest:
    pytest scripts/test_nl2sql.py -v
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.services.nl2sql_service import NL2SQLService

# ---------------------------------------------------------------------------
# Test question categories
# ---------------------------------------------------------------------------
BOOKING_QUESTIONS = [
    "How many bookings were made in January 2026?",
    "What is the total revenue by room type this year?",
    "Show me all confirmed bookings with check-in after March 1, 2026.",
    "What is the most popular payment method?",
]

AVAILABILITY_QUESTIONS = [
    "What rooms are available from 2026-03-10 to 2026-03-14?",
    "Are there any Suite rooms available next week (2026-02-23 to 2026-03-01)?",
    "How many rooms are currently available today?",
]

GUEST_QUESTIONS = [
    "Which guests have made the most bookings?",
    "How many Platinum loyalty tier customers do we have?",
    "List the top 5 customers by total amount spent.",
]

ROOM_QUESTIONS = [
    "What are the most expensive rooms?",
    "Show me all rooms with ocean view.",
    "What is the average nightly rate by room type?",
]

ALL_QUESTIONS = (
    BOOKING_QUESTIONS
    + AVAILABILITY_QUESTIONS
    + GUEST_QUESTIONS
    + ROOM_QUESTIONS
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_question(agent: NL2SQLService, question: str, verbose: bool = True) -> dict:
    """Run a single question and return the result dict."""
    result = agent.query(question)

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Q: {question}")
        print(f"  SQL: {result['sql_query']}")
        if result["success"]:
            print(f"  Rows: {result['row_count']}   Columns: {result.get('columns', [])}")
            for i, row in enumerate(result["rows"][:3], 1):
                print(f"    [{i}] {row}")
            explanation = agent.explain_results(question, result)
            print(f"  Explanation: {explanation}")
        else:
            print(f"  ERROR: {result.get('error')}")

    return result


def run_category(agent: NL2SQLService, label: str, questions: list[str]) -> tuple[int, int]:
    """Run a category of questions. Returns (passed, total)."""
    print(f"\n{'#'*60}")
    print(f"  {label}")
    print(f"{'#'*60}")
    passed = 0
    for q in questions:
        try:
            r = run_question(agent, q)
            if r["success"]:
                passed += 1
            else:
                print(f"  [FAIL] {r.get('error')}")
        except Exception as exc:
            print(f"  [EXCEPTION] {exc}")
            traceback.print_exc()
    return passed, len(questions)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  Blue Horizon — NL2SQL Service Test  (OpenAI gpt-4o-mini)")
    print("=" * 60)

    print("\nInitializing NL2SQL Service...")
    agent = NL2SQLService(model="gpt-4o-mini")

    categories = [
        ("BOOKING QUERIES",      BOOKING_QUESTIONS),
        ("AVAILABILITY QUERIES", AVAILABILITY_QUESTIONS),
        ("GUEST QUERIES",        GUEST_QUESTIONS),
        ("ROOM QUERIES",         ROOM_QUESTIONS),
    ]

    total_passed = total_questions = 0
    for label, questions in categories:
        p, t = run_category(agent, label, questions)
        total_passed    += p
        total_questions += t

    print(f"\n{'='*60}")
    print(f"  RESULT: {total_passed}/{total_questions} queries succeeded")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Pytest integration — one test per category
# ---------------------------------------------------------------------------

_agent: NL2SQLService | None = None


def _get_agent() -> NL2SQLService:
    global _agent
    if _agent is None:
        _agent = NL2SQLService(model="gpt-4o-mini")
    return _agent


def test_booking_queries():
    agent = _get_agent()
    for q in BOOKING_QUESTIONS:
        r = agent.query(q)
        assert r["success"], f"Query failed: {q!r}  Error: {r.get('error')}"


def test_availability_queries():
    agent = _get_agent()
    for q in AVAILABILITY_QUESTIONS:
        r = agent.query(q)
        assert r["success"], f"Query failed: {q!r}  Error: {r.get('error')}"


def test_guest_queries():
    agent = _get_agent()
    for q in GUEST_QUESTIONS:
        r = agent.query(q)
        assert r["success"], f"Query failed: {q!r}  Error: {r.get('error')}"


def test_room_queries():
    agent = _get_agent()
    for q in ROOM_QUESTIONS:
        r = agent.query(q)
        assert r["success"], f"Query failed: {q!r}  Error: {r.get('error')}"


def test_explain_results():
    agent = _get_agent()
    q = "How many bookings were made in January 2026?"
    r = agent.query(q)
    if r["success"]:
        explanation = agent.explain_results(q, r)
        assert isinstance(explanation, str) and len(explanation) > 0


if __name__ == "__main__":
    main()