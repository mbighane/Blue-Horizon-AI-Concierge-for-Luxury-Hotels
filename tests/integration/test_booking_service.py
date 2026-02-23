"""
Test script for BookingService.

All DB read methods (list_room_types, get_customer, find_available_room)
now delegate SQL generation to OpenAI via _generate_read_sql().
create_booking() likewise delegates INSERT + UPDATE SQL to OpenAI
via _generate_booking_sql().

Run directly:
    python scripts/test_booking_service.py

Run via pytest:
    pytest scripts/test_booking_service.py -v
"""
from __future__ import annotations

import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.services.booking_service import BookingService

# ---------------------------------------------------------------------------
# Shared service instance
# ---------------------------------------------------------------------------
_svc: BookingService | None = None


def _get_svc() -> BookingService:
    global _svc
    if _svc is None:
        print("\nInitializing BookingService ...")
        _svc = BookingService()
        print("[OK] BookingService ready")
    return _svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _pass(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


# ---------------------------------------------------------------------------
# Test: _generate_read_sql  (OpenAI SQL helper)
# ---------------------------------------------------------------------------
def test_generate_read_sql(svc: BookingService) -> bool:
    _section("_generate_read_sql()  [OpenAI SELECT generator]")
    passed = True

    cases = [
        {
            "desc":    "Return all distinct values of the 'type' column from the rooms table, "
                       "excluding rooms with status 'Out of Service', ordered alphabetically.",
            "must_contain": ["SELECT", "rooms", "type"],
        },
        {
            "desc":    "Fetch customer_id, first_name, last_name, email and loyalty_tier "
                       "from the customers table where customer_id = 1.",
            "must_contain": ["SELECT", "customers", "customer_id"],
        },
        {
            "desc":    f"Find the single cheapest available room whose type matches 'Deluxe' "
                       f"(case-insensitive, partial match) for check_in = DATE '2026-06-01' "
                       f"to check_out = DATE '2026-06-05', supporting at least 2 adult(s), "
                       f"excluding status 'Out of Service', and excluding rooms with "
                       f"overlapping bookings. Return room_id, room_number, type, base_rate, "
                       f"bed_type, view_type, max_occupancy, floor. Order by base_rate. Limit 1.",
            "must_contain": ["SELECT", "rooms", "base_rate", "LIMIT"],
        },
    ]

    for i, case in enumerate(cases, 1):
        print(f"\n  Case {i}: {case['desc'][:70]} ...")
        try:
            sql = svc._generate_read_sql(case["desc"])
            print(f"  Generated SQL:\n    {sql[:200]}")
            for keyword in case["must_contain"]:
                if keyword.upper() not in sql.upper():
                    _fail(f"Expected keyword '{keyword}' in generated SQL")
                    passed = False
                    break
            else:
                _pass(f"SQL contains required keywords: {case['must_contain']}")
        except Exception as exc:
            _fail(f"Exception: {exc}")
            traceback.print_exc()
            passed = False

    return passed


# ---------------------------------------------------------------------------
# Test: _generate_booking_sql  (OpenAI SQL helper)
# ---------------------------------------------------------------------------
def test_generate_booking_sql(svc: BookingService) -> bool:
    _section("_generate_booking_sql()  [OpenAI INSERT+UPDATE generator]")

    sample_params = {
        "booking_id":       "BK-TEST1234",
        "customer_id":      1,
        "room_id":          "ROOM-001",
        "room_number":      101,
        "room_type":        "Deluxe",
        "check_in":         "2026-07-10",
        "check_out":        "2026-07-13",
        "duration_days":    3,
        "num_adults":       2,
        "num_children":     0,
        "loyalty_tier":     "Gold",
        "special_requests": "High floor preferred",
        "booking_status":   "Confirmed",
        "payment_method":   "Credit Card",
        "total_amount":     750.00,
        "points_earned":    7500,
    }

    try:
        sql_dict = svc._generate_booking_sql(sample_params)
        print(f"\n  insert_sql       :\n    {sql_dict.get('insert_sql', '')[:200]}")
        print(f"\n  availability_sql :\n    {sql_dict.get('availability_sql', '')[:200]}")

        assert "insert_sql"       in sql_dict, "Missing 'insert_sql' key"
        assert "availability_sql" in sql_dict, "Missing 'availability_sql' key"

        ins = sql_dict["insert_sql"].upper()
        avl = sql_dict["availability_sql"].upper()

        assert "INSERT" in ins and "ROOM_BOOKINGS" in ins, \
            "insert_sql must INSERT INTO room_bookings"
        assert "BK-TEST1234" in sql_dict["insert_sql"], \
            "booking_id not embedded in insert_sql"
        assert "CONFIRMED" in ins, "booking_status 'Confirmed' missing from insert_sql"

        assert "UPDATE" in avl and "ROOM_AVAILABILITY" in avl, \
            "availability_sql must UPDATE room_availability"
        assert "BOOKED" in avl, "status 'Booked' missing from availability_sql"
        assert "2026-07-10" in sql_dict["availability_sql"] or "07-10" in sql_dict["availability_sql"], \
            "check_in date not embedded in availability_sql"

        _pass("Both SQL statements generated and validated OK")
        return True

    except AssertionError as exc:
        _fail(f"Assertion: {exc}")
        return False
    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Test: list_room_types
# ---------------------------------------------------------------------------
def test_list_room_types(svc: BookingService) -> bool:
    _section("list_room_types()  [OpenAI-generated SQL]")
    try:
        types = svc.list_room_types()
        print(f"  Room types: {types}")
        if not types:
            _fail("No room types returned — check rooms table.")
            return False
        _pass(f"{len(types)} room type(s) found: {types}")
        return True
    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Test: get_customer
# ---------------------------------------------------------------------------
def test_get_customer(svc: BookingService) -> bool:
    _section("get_customer()  [OpenAI-generated SQL]")
    passed = True

    # Case 1 — valid customer (ID 1, expected to exist in seed data)
    print("\n  Case 1: existing customer (customer_id=1)")
    try:
        cust = svc.get_customer(1)
        if cust:
            print(f"    -> {cust}")
            _pass(
                f"customer_id={cust['customer_id']}  "
                f"{cust['first_name']} {cust['last_name']}  "
                f"tier={cust['loyalty_tier']}"
            )
        else:
            _warn("customer_id=1 not found — seed data may differ.")
    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        passed = False

    # Case 2 — non-existent customer
    print("\n  Case 2: non-existent customer (customer_id=999999)")
    try:
        cust = svc.get_customer(999999)
        if cust is None:
            _pass("Correctly returned None for unknown customer_id")
        else:
            _fail(f"Expected None, got: {cust}")
            passed = False
    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        passed = False

    return passed


# ---------------------------------------------------------------------------
# Test: find_available_room
# ---------------------------------------------------------------------------
def test_find_available_room(svc: BookingService) -> bool:
    _section("find_available_room()  [OpenAI-generated SQL]")
    passed = True

    check_in  = _future(30)   # 30 days from today — unlikely to be booked
    check_out = _future(33)   # 3-night stay

    room_types = svc.list_room_types() or ["Standard", "Deluxe", "Suite"]

    for room_type in room_types:
        print(f"\n  Room type: {room_type}  ({check_in} → {check_out})")
        try:
            room = svc.find_available_room(
                room_type=room_type,
                check_in=check_in,
                check_out=check_out,
                num_adults=2,
            )
            if room:
                _pass(
                    f"room_id={room['room_id']}  "
                    f"room_number={room['room_number']}  "
                    f"type={room['type']}  "
                    f"rate=${room['base_rate']}/night  "
                    f"occupancy<={room['max_occupancy']}"
                )
            else:
                _warn(f"No '{room_type}' room available for the test window — may be fully booked.")
        except Exception as exc:
            _fail(f"Exception: {exc}")
            traceback.print_exc()
            passed = False

    # Edge case: impossible occupancy
    print(f"\n  Edge case: num_adults=99 (should find nothing)")
    try:
        room = svc.find_available_room(
            room_type=room_types[0] if room_types else "Standard",
            check_in=check_in,
            check_out=check_out,
            num_adults=99,
        )
        if room is None:
            _pass("Correctly returned None for impossible occupancy")
        else:
            _fail(f"Expected None for num_adults=99, got room: {room}")
            passed = False
    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        passed = False

    return passed


# ---------------------------------------------------------------------------
# Test: create_booking (full end-to-end write)
# ---------------------------------------------------------------------------
def test_create_booking(svc: BookingService) -> bool:
    _section("create_booking()  [OpenAI-generated SQL + writes to NeonDB]") 

    # Pre-conditions: need a real customer and a real available room
    customer = svc.get_customer(1)
    if not customer:
        _warn("customer_id=1 not found — skipping create_booking test.")
        return True

    check_in  = _future(60)   # well in the future to avoid conflicts
    check_out = _future(62)   # 2-night stay

    room_types = svc.list_room_types()
    room = None
    used_type = None
    for rt in room_types:
        room = svc.find_available_room(rt, check_in, check_out, num_adults=1)
        if room:
            used_type = rt
            break

    if not room:
        _warn(f"No availability found in window {check_in}→{check_out}. Skipping write test.")
        return True

    nights       = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    total_amount = round(float(room["base_rate"]) * nights, 2)

    print(f"\n  Creating booking for:")
    print(f"    customer_id={customer['customer_id']}  "
          f"{customer['first_name']} {customer['last_name']}")
    print(f"    room_id={room['room_id']}  type={room['type']}  "
          f"room_number={room['room_number']}")
    print(f"    {check_in} -> {check_out}  ({nights} nights)  total=${total_amount}")

    try:
        confirm = svc.create_booking(
            customer_id     = customer["customer_id"],
            room_id         = room["room_id"],
            room_number     = int(room["room_number"]),
            room_type       = room["type"],
            check_in        = check_in,
            check_out       = check_out,
            num_adults      = 2,
            num_children    = 0,
            total_amount    = total_amount,
            payment_method  = "Credit Card",
            special_requests= "Test booking — automated test",
            loyalty_tier    = customer.get("loyalty_tier", "Standard"),
        )

        print(f"\n  Confirmation:")
        for k, v in confirm.items():
            print(f"    {k}: {v}")

        assert confirm["booking_status"] == "Confirmed", \
            f"Expected 'Confirmed', got '{confirm['booking_status']}'"
        assert confirm["booking_id"].startswith("BK-"), \
            f"Unexpected booking_id format: {confirm['booking_id']}"
        assert confirm["duration_days"] == nights, \
            f"Expected {nights} nights, got {confirm['duration_days']}"
        assert confirm["total_amount"] == total_amount, \
            f"Total mismatch: {confirm['total_amount']} vs {total_amount}"
        assert confirm["points_earned"] > 0, "points_earned should be > 0"

        _pass(f"Booking created: {confirm['booking_id']}  "
              f"${confirm['total_amount']:,.2f}  "
              f"{confirm['points_earned']} pts")
        return True

    except AssertionError as exc:
        _fail(f"Assertion: {exc}")
        return False
    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Invalid input tests
# ---------------------------------------------------------------------------
def test_invalid_inputs(svc: BookingService) -> bool:
    _section("Invalid input handling")
    passed = True

    # check_out before check_in
    print("\n  Case: check_out before check_in")
    try:
        svc.create_booking(
            customer_id=1, room_id=1, room_number=101, room_type="Standard",
            check_in=_future(5), check_out=_future(3),   # out < in
            num_adults=1, num_children=0, total_amount=200.0,
        )
        _fail("Expected ValueError for inverted dates, but no exception raised")
        passed = False
    except ValueError as exc:
        _pass(f"Correctly raised ValueError: {exc}")
    except Exception as exc:
        _fail(f"Wrong exception type {type(exc).__name__}: {exc}")
        passed = False

    # same-day check-in and check-out
    print("\n  Case: same-day check-in and check-out (0 nights)")
    today = date.today().isoformat()
    try:
        svc.create_booking(
            customer_id=1, room_id=1, room_number=101, room_type="Standard",
            check_in=today, check_out=today,
            num_adults=1, num_children=0, total_amount=0.0,
        )
        _fail("Expected ValueError for 0-night stay, but no exception raised")
        passed = False
    except ValueError as exc:
        _pass(f"Correctly raised ValueError: {exc}")
    except Exception as exc:
        _fail(f"Wrong exception type {type(exc).__name__}: {exc}")
        passed = False

    return passed


# ---------------------------------------------------------------------------
# Test: parse_booking_request (OpenAI agent)
# ---------------------------------------------------------------------------
def test_parse_booking_request(svc: BookingService) -> bool:
    _section("parse_booking_request()  [OpenAI agent]")
    passed = True

    cases = [
        {
            "input":    "Book a Deluxe room for customer 42, 2 adults, check-in March 10 2026, check-out March 14 2026.",
            "expected": {"room_type": "Deluxe", "customer_id": 42, "num_adults": 2},
        },
        {
            "input":    "I'd like a Suite from April 1 to April 5 for 1 adult. No customer ID yet.",
            "expected": {"room_type": "Suite"},
            "missing":  ["customer_id"],
        },
        {
            "input":    "Book something nice",   # intentionally vague
            "missing":  ["customer_id", "room_type", "check_in", "check_out"],
        },
    ]

    for i, case in enumerate(cases, 1):
        print(f"\n  Case {i}: {case['input'][:70]}")
        try:
            result = svc.parse_booking_request(case["input"])
            print(f"    -> {result}")

            for key, val in case.get("expected", {}).items():
                if str(result.get(key)).lower() != str(val).lower():
                    _fail(f"Expected {key}={val!r}, got {result.get(key)!r}")
                    passed = False
                    continue

            for missing_field in case.get("missing", []):
                if missing_field not in result.get("missing_fields", []):
                    _warn(f"Expected '{missing_field}' in missing_fields, got {result.get('missing_fields')}")

            _pass(f"Parsed OK  missing_fields={result.get('missing_fields', [])}")
        except Exception as exc:
            _fail(f"Exception: {exc}")
            traceback.print_exc()
            passed = False

    return passed


# ---------------------------------------------------------------------------
# Test: suggest_alternatives (OpenAI agent)
# ---------------------------------------------------------------------------
def test_suggest_alternatives(svc: BookingService) -> bool:
    _section("suggest_alternatives()  [OpenAI agent]")
    check_in  = _future(30)
    check_out = _future(33)

    # Use a fake type that almost certainly has no rooms
    print(f"\n  Requesting impossible type 'Penthouse' ({check_in} -> {check_out})")
    try:
        suggestion = svc.suggest_alternatives(
            original_request="Book a Penthouse for 2 adults",
            unavailable_type="Penthouse",
            check_in=check_in,
            check_out=check_out,
            num_adults=2,
        )
        print(f"\n  [OpenAI Suggestion]:\n  {suggestion}")
        if suggestion:
            _pass("suggest_alternatives returned a non-empty response")
            return True
        else:
            _fail("Empty suggestion returned")
            return False
    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Test: book() pipeline (OpenAI agent — end-to-end)
# ---------------------------------------------------------------------------
def test_book_pipeline(svc: BookingService) -> bool:
    _section("book()  [OpenAI end-to-end pipeline]")

    check_in  = _future(90)
    check_out = _future(92)
    room_types = svc.list_room_types()
    if not room_types:
        _warn("No room types available — skipping book() pipeline test.")
        return True

    request = (
        f"Please book a {room_types[0]} room for customer ID 1, "
        f"2 adults, check-in {check_in}, check-out {check_out}, "
        f"payment by credit card, no special requests."
    )
    print(f"\n  Request: {request}")

    try:
        result = svc.book(request)
        print(f"\n  Result: success={result['success']}")
        print(f"  Params: {result['params']}")
        print(f"\n  [OpenAI Message]:\n{result['message']}")

        if result["success"]:
            assert result["booking"] is not None
            assert result["booking"]["booking_status"] == "Confirmed"
            _pass(f"Booking confirmed: {result['booking']['booking_id']}")
        else:
            # Acceptable if no availability at that date
            _warn(f"Booking not made (may be unavailability): {result['message'][:120]}")
        return True

    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        return False

def main() -> None:
    print("=" * 60)
    print("  Blue Horizon — BookingService Tests")
    print("=" * 60)

    svc = _get_svc()

    results = {
        "generate_read_sql":      test_generate_read_sql(svc),
        "generate_booking_sql":   test_generate_booking_sql(svc),
        "list_room_types":        test_list_room_types(svc),
        "get_customer":           test_get_customer(svc),
        "find_available_room":    test_find_available_room(svc),
        "create_booking":         test_create_booking(svc),
        "invalid_inputs":         test_invalid_inputs(svc),
        "parse_booking_request":  test_parse_booking_request(svc),
        "suggest_alternatives":   test_suggest_alternatives(svc),
        "book_pipeline":          test_book_pipeline(svc),
    }

    _section("SUMMARY")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\n  RESULT: {passed}/{total} test groups passed")


# ---------------------------------------------------------------------------
# Pytest-compatible test functions
# ---------------------------------------------------------------------------

def test_generate_read_sql_pytest():
    assert test_generate_read_sql(_get_svc())

def test_generate_booking_sql_pytest():
    assert test_generate_booking_sql(_get_svc())

def test_list_room_types_pytest():
    assert test_list_room_types(_get_svc())

def test_get_customer_pytest():
    assert test_get_customer(_get_svc())

def test_find_available_room_pytest():
    assert test_find_available_room(_get_svc())

def test_create_booking_pytest():
    assert test_create_booking(_get_svc())

def test_invalid_inputs_pytest():
    assert test_invalid_inputs(_get_svc())

def test_parse_booking_request_pytest():
    assert test_parse_booking_request(_get_svc())

def test_suggest_alternatives_pytest():
    assert test_suggest_alternatives(_get_svc())

def test_book_pipeline_pytest():
    assert test_book_pipeline(_get_svc())


if __name__ == "__main__":
    main()
