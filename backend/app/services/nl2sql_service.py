"""
NL2SQL Service � Blue Horizon Hotel
Converts natural language questions into parameterized PostgreSQL SELECT
queries using OpenAI, then executes them against Neon DB.

Agent capabilities:
  - Booking queries    : reservations, revenue, guest counts, check-in/out
  - Availability logic : available rooms by date range and room type
  - Guest queries      : customer profiles, loyalty tiers, top guests
  - Room queries       : room types, rates, amenities, occupancy
"""
from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from openai import OpenAI

try:
    from backend.app.config import get_settings
except ImportError:
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from backend.app.config import get_settings


# -----------------------------------------------------------------------------
# Database schema reference injected into every system prompt
# -----------------------------------------------------------------------------
_DB_SCHEMA = """
== DATABASE SCHEMA (PostgreSQL / Neon DB) ==

TABLE: room_bookings
  booking_id        SERIAL PRIMARY KEY
  customer_id       INTEGER  FK -> customers.customer_id
  room_id           INTEGER  FK -> rooms.room_id
  room_number       INTEGER
  room_type         VARCHAR  ('Standard' | 'Deluxe' | 'Suite' | 'Presidential')
  check_in          DATE
  check_out         DATE
  num_adults        INTEGER
  num_children      INTEGER
  total_amount      NUMERIC(10,2)
  payment_method    VARCHAR  ('Credit Card' | 'Cash' | 'Bank Transfer')
  booking_status    VARCHAR  ('Confirmed' | 'Cancelled' | 'Completed' | 'No-Show')
  special_requests  TEXT
  loyalty_tier      VARCHAR  ('Standard' | 'Silver' | 'Gold' | 'Platinum')
  created_at        TIMESTAMP

TABLE: room_availability
  availability_id   SERIAL PRIMARY KEY
  room_id           INTEGER  FK -> rooms.room_id
  room_number       INTEGER
  room_type         VARCHAR
  date              DATE
  status            VARCHAR  ('Available' | 'Booked')
  booking_id        INTEGER  FK -> room_bookings.booking_id  (NULL when Available)

TABLE: customers
  customer_id       SERIAL PRIMARY KEY
  first_name        VARCHAR
  last_name         VARCHAR
  email             VARCHAR
  phone             VARCHAR
  loyalty_tier      VARCHAR  ('Standard' | 'Silver' | 'Gold' | 'Platinum')
  created_at        TIMESTAMP

TABLE: rooms
  room_id              SERIAL PRIMARY KEY
  room_number          INTEGER UNIQUE
  type                 VARCHAR  ('Standard' | 'Deluxe' | 'Suite' | 'Presidential')
  bed_type             VARCHAR  ('Single' | 'Double' | 'Queen' | 'King')
  view_type            VARCHAR  ('City' | 'Garden' | 'Ocean' | 'Pool')
  base_rate            NUMERIC(10,2)   -- nightly rate
  max_occupancy        INTEGER
  basic_amenities      TEXT    -- standard amenities included in all rooms
  additional_amenities TEXT    -- premium/extra amenities for higher-tier rooms

== KEY RELATIONSHIPS ==
  room_bookings.customer_id    -> customers.customer_id
  room_bookings.room_id        -> rooms.room_id
  room_availability.room_id    -> rooms.room_id
  room_availability.booking_id -> room_bookings.booking_id

== AVAILABILITY LOGIC ==
  A room is AVAILABLE for a date range [check_in, check_out) when every night
  in room_availability has status = 'Available'.
  To find available rooms use NOT EXISTS:
    SELECT DISTINCT r.*
    FROM rooms r
    WHERE NOT EXISTS (
        SELECT 1 FROM room_availability ra
        WHERE ra.room_id = r.room_id
          AND ra.date >= :check_in AND ra.date < :check_out
          AND ra.status = 'Booked'
    )
"""

