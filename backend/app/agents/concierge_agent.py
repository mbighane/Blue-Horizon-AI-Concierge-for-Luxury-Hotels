"""
Blue Horizon Concierge Agent using PydanticAI.

A true orchestration agent that picks the right tool based on the user's question:
  - run_sql_query  : booking/guest/room data questions
  - search_faq     : policy/amenity/info questions
  - book_room      : room reservation — writes to NeonDB (room_bookings + room_availability)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from backend.app.services.nl2sql_service import NL2SQLService
from backend.app.services.search_service import HotelFAQSearchService, get_search_service
from backend.app.services.booking_service import BookingService
from backend.app.config import get_settings


# ─────────────────────────────────────────────
# Dependency container injected into every tool
# ─────────────────────────────────────────────
@dataclass
class ConciergeDeps:
    nl2sql: NL2SQLService
    search: Optional[HotelFAQSearchService]   # None when Ollama/Redis unavailable
    booking: BookingService


# ─────────────────────────────────────────────
# Build the PydanticAI agent
# ─────────────────────────────────────────────
def _build_agent() -> Agent[ConciergeDeps, str]:
    settings = get_settings()
    model = OpenAIChatModel(
        settings.openai_model,
        provider=OpenAIProvider(api_key=settings.openai_api_key),
    )

    agent: Agent[ConciergeDeps, str] = Agent(
        model,
        deps_type=ConciergeDeps,
        output_type=str,
        system_prompt=(
            "You are Blue Horizon, an AI concierge for a luxury hotel. "
            "Answer guest questions helpfully and accurately.\n\n"
            "TOOL SELECTION — follow these rules strictly:\n"
            "1. Use 'run_sql_query' ONLY for questions that need LIVE DATABASE DATA: "
            "   specific booking records, guest counts, revenue figures, occupancy stats, "
            "   check-in/check-out dates for specific guests, or any question asking "
            "   'how many', 'which guests', 'show me bookings', 'total revenue', etc.\n"
            "2. Use 'search_faq' for ALL informational questions about the hotel: "
            "   policies (cancellation, pets, smoking), amenities (pool, spa, gym, restaurant), "
            "   services (room service, concierge, parking), prices/rates, check-in times, "
            "   what is included, how something works, or anything a guest would find in a brochure.\n"
            "3. Use 'book_room' when a guest explicitly wants to MAKE A NEW RESERVATION. "
            "   Required fields: first_name, last_name, room_type, check_in (YYYY-MM-DD), "
            "   check_out (YYYY-MM-DD), num_adults. "
            "   If any required field is missing, ask the guest before calling the tool.\n"
            "4. If the question is casual or conversational (greetings, opinions, general chat), "
            "   answer directly WITHOUT calling any tool.\n"
            "5. When in doubt between run_sql_query and search_faq, prefer search_faq.\n\n"
            "EXAMPLES:\n"
            "- 'What is the check-in time?' -> search_faq\n"
            "- 'Do you have a pool?' -> search_faq\n"
            "- 'What is your cancellation policy?' -> search_faq\n"
            "- 'How many bookings were made in January?' -> run_sql_query\n"
            "- 'Show guests checking in this week' -> run_sql_query\n"
            "- 'Book a Deluxe room for Anaya Sharma' -> book_room\n"
            "- 'Hello, how are you?' -> answer directly, no tool\n\n"
            "Always respond in clear, warm, professional language."
        ),
    )

    # ── Tool 1: run a SQL query ───────────────────────────────────────────────
    @agent.tool
    async def run_sql_query(ctx: RunContext[ConciergeDeps], question: str) -> str:
        """
        Use this tool ONLY when the guest asks for LIVE DATA from the hotel database:
        specific booking records, guest lists, revenue totals, occupancy counts,
        check-in/check-out schedules, or any question requiring a database query
        (e.g. 'how many bookings', 'show me guests', 'total revenue', 'which rooms are booked').
        Do NOT use this for general hotel information, policies, or amenities.
        """
        result = ctx.deps.nl2sql.query(question)
        if not result.get("success"):
            return f"Query failed: {result.get('error', 'Unknown error')}"
        explanation = ctx.deps.nl2sql.explain_results(question, result)
        rows = result.get("rows", [])
        sql  = result.get("sql_query", "")
        return (
            f"SQL: {sql}\n\n"
            f"Results ({result.get('row_count', 0)} rows): "
            f"{rows[:5]}\n\n"
            f"Summary: {explanation}"
        )

    # ── Tool 2: search FAQs ───────────────────────────────────────────────────
    @agent.tool
    async def search_faq(ctx: RunContext[ConciergeDeps], question: str, top_k: int = 10) -> str:
        """
        Use this tool for ANY question about hotel information, policies, or services:
        check-in/check-out times, cancellation policy, pet policy, breakfast, parking,
        pool, spa, gym, restaurant hours, room features, amenities, prices,
        or anything a guest would find in a hotel brochure or FAQ page.
        This is the DEFAULT tool for informational questions — prefer it over run_sql_query
        when the guest is asking 'what', 'do you have', 'is there', 'how does', 'what time'.
        """
        if ctx.deps.search is None:
            return (
                "FAQ search is currently unavailable (Redis not reachable or index not built). "
                "I can still help with booking data queries and room reservations."
            )

       
        try:
            settings = get_settings()
            faq_dir = settings.faq_data_dir
            index_name = HotelFAQSearchService.INDEX_NAME
            ctx.deps.search.create_index(
                        data_dir=faq_dir,
                        index_name=index_name,
                 )
            results = ctx.deps.search.search(question, top_k=top_k)
        except Exception as e:
            return f"FAQ search failed: {e}"

        if not results:
            return "No relevant FAQ entries found."

        # Synthesise a fluent answer from the top results via OpenAI
        answer = ctx.deps.search.explain_results(question, results)
        return answer

    # ── Tool 3: book a room ────────────────────────────────────────────────────
    @agent.tool
    async def book_room(
        ctx: RunContext[ConciergeDeps],
        first_name: str,
        last_name: str,
        room_type: str,
        check_in: str,
        check_out: str,
        num_adults: int = 1,
        num_children: int = 0,
        customer_id: int | None = None,
        payment_method: str = "Credit Card",
        special_requests: str = "",
    ) -> str:
        """
        Book a hotel room for a guest and persist the reservation in NeonDB.
        Writes to room_bookings (new row, status='Confirmed') and updates
        room_availability (status='Booked') for every occupied night.

        Args:
            first_name:       Guest first name.
            last_name:        Guest last name.
            room_type:        Desired room type, e.g. 'Deluxe', 'Suite', 'Standard'.
            check_in:         Check-in date  (YYYY-MM-DD).
            check_out:        Check-out date (YYYY-MM-DD).
            num_adults:       Number of adults (default 1).
            num_children:     Number of children (default 0).
            customer_id:      Optional existing customer_id.
            payment_method:   Payment method (default 'Credit Card').
            special_requests: Any special requests from the guest.
        """
        # Build a natural language request and delegate to the booking agent pipeline.
        # This gives us: customer validation, availability check, DB write,
        # alternative suggestions, and an OpenAI-generated confirmation — all in one call.
        # customer_phrase = (
        #     f"customer name {first_name} {last_name}, " if customer_id is not None else ""
        # )
        natural = (
            f"Book a {room_type} room for {first_name} {last_name}, "
            # f"{customer_phrase}"
            f"{num_adults} adult(s) and {num_children} child(ren), "
            f"check-in {check_in}, check-out {check_out}, "
            f"payment method {payment_method}. "
            f"Special requests: {special_requests or 'none'}."
        )
        result = ctx.deps.booking.book(natural)
        return result["message"]

    return agent


# ─────────────────────────────────────────────
# Singleton agent + deps
# ─────────────────────────────────────────────
_agent: Agent[ConciergeDeps, str] | None = None
_deps:  ConciergeDeps | None = None

# Per-user conversation history:  user_id -> list[ModelMessage]
_session_store: dict[str, list] = {}


def get_concierge_agent() -> tuple[Agent[ConciergeDeps, str], ConciergeDeps]:
    """Return the singleton (agent, deps) pair, creating them on first call."""
    global _agent, _deps
    if _agent is None:
        # Search service requires Ollama + Redis — make it optional so the
        # agent still starts even when those services are not running.
        try:
            search_svc = get_search_service()
        except Exception as e:
            print(f"[WARN] FAQ search service unavailable (Ollama/Redis not running?): {e}")
            search_svc = None

        _deps  = ConciergeDeps(
            nl2sql=NL2SQLService(),
            search=search_svc,
            booking=BookingService(),
        )
        _agent = _build_agent()
    return _agent, _deps


def clear_session(user_id: str) -> None:
    """Wipe the conversation history for a given user."""
    _session_store.pop(user_id, None)


async def ask_concierge(user_message: str, user_id: str = "guest") -> str:
    """
    High-level helper used by the FastAPI endpoint.
    Maintains per-user conversation history so the agent remembers
    earlier turns in the same session.
    """
    agent, deps = get_concierge_agent()

    # Retrieve existing history for this user (empty list = fresh session)
    history = _session_store.get(user_id, [])

    #The actual OpenAI call that decides which tool to invoke is triggered
    result = await agent.run(
        user_message,
        deps=deps,
        message_history=history if history else None,
    )

    # Persist only the NEW messages from this turn so history grows incrementally
    _session_store[user_id] = list(history) + list(result.new_messages())

    return result.output
