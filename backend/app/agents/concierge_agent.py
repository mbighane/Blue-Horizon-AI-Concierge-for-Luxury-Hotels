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
from pydantic_ai.models.openai import OpenAIModel
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
    model = OpenAIModel(
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
            "   Required fields: customer_id (integer), room_type, check_in (YYYY-MM-DD), "
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
            "- 'Book a Deluxe room for customer 42' -> book_room\n"
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
                "FAQ search is currently unavailable (Ollama / Redis not running). "
                "I can still help with booking data queries and room reservations."
            )
        try:
            results = ctx.deps.search.search(question, top_k=top_k)
        except Exception as e:
            if "not loaded" in str(e).lower() or "load_index" in str(e).lower():
                try:
                    ctx.deps.search.load_index()
                    results = ctx.deps.search.search(question, top_k=top_k)
                except Exception as e2:
                    return f"FAQ search unavailable: {e2}"
            else:
                return f"FAQ search failed: {e}"

        if not results:
            return "No relevant FAQ entries found."

        lines = []
        for r in results:
            lines.append(
                f"Q: {r.get('question', 'N/A')}\n"
                f"A: {r.get('answer', 'No answer available')}\n"
                f"Category: {r.get('category', 'general')}  "
                f"Relevance: {r.get('relevance', '?')} ({r.get('score', 0):.2f})"
            )
        return "\n\n---\n\n".join(lines)

    # ── Tool 3: book a room ────────────────────────────────────────────────────
    @agent.tool
    async def book_room(
        ctx: RunContext[ConciergeDeps],
        customer_id: int,
        room_type: str,
        check_in: str,
        check_out: str,
        num_adults: int = 1,
        num_children: int = 0,
        payment_method: str = "Credit Card",
        special_requests: str = "",
    ) -> str:
        """
        Book a hotel room for a guest and persist the reservation in NeonDB.
        Writes to room_bookings (new row, status='Confirmed') and updates
        room_availability (status='Booked') for every occupied night.

        Args:
            customer_id:      Guest's integer customer_id from the customers table.
            room_type:        Desired room type, e.g. 'Deluxe', 'Suite', 'Standard'.
            check_in:         Check-in date  (YYYY-MM-DD).
            check_out:        Check-out date (YYYY-MM-DD).
            num_adults:       Number of adults (default 1).
            num_children:     Number of children (default 0).
            payment_method:   Payment method (default 'Credit Card').
            special_requests: Any special requests from the guest.
        """
        from datetime import date as _date

        svc = ctx.deps.booking

        # 1. Validate customer
        customer = svc.get_customer(customer_id)
        if not customer:
            return (
                f"No customer found with ID {customer_id}. "
                "Please verify the customer ID and try again."
            )

        # 2. Find an available room
        room = svc.find_available_room(
            room_type=room_type,
            check_in=check_in,
            check_out=check_out,
            num_adults=num_adults,
        )
        if not room:
            available_types = svc.list_room_types()
            return (
                f"Sorry, no '{room_type}' rooms are available from {check_in} to {check_out} "
                f"for {num_adults} adult(s). "
                f"Available room types: {', '.join(available_types)}."
            )

        # 3. Calculate total (base_rate × nights)
        nights       = (_date.fromisoformat(check_out) - _date.fromisoformat(check_in)).days
        total_amount = round(float(room["base_rate"]) * nights, 2)

        # 4. Persist the booking
        try:
            confirm = svc.create_booking(
                customer_id=customer_id,
                room_id=room["room_id"],
                room_number=int(room["room_number"]),
                room_type=room["type"],
                check_in=check_in,
                check_out=check_out,
                num_adults=num_adults,
                num_children=num_children,
                total_amount=total_amount,
                payment_method=payment_method,
                special_requests=special_requests,
                loyalty_tier=customer.get("loyalty_tier", "Standard"),
            )
        except Exception as exc:
            return f"Booking failed: {exc}"

        return (
            f"Booking confirmed!\n\n"
            f"  Booking ID   : {confirm['booking_id']}\n"
            f"  Guest        : {customer['first_name']} {customer['last_name']}\n"
            f"  Room         : {confirm['room_type']} — Room {confirm['room_number']}"
            f" ({room.get('bed_type', '')}, {room.get('view_type', '')})\n"
            f"  Check-in     : {confirm['check_in']}\n"
            f"  Check-out    : {confirm['check_out']}\n"
            f"  Nights       : {confirm['duration_days']}\n"
            f"  Total amount : ${confirm['total_amount']:,.2f}\n"
            f"  Payment      : {payment_method}\n"
            f"  Loyalty pts  : {confirm['points_earned']} points earned\n"
            f"  Status       : {confirm['booking_status']}"
        )

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

    result = await agent.run(
        user_message,
        deps=deps,
        message_history=history if history else None,
    )

    # Persist only the NEW messages from this turn so history grows incrementally
    _session_store[user_id] = list(history) + list(result.new_messages())

    return result.output
