import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app import service
from tests.conftest import code

UTC = timezone.utc


def ids(resp):
    return [s["id"] for s in resp.json()]


def parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------- GET /slots
class TestListSlots:
    def test_excludes_past_and_zero_capacity(self, client):
        got = ids(client.get("/slots"))
        for hidden in ("S4", "S6", "S14"):
            assert hidden not in got

    def test_includes_future_slots(self, client):
        got = ids(client.get("/slots"))
        for shown in ("S1", "S2", "S3", "S5", "S7", "S8", "S9", "S10", "S11", "S12", "S13"):
            assert shown in got

    def test_sorted_by_start_time(self, client):
        starts = [parse(s["start_utc"]) for s in client.get("/slots").json()]
        assert starts == sorted(starts)

    def test_center_filter_case_and_space_insensitive(self, client):
        assert set(ids(client.get("/slots", params={"center": "  dElHi "}))) == {"S1", "S2", "S8"}

    def test_unknown_center_returns_empty(self, client):
        r = client.get("/slots", params={"center": "Atlantis"})
        assert r.status_code == 200 and r.json() == []

    def test_time_range_filter_inclusive(self, client):
        r = client.get("/slots", params={"from_time": "2026-11-20T04:30:00Z",
                                         "to_time": "2026-11-20T05:30:00Z"})
        assert set(ids(r)) == {"S1", "S2", "S12"}

    def test_ist_slot_converted_to_utc(self, client):
        s10 = next(s for s in client.get("/slots").json() if s["id"] == "S10")
        assert parse(s10["start_utc"]) == datetime(2026, 11, 21, 19, 0, tzinfo=UTC)

    def test_utc_seed_slot_unchanged(self, client):
        s11 = next(s for s in client.get("/slots").json() if s["id"] == "S11")
        assert parse(s11["start_utc"]) == datetime(2026, 11, 22, 9, 0, tzinfo=UTC)

    @pytest.mark.parametrize("value", ["2026-11-20T04:30:00", "2026-11-20T10:00:00+05:30"])
    def test_non_utc_filter_rejected(self, client, value):
        for field in ("from_time", "to_time"):
            r = client.get("/slots", params={field: value})
            assert r.status_code == 422 and code(r) == "TIME_MUST_BE_UTC"

    def test_garbage_time_rejected(self, client):
        assert client.get("/slots", params={"from_time": "tomorrow"}).status_code == 422

    def test_available_seats_decrease_and_full_slot_disappears(self, client, book):
        assert book("A1", "S2").status_code == 201          # S2 capacity 1
        assert "S2" not in ids(client.get("/slots"))
        assert book("A2", "S1").status_code == 201          # S1 capacity 2
        s1 = next(s for s in client.get("/slots").json() if s["id"] == "S1")
        assert s1["available_seats"] == 1

    def test_slot_vanishes_once_started(self, client, clock):
        clock.set(datetime(2026, 11, 14, 3, 30, tzinfo=UTC))   # exactly S5 start
        assert "S5" not in ids(client.get("/slots"))


# ----------------------------------------------------------- GET /slots/{id}
class TestGetSlot:
    def test_existing(self, client):
        r = client.get("/slots/S1")
        assert r.status_code == 200
        assert r.json()["available_seats"] == 2 and r.json()["is_past"] is False

    def test_past_slot_still_visible_and_flagged(self, client):
        r = client.get("/slots/S4")
        assert r.status_code == 200 and r.json()["is_past"] is True

    def test_zero_capacity_visible(self, client):
        r = client.get("/slots/S14")
        assert r.json()["capacity"] == 0 and r.json()["available_seats"] == 0

    def test_not_found(self, client):
        r = client.get("/slots/NOPE")
        assert r.status_code == 404 and code(r) == "SLOT_NOT_FOUND"


