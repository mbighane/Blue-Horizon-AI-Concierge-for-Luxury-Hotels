"""
Room Booking Agent Service - Blue Horizon Hotel
Combines an OpenAI agent layer with direct NeonDB writes.

Agent capabilities:
  parse_booking_request() - extract structured booking params from natural language
  format_confirmation()   - generate a warm, personalised confirmation message
  suggest_alternatives()  - recommend alternatives when a room type is unavailable
  book()                  - end-to-end pipeline: parse -> find room -> write -> confirm

DB tables touched:
  - room_bookings     : INSERT new confirmed booking row
  - room_availability : UPDATE status -> 'Booked' for each occupied night
"""
from __future__ import annotations
import secrets
import json
import uuid
import sys
from pathlib import Path
from datetime import date, timedelta
from typing import Any, Dict, Optional

from openai import OpenAI
from sqlalchemy import create_engine, text

try:
    from backend.app.config import get_settings
except ImportError:
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from backend.app.config import get_settings


# ---------------------------------------------------------------------------
# Agent system prompts
# ---------------------------------------------------------------------------
_PARSE_SYSTEM_PROMPT = """You are a booking assistant for Blue Horizon, a luxury hotel.
Extract booking intent from a guest's natural language request and return a JSON object.

JSON schema (all fields required unless marked optional):
{
    "first_name":        <string | null>,
    "last_name":         <string | null>,
  "room_type":         <"Standard" | "Deluxe" | "Suite" | "Presidential" | null>,
  "check_in":          <"YYYY-MM-DD" | null>,
  "check_out":         <"YYYY-MM-DD" | null>,
  "num_adults":        <integer, default 1>,
  "num_children":      <integer, default 0>,
  "payment_method":    <"Credit Card" | "Cash" | "Bank Transfer", default "Credit Card">,
  "special_requests":  <string, default "">,
  "missing_fields":    [list of field names that are required but not provided]
}

Rules:
- Today's date for relative expressions is {today}.
- Normalise room type to the exact values above (e.g. 'deluxe' -> 'Deluxe').
- If check_out is missing but duration is given (e.g. '3 nights'), calculate it.
- first_name and last_name are required.
- List every required field that cannot be determined in missing_fields.
- Return ONLY the raw JSON — no markdown, no explanation."""

_CONFIRM_SYSTEM_PROMPT = """You are a warm, professional concierge at Blue Horizon luxury hotel.
Write a friendly booking confirmation message for the guest.
Include: guest name, room type, room number, view type, bed type, dates, number of nights,
total amount, loyalty points earned, and any special requests.
Keep it to 5-8 lines. Be welcoming and enthusiastic.
Format currency as $X,XXX.XX."""

_SUGGEST_SYSTEM_PROMPT = """You are a helpful concierge at Blue Horizon luxury hotel.
The guest's requested room type is unavailable for their dates.
Based on what IS available, suggest the best alternative(s) in a warm, helpful tone.
Mention specific benefits of each alternative (view, bed type, rate).
Keep it to 3-5 lines."""

_READ_SQL_SYSTEM_PROMPT = """You are a PostgreSQL expert for the Blue Horizon hotel database.
Given a plain-English description and embedded parameter values, generate
a single SELECT SQL statement that satisfies the request.

Table schemas:
  rooms (
      room_id        VARCHAR PRIMARY KEY,
      room_number    INTEGER,
      type           VARCHAR,          -- 'Standard'|'Deluxe'|'Suite'|'Presidential'
      base_rate      NUMERIC(10,2),
      bed_type       VARCHAR,
      view_type      VARCHAR,
      max_occupancy  INTEGER,
      floor          INTEGER,
      status         VARCHAR           -- 'Available'|'Out of Service'|'Maintenance'
  )

  customers (
      customer_id    INTEGER PRIMARY KEY,
      first_name     VARCHAR,
      last_name      VARCHAR,
      email          VARCHAR,
      loyalty_tier   VARCHAR
  )

  room_bookings (
      booking_id      VARCHAR PRIMARY KEY,
      customer_id     INTEGER,
      room_id         VARCHAR,
      room_number     INTEGER,
      room_type       VARCHAR,
      check_in        DATE,
      check_out       DATE,
      booking_status  VARCHAR           -- 'Confirmed'|'Cancelled'|'No Show'|'Checked In'|'Checked Out'
  )

Rules:
- Embed ALL parameter values directly into the SQL (no placeholders such as %s or :param).
- Escape string values in single quotes; use DATE 'YYYY-MM-DD' for date literals.
- Return ONLY the raw SQL — no markdown fences, no explanation.
- End the statement with a semicolon."""