# -----------------------------------------------------------------------------
# System prompt for SQL generation
# -----------------------------------------------------------------------------
_SQL_SYSTEM_PROMPT = f"""You are a PostgreSQL SQL expert for Blue Horizon, a luxury hotel.
Translate natural language questions into correct PostgreSQL SELECT queries.

{_DB_SCHEMA}

== SQL GENERATION RULES ==
1.  Return ONLY the raw SQL � no markdown, no code fences, no explanation.
2.  SELECT queries ONLY. Never generate INSERT / UPDATE / DELETE / DDL.
3.  PostgreSQL syntax: use DATE literals, ILIKE, EXTRACT, date_trunc where appropriate.
4.  Use ILIKE for case-insensitive text matching.
5.  Alias every computed expression (SUM(...) AS total_revenue, COUNT(*) AS booking_count).
6.  GROUP BY must include EVERY non-aggregate column in SELECT.
    Correct:   GROUP BY customers.customer_id, customers.first_name, customers.last_name
    Incorrect: GROUP BY customers.customer_id
7.  Never expose customer_id as a raw number. Always JOIN customers and return
    (customers.first_name || ' ' || customers.last_name) AS customer_name.
8.  Never combine DISTINCT ON with GROUP BY � use one or the other.
9.  Booking / reservation questions        -> query room_bookings
10. Availability / open rooms questions   -> use the NOT EXISTS pattern against room_availability
11. Revenue / financial questions         -> SUM(total_amount) FROM room_bookings WHERE booking_status != 'Cancelled'
12. Occupancy questions                   -> COUNT(*) FROM room_availability WHERE status = 'Booked'
13. "This month" / "January" etc.         -> EXTRACT(MONTH FROM ...) = N AND EXTRACT(YEAR FROM ...) = YYYY
14. Limit results to 100 rows unless the question asks for all.

== EXAMPLES ==
Q: How many bookings were made in January 2026?
A: SELECT COUNT(*) AS booking_count
   FROM room_bookings
   WHERE EXTRACT(YEAR FROM check_in) = 2026
     AND EXTRACT(MONTH FROM check_in) = 1;

Q: Which guests have made the most bookings?
A: SELECT customers.customer_id,
          customers.first_name,
          customers.last_name,
          COUNT(room_bookings.booking_id) AS booking_count
   FROM room_bookings
   JOIN customers ON customers.customer_id = room_bookings.customer_id
   GROUP BY customers.customer_id, customers.first_name, customers.last_name
   ORDER BY booking_count DESC
   LIMIT 10;

Q: What rooms are available from 2026-03-10 to 2026-03-14?
A: SELECT DISTINCT r.room_id, r.room_number, r.type, r.bed_type, r.view_type, r.base_rate
   FROM rooms r
   WHERE NOT EXISTS (
       SELECT 1 FROM room_availability ra
       WHERE ra.room_id = r.room_id
         AND ra.date >= '2026-03-10'
         AND ra.date < '2026-03-14'
         AND ra.status = 'Booked'
   )
   ORDER BY r.type, r.room_number;

Q: What is the total revenue by room type this year?
A: SELECT room_type,
          SUM(total_amount) AS total_revenue,
          COUNT(*) AS booking_count
   FROM room_bookings
   WHERE EXTRACT(YEAR FROM check_in) = EXTRACT(YEAR FROM CURRENT_DATE)
     AND booking_status != 'Cancelled'
   GROUP BY room_type
   ORDER BY total_revenue DESC;
"""

# -----------------------------------------------------------------------------
# System prompt for result explanation
# -----------------------------------------------------------------------------
_EXPLAIN_SYSTEM_PROMPT = """You are a helpful hotel data analyst at Blue Horizon luxury hotel.
Explain database query results in clear, warm, professional language.
Be concise: 2-4 sentences max. Highlight the most important insight.
If row count is 0, say no matching data was found and suggest a reason.
Format numbers nicely (e.g. $1,250.00 not 1250.0, 42 guests not 42)."""