# ------------------------------------------------------------- POST /bookings
class TestBook:
    def test_success(self, book):
        r = book("AB1", "S1")
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "active" and body["slot_id"] == "S1"
        assert body["applicant_id"] == "AB1"
        assert body["booking_id"]

    def test_applicant_id_normalised(self, book):
        assert book("  ab1 ", "S1").json()["applicant_id"] == "AB1"

    def test_same_applicant_different_case_is_duplicate(self, book):
        book("ab1", "S1")
        r = book("AB1", "S3")
        assert r.status_code == 409 and code(r) == "ALREADY_HAS_BOOKING"

    def test_same_applicant_same_slot_rejected(self, book):
        book("AB1", "S1")
        assert code(book("AB1", "S1")) == "ALREADY_HAS_BOOKING"

    def test_unknown_slot(self, book):
        r = book("AB1", "NOPE")
        assert r.status_code == 404 and code(r) == "SLOT_NOT_FOUND"

    @pytest.mark.parametrize("slot", ["S4", "S6"])
    def test_past_slot(self, book, slot):
        r = book("AB1", slot)
        assert r.status_code == 409 and code(r) == "SLOT_IN_PAST"

    def test_slot_exactly_at_now_is_past(self, book, clock):
        clock.set(datetime(2026, 11, 14, 3, 30, tzinfo=UTC))
        assert code(book("AB1", "S5")) == "SLOT_IN_PAST"

    def test_full_slot(self, book):
        book("A1", "S2")
        r = book("A2", "S2")
        assert r.status_code == 409 and code(r) == "SLOT_FULL"

    def test_zero_capacity_slot_always_full(self, book):
        assert code(book("A1", "S14")) == "SLOT_FULL"

    def test_capacity_filled_exactly(self, book):
        assert book("A1", "S1").status_code == 201
        assert book("A2", "S1").status_code == 201
        assert code(book("A3", "S1")) == "SLOT_FULL"

    def test_under_24h_slot_is_still_bookable(self, book):
        assert book("AB1", "S5").status_code == 201

    @pytest.mark.parametrize("applicant", ["", "   "])
    def test_empty_applicant(self, client, applicant):
        r = client.post("/bookings", json={"applicant_id": applicant, "slot_id": "S1"})
        assert r.status_code == 422

    def test_whitespace_applicant_domain_code(self, book):
        r = book("   ", "S1")
        assert r.status_code == 422 and code(r) == "INVALID_APPLICANT_ID"

    def test_applicant_id_too_long(self, book):
        assert book("x" * 65, "S1").status_code == 422

    @pytest.mark.parametrize("payload", [{}, {"applicant_id": "A1"}, {"slot_id": "S1"}])
    def test_missing_fields(self, client, payload):
        assert client.post("/bookings", json=payload).status_code == 422

    def test_failed_booking_does_not_consume_seat(self, client, book):
        book("A1", "S4")  # fails: past
        assert client.get("/slots/S1").json()["available_seats"] == 2