_BOOKING_SQL_SYSTEM_PROMPT = """You are a PostgreSQL expert for the Blue Horizon hotel database.
Given a JSON object of booking parameters, generate the two SQL statements required
to record a confirmed booking atomically.

Table schemas:
  room_bookings (
      booking_id       VARCHAR PRIMARY KEY,   -- e.g. 'BK-A1B2C3D4'
      customer_id      INTEGER  NOT NULL,
      room_id          VARCHAR,               -- FK -> rooms.room_id
      room_number      INTEGER,
      room_type        VARCHAR,               -- 'Standard'|'Deluxe'|'Suite'|'Presidential'
      check_in         DATE     NOT NULL,
      check_out        DATE     NOT NULL,
      duration_days    INTEGER,
      num_adults       INTEGER  DEFAULT 1,
      num_children     INTEGER  DEFAULT 0,
      loyalty_tier     VARCHAR  DEFAULT 'Standard',
      special_requests TEXT     DEFAULT '',
      booking_status   VARCHAR  DEFAULT 'Confirmed',
      payment_method   VARCHAR  DEFAULT 'Credit Card',
      total_amount     NUMERIC(10,2),
      points_earned    INTEGER  DEFAULT 0
  )

  room_availability (
      room_id   VARCHAR NOT NULL,
      date      DATE    NOT NULL,
      status    VARCHAR NOT NULL   -- 'Available'|'Booked'|'Maintenance'
  )

Rules:
- Embed ALL values directly into the SQL (no placeholders such as %s or :param).
- Escape strings in single quotes; use DATE 'YYYY-MM-DD' for date literals.
- booking_status must always be 'Confirmed'.
- For availability_sql: update every night in the range using
    date >= DATE 'YYYY-MM-DD' AND date < DATE 'YYYY-MM-DD'
  (inclusive check_in, exclusive check_out).
- Return ONLY a raw JSON object with exactly two keys:
    "insert_sql"       -- INSERT INTO room_bookings ...
    "availability_sql" -- UPDATE room_availability SET status = 'Booked' WHERE ...
- No markdown fences, no explanation — raw JSON only."""