class NL2SQLService:
    """
    Natural Language to SQL agent for Blue Horizon hotel data.

    Pipeline:
        generate_sql()   -> OpenAI produces a SELECT query from natural language
        execute_query()  -> SQLAlchemy runs it against Neon DB
        explain_results()-> OpenAI narrates the results in plain English
        query()          -> convenience end-to-end wrapper
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        """
        Args:
            model: OpenAI chat model (e.g. 'gpt-4o-mini', 'gpt-4o').
        """
        self.settings = get_settings()
        self.model    = model

        # OpenAI client
        self.client = OpenAI(api_key=self.settings.openai_api_key)

        # Neon DB connection pool
        self.engine = create_engine(
            self.settings.database_url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
            connect_args={
                "connect_timeout":     30,
                "keepalives":          1,
                "keepalives_idle":     30,
                "keepalives_interval": 10,
                "keepalives_count":    5,
            },
        )
        print(f"[OK] NL2SQL initialized  model={self.model}")

    # -------------------------------------------------------------------------
    # SQL generation
    # -------------------------------------------------------------------------

    def generate_sql(self, natural_query: str) -> str:
        """
        Translate a natural language question into a PostgreSQL SELECT query.

        Args:
            natural_query: Plain English question about hotel data.

        Returns:
            Ready-to-execute SQL SELECT string.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _SQL_SYSTEM_PROMPT},
                {"role": "user",   "content": natural_query},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        raw = response.choices[0].message.content.strip()
        return self._clean_sql(raw)

    @staticmethod
    def _clean_sql(raw: str) -> str:
        """Strip markdown fences and surrounding whitespace."""
        raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        return raw.strip()

    @staticmethod
    def _is_safe_sql(sql: str) -> bool:
        """Allow only SELECT statements � guard against mutating SQL."""
        first = sql.strip().split()[0].upper() if sql.strip() else ""
        return first == "SELECT"

    # -------------------------------------------------------------------------
    # Query execution
    # -------------------------------------------------------------------------

    def execute_query(self, sql_query: str) -> Dict[str, Any]:
        """
        Execute a SQL SELECT against Neon DB with one automatic retry on
        transient connection / SSL errors.

        Returns:
            success=True : {success, columns, rows, row_count}
            success=False: {success, error, columns=[], rows=[], row_count=0}
        """
        if not self._is_safe_sql(sql_query):
            return {
                "success":   False,
                "error":     "Only SELECT queries are permitted.",
                "columns":   [],
                "rows":      [],
                "row_count": 0,
            }

        last_error: Optional[Exception] = None

        for attempt in range(2):
            try:
                with self.engine.connect() as conn:
                    result  = conn.execute(text(sql_query))
                    columns = list(result.keys())
                    rows    = [dict(zip(columns, row)) for row in result.fetchall()]
                    return {
                        "success":   True,
                        "columns":   columns,
                        "rows":      rows,
                        "row_count": len(rows),
                    }
            except Exception as exc:
                last_error = exc
                is_transient = any(
                    k in str(exc).lower()
                    for k in ("ssl", "connection", "closed", "timeout")
                )
                if attempt == 0 and is_transient:
                    print(f"[NL2SQL] Transient DB error, retrying: {exc}")
                    self.engine.dispose()
                    continue
                break

        return {
            "success":   False,
            "error":     str(last_error),
            "columns":   [],
            "rows":      [],
            "row_count": 0,
        }

    # -------------------------------------------------------------------------
    # End-to-end convenience method
    # -------------------------------------------------------------------------

    def query(self, natural_query: str) -> Dict[str, Any]:
        """
        Full pipeline: natural language -> SQL -> execute -> return results.

        Args:
            natural_query: Plain English question.

        Returns:
            Dict with natural_query, sql_query, success, columns, rows,
            row_count (and error on failure).
        """
        sql_query = self.generate_sql(natural_query)
        result    = self.execute_query(sql_query)
        return {
            "natural_query": natural_query,
            "sql_query":     sql_query,
            **result,
        }

    # -------------------------------------------------------------------------
    # Result narration
    # -------------------------------------------------------------------------

    def explain_results(self, natural_query: str, results: Dict[str, Any]) -> str:
        """
        Produce a plain-English summary of query results using OpenAI.

        Args:
            natural_query: The original guest question.
            results:       Dict returned by query() or execute_query().

        Returns:
            Concise, human-readable explanation string.
        """
        if not results.get("success"):
            return f"The query could not be completed: {results.get('error', 'unknown error')}."

        rows      = results.get("rows", [])
        row_count = results.get("row_count", 0)

        user_prompt = (
            f"Guest question: {natural_query}\n\n"
            f"Query returned {row_count} row(s).\n"
            f"Sample data (first 5 rows):\n{rows[:5]}\n\n"
            "Please explain these results to the guest."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _EXPLAIN_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=256,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            print(f"[NL2SQL] explain_results error: {exc}")
            return f"Found {row_count} result(s) for your query."


# -----------------------------------------------------------------------------
# Quick smoke-test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
     NL2SQLService()
    # svc = NL2SQLService(model="gpt-4o-mini")
    # test_questions = [
    #     "Which guests have made the most bookings?",
    #     "What rooms are available from 2026-03-10 to 2026-03-14?",
    #     "What is the total revenue by room type this year?",
    #     "How many bookings were made in January 2026?",
    # ]
    # for q in test_questions:
    #     print(f"\n{'='*60}\nQ: {q}")
    #     r = svc.query(q)
    #     print(f"SQL : {r['sql_query']}")
    #     print(f"Rows: {r['row_count']}")
    #     if r["success"] and r["rows"]:
    #         print(f"Data: {r['rows'][:2]}")
    #         print(f"Expl: {svc.explain_results(q, r)}")
    #     else:
    #         print(f"Err : {r.get('error')}")