# --------------------------------------------------- DELETE /bookings/{id}
class TestCancel:
    def test_cancel_success_frees_seat(self, client, book):
        bid = book("A1", "S2").json()["booking_id"]
        r = client.delete(f"/bookings/{bid}")
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        assert client.get("/slots/S2").json()["available_seats"] == 1
        assert book("A2", "S2").status_code == 201

    def test_can_rebook_after_cancel(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        client.delete(f"/bookings/{bid}")
        assert book("A1", "S3").status_code == 201

    def test_cancel_twice(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        client.delete(f"/bookings/{bid}")
        r = client.delete(f"/bookings/{bid}")
        assert r.status_code == 409 and code(r) == "ALREADY_CANCELLED"

    def test_unknown_booking(self, client):
        r = client.delete("/bookings/nope")
        assert r.status_code == 404 and code(r) == "BOOKING_NOT_FOUND"

    def test_within_24h_blocked(self, client, book):
        bid = book("A1", "S5").json()["booking_id"]   # S5 is ~21.5h away
        r = client.delete(f"/bookings/{bid}")
        assert r.status_code == 409 and code(r) == "CANCELLATION_WINDOW_CLOSED"
        assert client.get(f"/bookings/{bid}").json()["status"] == "active"

    def test_exactly_24h_allowed(self, client, book, clock):
        bid = book("A1", "S8").json()["booking_id"]
        s8_start = parse(client.get("/slots/S8").json()["start_utc"])
        clock.set(s8_start - timedelta(hours=24))
        assert client.delete(f"/bookings/{bid}").status_code == 200

    def test_one_second_inside_24h_blocked(self, client, book, clock):
        bid = book("A1", "S8").json()["booking_id"]
        s8_start = parse(client.get("/slots/S8").json()["start_utc"])
        clock.set(s8_start - timedelta(hours=24) + timedelta(seconds=1))
        assert code(client.delete(f"/bookings/{bid}")) == "CANCELLATION_WINDOW_CLOSED"

    def test_cancelled_at_recorded(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        assert "cancelled_at_utc" in client.delete(f"/bookings/{bid}").json()


# --------------------------------------------------------- GET /bookings...
class TestReadBookings:
    def test_get_by_id(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        r = client.get(f"/bookings/{bid}")
        assert r.status_code == 200 and r.json()["booking_id"] == bid

    def test_get_by_id_not_found(self, client):
        r = client.get("/bookings/nope")
        assert r.status_code == 404 and code(r) == "BOOKING_NOT_FOUND"

    def test_list_active_only_by_default(self, client, book):
        b1 = book("A1", "S1").json()["booking_id"]
        client.delete(f"/bookings/{b1}")
        b2 = book("A1", "S3").json()["booking_id"]
        got = client.get("/bookings", params={"applicant_id": "A1"}).json()
        assert [b["booking_id"] for b in got] == [b2]

    def test_list_include_cancelled_oldest_first(self, client, book, clock):
        b1 = book("A1", "S1").json()["booking_id"]
        client.delete(f"/bookings/{b1}")
        clock.advance(minutes=5)
        b2 = book("A1", "S3").json()["booking_id"]
        got = client.get("/bookings", params={"applicant_id": "a1", "include_cancelled": True}).json()
        assert [b["booking_id"] for b in got] == [b1, b2]

    def test_list_unknown_applicant_empty(self, client):
        r = client.get("/bookings", params={"applicant_id": "ZZZ"})
        assert r.status_code == 200 and r.json() == []

    def test_list_requires_applicant_id(self, client):
        assert client.get("/bookings").status_code == 422

    def test_list_blank_applicant_rejected(self, client):
        r = client.get("/bookings", params={"applicant_id": "  "})
        assert r.status_code == 422 and code(r) == "INVALID_APPLICANT_ID"

    def test_list_does_not_leak_other_applicants(self, client, book):
        book("A1", "S1"); book("A2", "S1")
        got = client.get("/bookings", params={"applicant_id": "A1"}).json()
        assert len(got) == 1 and got[0]["applicant_id"] == "A1"


# ------------------------------------------- POST /bookings/{id}/reschedule
class TestReschedule:
    def resched(self, client, bid, slot):
        return client.post(f"/bookings/{bid}/reschedule", json={"new_slot_id": slot})

    def test_success_moves_seat(self, client, book):
        bid = book("A1", "S2").json()["booking_id"]
        r = self.resched(client, bid, "S3")
        assert r.status_code == 200 and r.json()["slot_id"] == "S3"
        assert "rescheduled_at_utc" in r.json()
        assert client.get("/slots/S2").json()["available_seats"] == 1
        assert client.get("/slots/S3").json()["available_seats"] == 2

    def test_booking_id_unchanged(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        assert self.resched(client, bid, "S3").json()["booking_id"] == bid

    def test_start_time_updated(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        r = self.resched(client, bid, "S10")
        assert parse(r.json()["start_utc"]) == datetime(2026, 11, 21, 19, 0, tzinfo=UTC)

    def test_same_slot(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        r = self.resched(client, bid, "S1")
        assert r.status_code == 409 and code(r) == "SAME_SLOT"

    def test_full_target_keeps_old_seat(self, client, book):
        book("A9", "S2")                                   # fills S2
        bid = book("A1", "S1").json()["booking_id"]
        r = self.resched(client, bid, "S2")
        assert r.status_code == 409 and code(r) == "SLOT_FULL"
        assert client.get(f"/bookings/{bid}").json()["slot_id"] == "S1"
        assert client.get("/slots/S1").json()["available_seats"] == 1

    def test_past_target(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        assert code(self.resched(client, bid, "S4")) == "SLOT_IN_PAST"

    def test_unknown_target(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        r = self.resched(client, bid, "NOPE")
        assert r.status_code == 404 and code(r) == "SLOT_NOT_FOUND"

    def test_unknown_booking(self, client):
        r = self.resched(client, "nope", "S1")
        assert r.status_code == 404 and code(r) == "BOOKING_NOT_FOUND"

    def test_cancelled_booking(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        client.delete(f"/bookings/{bid}")
        assert code(self.resched(client, bid, "S3")) == "ALREADY_CANCELLED"

    def test_within_24h_of_current_slot_blocked(self, client, book):
        bid = book("A1", "S5").json()["booking_id"]
        assert code(self.resched(client, bid, "S3")) == "CANCELLATION_WINDOW_CLOSED"

    def test_zero_capacity_target(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        assert code(self.resched(client, bid, "S14")) == "SLOT_FULL"

    def test_missing_body(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        assert client.post(f"/bookings/{bid}/reschedule", json={}).status_code == 422

    def test_can_reschedule_twice(self, client, book):
        bid = book("A1", "S1").json()["booking_id"]
        self.resched(client, bid, "S3")
        assert self.resched(client, bid, "S9").json()["slot_id"] == "S9"


# ------------------------------------------------------------- concurrency
class TestConcurrency:
    def test_last_seat_booked_once(self):
        barrier = threading.Barrier(20)

        def go(i):
            barrier.wait()
            try:
                service.book(f"USER{i}", "S2")           # capacity 1
                return "ok"
            except service.DomainError as e:
                return e.code

        with ThreadPoolExecutor(20) as ex:
            results = list(ex.map(go, range(20)))
        assert results.count("ok") == 1
        assert results.count("SLOT_FULL") == 19

    def test_same_applicant_cannot_double_book(self):
        barrier = threading.Barrier(10)
        slots = ["S1", "S3", "S9", "S12", "S13", "S7", "S8", "S10", "S11", "S2"]

        def go(slot):
            barrier.wait()
            try:
                service.book("SAME", slot)
                return "ok"
            except service.DomainError as e:
                return e.code

        with ThreadPoolExecutor(10) as ex:
            results = list(ex.map(go, slots))
        assert results.count("ok") == 1

    def test_reschedule_and_book_race_on_last_seat(self):
        service.book("OWNER", "S1")
        bid = service.book("MOVER", "S3")["booking_id"]
        barrier = threading.Barrier(2)

        def mover():
            barrier.wait()
            try:
                service.reschedule(bid, "S2"); return "ok"
            except service.DomainError as e:
                return e.code

        def booker():
            barrier.wait()
            try:
                service.book("NEWBIE", "S2"); return "ok"
            except service.DomainError as e:
                return e.code

        with ThreadPoolExecutor(2) as ex:
            r = [f.result() for f in (ex.submit(mover), ex.submit(booker))]
        assert r.count("ok") == 1 and r.count("SLOT_FULL") == 1
        assert service._seats_taken("S2") == 1



def test_past_booking_should_not_block_new_booking(book, clock):
    assert book("A1", "S5").status_code == 201
    clock.set(datetime(2026, 11, 14, 4, 0, tzinfo=UTC))
    assert book("A1", "S9").status_code == 201