class BookingService:
    """
    Booking agent for Blue Horizon hotel.

    Agent layer (OpenAI):
        parse_booking_request()  - NL -> structured booking params
        format_confirmation()    - booking dict -> warm confirmation message
        suggest_alternatives()   - unavailability -> alternative suggestions
        book()                   - end-to-end NL booking pipeline

    DB layer (SQLAlchemy / NeonDB):
        get_customer()           - lookup customer by ID
        list_room_types()        - available room types
        find_available_room()    - cheapest available room for date range
        create_booking()         - atomically write booking + update availability
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        settings     = get_settings()
        self.model   = model
        self.client  = OpenAI(api_key=settings.openai_api_key)
        self.engine  = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
            connect_args={
                "connect_timeout": 50,
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            },
        )
        print(f"[OK] BookingService initialized  model={self.model}")

    # ──────────────────────────────────────────────────────────────────────────
    # Read helpers
    # ──────────────────────────────────────────────────────────────────────────

    def list_room_types(self) -> list[str]:
        """
        Ask OpenAI to generate the SELECT SQL, then execute it to return
        all distinct room types that are not out-of-service.
        """
        sql = self._generate_read_sql(
            "Return all distinct values of the 'type' column from the rooms table, "
            "excluding any rooms whose status is 'Out of Service', ordered alphabetically."
        )
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        return [r[0] for r in rows if r[0]]

    def get_customer(self, customer_id: int) -> Optional[dict]:
        """
        Ask OpenAI to generate the SELECT SQL, then execute it to fetch
        basic customer info for the given customer_id.
        """
        sql = self._generate_read_sql(
            f"Fetch customer_id, first_name, last_name, email and loyalty_tier "
            f"from the customers table where customer_id = {customer_id}."
        )
        with self.engine.connect() as conn:
            row = conn.execute(text(sql)).fetchone()
        return dict(row._mapping) if row else None

    def create_customer(
        self,
        first_name: str,
        last_name: str,
        loyalty_tier: str = "Standard",
    ) -> dict:
        """
        Create a lightweight guest customer record and return it.

        This is used by booking flow to create a guest profile automatically.
        """
        first_name = (first_name or "Guest").strip()
        last_name = (last_name or uuid.uuid4().hex[:8].upper()).strip()
        sql = text(
            """
            INSERT INTO customers ( first_name, last_name, email, loyalty_tier)
            VALUES ( :first_name, :last_name, :email, :loyalty_tier)
            RETURNING customer_id, first_name, last_name, email, loyalty_tier
            """
        )

        for _ in range(20):
            suffix = uuid.uuid4().hex[:8]
            email = f"guest.{suffix}@bluehorizon.local"
            customer_id = secrets.randbelow(49999) + 50001
            try:
                with self.engine.begin() as conn:
                    row = conn.execute(
                        sql,
                        {
                            "customer_id": customer_id,
                            "first_name": first_name,
                            "last_name": last_name,
                            "email": email,
                            "loyalty_tier": loyalty_tier,
                        },
                    ).fetchone()
                if row:
                    customer = dict(row._mapping)
                    print(f"[BookingService] Created customer_id={customer.get('customer_id')}")
                    return customer
            except Exception as exc:
                message = str(exc).lower()
                if "duplicate" in message or "unique" in message:
                    continue
                raise

        raise RuntimeError("Could not create a new customer record after retries.")

    def find_available_room(
        self,
        room_type: str,
        check_in: str,
        check_out: str,
        num_adults: int = 1,
    ) -> Optional[dict]:
        """
        Ask OpenAI to generate the availability SELECT SQL, then execute it
        to return the cheapest available room matching *room_type* for the
        requested date range, or None if nothing is free.

        A room is considered unavailable if it has any non-cancelled booking
        that overlaps the requested window.
        """
        sql = self._generate_read_sql(
            f"Find the single cheapest available room whose type matches '{room_type}' "
            f"(case-insensitive, partial match) for the date range "
            f"check_in = DATE '{check_in}' to check_out = DATE '{check_out}', "
            f"supporting at least {num_adults} adult(s) (max_occupancy >= {num_adults}), "
            f"excluding rooms with status 'Out of Service', "
            f"and excluding rooms that already have a non-cancelled, non-no-show booking "
            f"whose check_in < DATE '{check_out}' AND check_out > DATE '{check_in}'. "
            f"Return columns: room_id, room_number, type, base_rate, bed_type, view_type, "
            f"max_occupancy, floor. Order by base_rate ascending. Limit 1."
        )
        with self.engine.connect() as conn:
            row = conn.execute(text(sql)).fetchone()
        return dict(row._mapping) if row else None

    # ──────────────────────────────────────────────────────────────────────────
    # Write
    # ──────────────────────────────────────────────────────────────────────────

    # ──────────────────────────────────────────────────────────────────────────
    # SQL generation (OpenAI)
    # ──────────────────────────────────────────────────────────────────────────

    def _generate_read_sql(self, query_description: str) -> str:
        """
        Ask OpenAI to write a SELECT SQL statement from a plain-English description.

        Args:
            query_description: Natural language description with all parameter
                               values already embedded as literals.

        Returns:
            A ready-to-execute SQL SELECT string.
        """
        print(f"[BookingService] Generating SELECT SQL: {query_description[:80]} …")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _READ_SQL_SYSTEM_PROMPT},
                {"role": "user",   "content": query_description},
            ],
            temperature=0.0,
            max_tokens=400,
        )
        sql = response.choices[0].message.content.strip()
        # Strip markdown fences if the model added them
        if sql.startswith("```"):
            lines = sql.splitlines()
            sql = "\n".join(lines[1:]).rstrip("`").strip()
        print(f"  sql: {sql[:100]} …")
        return sql

    def _generate_booking_sql(self, params: Dict[str, Any]) -> Dict[str, str]:
        """
        Ask OpenAI to generate the INSERT and UPDATE SQL for a booking.

        Args:
            params: Dict with all booking field values (must be serialisable).

        Returns:
            Dict with keys ``insert_sql`` and ``availability_sql``.
        """
        user_prompt = "Booking parameters:\n" + json.dumps(params, indent=2, default=str)
        print(f"[BookingService] Generating SQL via OpenAI for booking {params.get('booking_id')} …")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _BOOKING_SQL_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        sql_dict = json.loads(response.choices[0].message.content.strip())
        print(f"  insert_sql       : {sql_dict.get('insert_sql', '')[:80]} …")
        print(f"  availability_sql : {sql_dict.get('availability_sql', '')[:80]} …")
        return sql_dict

    def create_booking(
        self,
        customer_id: int,
        room_id: str,
        room_number: int,
        room_type: str,
        check_in: str,
        check_out: str,
        num_adults: int,
        num_children: int,
        total_amount: float,
        payment_method: str = "Credit Card",
        special_requests: str = "",
        loyalty_tier: str = "Standard",
    ) -> dict:
        """
        Atomically:
          1. Ask OpenAI to generate the INSERT (room_bookings) and
             UPDATE (room_availability) SQL from the booking parameters.
          2. Execute both statements inside a single transaction.

        Returns a confirmation dict with the generated booking_id.
        """
        check_in_date  = date.fromisoformat(check_in)
        check_out_date = date.fromisoformat(check_out)
        duration_days  = (check_out_date - check_in_date).days

        if duration_days <= 0:
            raise ValueError("check_out must be after check_in")

        booking_id    = f"BK-{uuid.uuid4().hex[:8].upper()}"
        points_earned = max(1, int(total_amount * 10))  # 10 pts per $ spent

        # ── Ask OpenAI to write the SQL ────────────────────────────────────
        sql_params = {
            "booking_id":       booking_id,
            "customer_id":      customer_id,
            "room_id":          room_id,
            "room_number":      room_number,
            "room_type":        room_type,
            "check_in":         check_in,
            "check_out":        check_out,
            "duration_days":    duration_days,
            "num_adults":       num_adults,
            "num_children":     num_children,
            "loyalty_tier":     loyalty_tier,
            "special_requests": special_requests,
            "booking_status":   "Confirmed",
            "payment_method":   payment_method,
            "total_amount":     total_amount,
            "points_earned":    points_earned,
        }
        sql_dict = self._generate_booking_sql(sql_params)

        insert_sql       = sql_dict.get("insert_sql", "")
        availability_sql = sql_dict.get("availability_sql", "")

        if not insert_sql or not availability_sql:
            raise RuntimeError(
                f"OpenAI did not return both SQL statements. Got: {sql_dict}"
            )

        # ── Execute in a single atomic transaction ─────────────────────────
        with self.engine.begin() as conn:
            conn.execute(text(insert_sql))
            conn.execute(text(availability_sql))

        return {
            "booking_id":     booking_id,
            "room_number":    room_number,
            "room_type":      room_type,
            "check_in":       check_in,
            "check_out":      check_out,
            "duration_days":  duration_days,
            "total_amount":   total_amount,
            "points_earned":  points_earned,
            "booking_status": "Confirmed",
        }

    # -------------------------------------------------------------------------
    # Agent methods (OpenAI)
    # -------------------------------------------------------------------------

    def parse_booking_request(self, natural_request: str) -> Dict[str, Any]:
        """
        Extract structured booking parameters from a natural language request.

        Args:
            natural_request: e.g. 'Book a Deluxe room for 2 adults from March 10
                             to March 14 for Anaya Sharma, ocean view preferred.'

        Returns:
            Dict with keys: first_name, last_name, room_type, check_in, check_out,
            num_adults, num_children, payment_method, special_requests,
            missing_fields (list of required fields not found).
        """
        system = _PARSE_SYSTEM_PROMPT.replace("{today}", date.today().isoformat())
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": natural_request},
                ],
                temperature=0.0,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            parsed = json.loads(raw)
            # Ensure missing_fields is always present
            parsed.setdefault("missing_fields", [])
            return parsed
        except Exception as exc:
            print(f"[BookingService] parse_booking_request error: {exc}")
            return {
                "first_name": None,
                "last_name": None,
                "room_type": None,
                "check_in": None,    "check_out": None,
                "num_adults": 1,     "num_children": 0,
                "payment_method": "Credit Card", "special_requests": "",
                "missing_fields": ["first_name", "last_name", "room_type", "check_in", "check_out"],
                "parse_error": str(exc),
            }

    def format_confirmation(
        self,
        confirmation: Dict[str, Any],
        customer: Dict[str, Any],
        room: Dict[str, Any],
    ) -> str:
        """
        Generate a warm, personalised booking confirmation message via OpenAI.

        Args:
            confirmation : Dict returned by create_booking().
            customer     : Dict returned by create_customer().
            room         : Dict returned by find_available_room().

        Returns:
            Friendly multi-line confirmation string.
        """
        user_prompt = (
            f"Guest: {customer.get('first_name', '')} {customer.get('last_name', '')}  "
            f"(loyalty tier: {customer.get('loyalty_tier', 'Standard')})\n"
            f"Booking ID  : {confirmation['booking_id']}\n"
            f"Room        : {confirmation['room_type']} - Room {confirmation['room_number']}  "
            f"({room.get('bed_type', '')}, {room.get('view_type', '')} view)\n"
            f"Check-in    : {confirmation['check_in']}\n"
            f"Check-out   : {confirmation['check_out']}\n"
            f"Nights      : {confirmation['duration_days']}\n"
            f"Total       : ${confirmation['total_amount']:,.2f}\n"
            f"Points earned: {confirmation['points_earned']}\n"
            f"Status      : {confirmation['booking_status']}\n"
            f"Special requests: {confirmation.get('special_requests', 'None')}"
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _CONFIRM_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
                max_tokens=300,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            print(f"[BookingService] format_confirmation error: {exc}")
            return (
                f"Booking confirmed! ID: {confirmation['booking_id']}\n"
                f"Room {confirmation['room_number']} ({confirmation['room_type']}) "
                f"{confirmation['check_in']} - {confirmation['check_out']}\n"
                f"Total: ${confirmation['total_amount']:,.2f}  "
                f"Points earned: {confirmation['points_earned']}"
            )

    def suggest_alternatives(
        self,
        original_request: str,
        unavailable_type: str,
        check_in: str,
        check_out: str,
        num_adults: int = 1,
    ) -> str:
        """
        When the requested room type is unavailable, find what IS available
        and ask OpenAI to suggest the best alternatives in a friendly way.
        """
        room_types = self.list_room_types()
        alternatives = []
        for rt in room_types:
            if rt.lower() == unavailable_type.lower():
                continue
            room = self.find_available_room(rt, check_in, check_out, num_adults)
            if room:
                alternatives.append(
                    f"- {rt}: Room {room['room_number']}, "
                    f"{room.get('bed_type', '')} bed, "
                    f"{room.get('view_type', '')} view, "
                    f"${room['base_rate']}/night"
                )

        if not alternatives:
            return (
                f"I'm sorry, we have no rooms available from {check_in} to {check_out} "
                "for your party. Please try different dates or contact the front desk."
            )

        user_prompt = (
            f"Guest request: {original_request}\n"
            f"Unavailable room type: {unavailable_type}\n"
            f"Available alternatives:\n" + "\n".join(alternatives)
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SUGGEST_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            print(f"[BookingService] suggest_alternatives error: {exc}")
            return "Available options:\n" + "\n".join(alternatives)

    def book(self, natural_request: str) -> Dict[str, Any]:
        """
        End-to-end booking pipeline from natural language.

        Steps:
          1. parse_booking_request()   - extract params via OpenAI
          2. Validate required fields  - return error if missing
          3. create_customer()         - auto-create customer profile
          4. find_available_room()     - find cheapest matching room
          5. create_booking()          - write to NeonDB atomically
          6. format_confirmation()     - generate friendly message via OpenAI
        """
        params = self.parse_booking_request(natural_request)

        missing = list(params.get("missing_fields", []))
        required = [
            f for f in ["first_name", "last_name", "room_type", "check_in", "check_out"]
            if not params.get(f)
        ]
        missing = missing or required
        if missing:
            return {
                "success": False,
                "message": (
                    f"To complete your booking I need the following information: "
                    f"{', '.join(missing)}. Please provide these details."
                ),
                "booking": None,
                "params": params,
            }

        first_name = str(params.get("first_name") or "").strip()
        last_name = str(params.get("last_name") or "").strip()
        room_type = params["room_type"]
        check_in = params["check_in"]
        check_out = params["check_out"]

        try:
            num_adults = int(params.get("num_adults") or 1)
        except (TypeError, ValueError):
            num_adults = 1
        num_adults = max(1, num_adults)

        try:
            num_children = int(params.get("num_children") or 0)
        except (TypeError, ValueError):
            num_children = 0
        num_children = max(0, num_children)

        try:
            customer = self.create_customer(first_name=first_name, last_name=last_name)
        except Exception as exc:
            return {
                "success": False,
                "message": f"Unable to create a customer profile automatically: {exc}",
                "booking": None,
                "params": params,
            }

        customer_id_value = customer.get("customer_id") if customer else None
        if customer_id_value in (None, ""):
            return {
                "success": False,
                "message": "Unable to resolve a valid customer ID for booking.",
                "booking": None,
                "params": params,
            }
        customer_id = int(customer_id_value)

        room = self.find_available_room(room_type, check_in, check_out, num_adults)
        if not room:
            suggestion = self.suggest_alternatives(
                natural_request, room_type, check_in, check_out, num_adults
            )
            return {
                "success": False,
                "message": f"No '{room_type}' rooms available from {check_in} to {check_out}.\n\n{suggestion}",
                "booking": None,
                "params": params,
            }

        nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
        total_amount = round(float(room["base_rate"]) * nights, 2)
        room_number_value = room.get("room_number")
        if room_number_value in (None, ""):
            return {
                "success": False,
                "message": "Selected room has no valid room_number.",
                "booking": None,
                "params": params,
            }

        try:
            confirmation = self.create_booking(
                customer_id=customer_id,
                room_id=room["room_id"],
                room_number=int(room_number_value),
                room_type=room["type"],
                check_in=check_in,
                check_out=check_out,
                num_adults=num_adults,
                num_children=num_children,
                total_amount=total_amount,
                payment_method=params.get("payment_method", "Credit Card"),
                special_requests=params.get("special_requests", ""),
                loyalty_tier=customer.get("loyalty_tier", "Standard"),
            )
        except Exception as exc:
            return {
                "success": False,
                "message": f"Booking write failed: {exc}",
                "booking": None,
                "params": params,
            }

        message = self.format_confirmation(confirmation, customer, room)
        return {
            "success": True,
            "message": message,
            "booking": confirmation,
            "params": params,
        }
