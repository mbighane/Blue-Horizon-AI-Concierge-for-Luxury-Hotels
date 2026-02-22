"""
Room Booking Service — creates bookings in NeonDB and updates room_availability.

Tables touched:
  - room_bookings    : INSERT new confirmed booking row
  - room_availability: UPDATE status → 'Booked' for each occupied night
"""
from __future__ import annotations

import uuid
import sys
from pathlib import Path
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import create_engine, text

try:
    from backend.app.config import get_settings
except ImportError:
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from backend.app.config import get_settings


class BookingService:
    """Handles availability checks and booking writes to NeonDB."""

    def __init__(self) -> None:
        settings = get_settings()
        self.engine = create_engine(
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

    # ──────────────────────────────────────────────────────────────────────────
    # Read helpers
    # ──────────────────────────────────────────────────────────────────────────

    def list_room_types(self) -> list[str]:
        """Return distinct room types that are not out-of-service."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT type FROM rooms "
                    "WHERE status != 'Out of Service' ORDER BY type"
                )
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def get_customer(self, customer_id: int) -> Optional[dict]:
        """Fetch basic customer info by ID."""
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT customer_id, first_name, last_name, "
                    "       email, loyalty_tier "
                    "FROM   customers "
                    "WHERE  customer_id = :cid"
                ),
                {"cid": customer_id},
            ).fetchone()
        return dict(row._mapping) if row else None

    def find_available_room(
        self,
        room_type: str,
        check_in: str,
        check_out: str,
        num_adults: int = 1,
    ) -> Optional[dict]:
        """
        Return the cheapest available room matching *room_type* for the
        requested date range, or None if nothing is free.

        A room is considered unavailable if it has any non-cancelled booking
        that overlaps the requested window.
        """
        with self.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT r.room_id,
                           r.room_number,
                           r.type,
                           r.base_rate,
                           r.bed_type,
                           r.view_type,
                           r.max_occupancy,
                           r.floor
                    FROM   rooms r
                    WHERE  LOWER(r.type) LIKE LOWER(:pattern)
                      AND  r.status != 'Out of Service'
                      AND  r.max_occupancy >= :num_adults
                      AND  r.room_id NOT IN (
                               SELECT rb.room_id
                               FROM   room_bookings rb
                               WHERE  rb.booking_status NOT IN ('Cancelled', 'No Show')
                                 AND  rb.room_id IS NOT NULL
                                 AND  rb.check_in  < CAST(:check_out AS date)
                                 AND  rb.check_out > CAST(:check_in  AS date)
                           )
                    ORDER  BY r.base_rate
                    LIMIT  1
                """),
                {
                    "pattern": f"%{room_type}%",
                    "check_in": check_in,
                    "check_out": check_out,
                    "num_adults": num_adults,
                },
            ).fetchone()
        return dict(row._mapping) if row else None

    # ──────────────────────────────────────────────────────────────────────────
    # Write
    # ──────────────────────────────────────────────────────────────────────────

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
          1. INSERT a new row into room_bookings with status 'Confirmed'.
          2. UPDATE room_availability to 'Booked' for each night.

        Returns a confirmation dict with the generated booking_id.
        """
        check_in_date  = date.fromisoformat(check_in)
        check_out_date = date.fromisoformat(check_out)
        duration_days  = (check_out_date - check_in_date).days

        if duration_days <= 0:
            raise ValueError("check_out must be after check_in")

        booking_id    = f"BK-{uuid.uuid4().hex[:8].upper()}"
        points_earned = max(1, int(total_amount * 10))  # 10 pts per $ spent

        with self.engine.begin() as conn:
            # ── 1. Insert booking ──────────────────────────────────────────
            conn.execute(
                text("""
                    INSERT INTO room_bookings (
                        booking_id, customer_id, room_number, room_type,
                        check_in, check_out, duration_days,
                        num_adults, num_children, loyalty_tier,
                        special_requests, booking_status,
                        payment_method, total_amount, points_earned, room_id
                    ) VALUES (
                        :booking_id, :customer_id, :room_number, :room_type,
                        CAST(:check_in  AS date),
                        CAST(:check_out AS date),
                        :duration_days,
                        :num_adults, :num_children, :loyalty_tier,
                        :special_requests, 'Confirmed',
                        :payment_method, :total_amount, :points_earned, :room_id
                    )
                """),
                {
                    "booking_id":    booking_id,
                    "customer_id":   customer_id,
                    "room_number":   room_number,
                    "room_type":     room_type,
                    "check_in":      check_in,
                    "check_out":     check_out,
                    "duration_days": duration_days,
                    "num_adults":    num_adults,
                    "num_children":  num_children,
                    "loyalty_tier":  loyalty_tier,
                    "special_requests": special_requests,
                    "payment_method":   payment_method,
                    "total_amount":  total_amount,
                    "points_earned": points_earned,
                    "room_id":       room_id,
                },
            )

            # ── 2. Mark each night as Booked in room_availability ──────────
            curr = check_in_date
            while curr < check_out_date:
                conn.execute(
                    text("""
                        UPDATE room_availability
                        SET    status = 'Booked'
                        WHERE  room_id = :room_id
                          AND  date    = :night
                    """),
                    {"room_id": room_id, "night": curr.isoformat()},
                )
                curr += timedelta(days=1)

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
