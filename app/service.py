import threading
import uuid
from datetime import datetime, timedelta, timezone

from app.seed import SLOTS_JSON

CUTOFF = timedelta(hours=24)
lock = threading.Lock()  # one lock around every check-then-write


class DomainError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status


def now():
    return datetime.now(timezone.utc)


def require_utc(dt, field):
    if dt is not None and (dt.tzinfo is None or dt.utcoffset() != timedelta(0)):
        raise DomainError("TIME_MUST_BE_UTC", f"{field} must be UTC, e.g. 2026-11-20T04:30:00Z", 422)


# Slots are converted from IST to UTC once, at load.
slots = {
    s["id"]: {**s, "start": datetime.fromisoformat(s["start"]).astimezone(timezone.utc)}
    for s in SLOTS_JSON
}
bookings = {}  # booking_id -> dict


def _seats_taken(slot_id):
    return sum(1 for b in bookings.values() if b["slot_id"] == slot_id and b["status"] == "active")


def list_slots(center=None, from_time=None, to_time=None):
    require_utc(from_time, "from_time")
    require_utc(to_time, "to_time")
    with lock:
        t = now()
        out = []
        for s in sorted(slots.values(), key=lambda s: s["start"]):
            left = s["capacity"] - _seats_taken(s["id"])
            if s["start"] <= t or left <= 0:
                continue
            if center and s["center"].lower() != center.strip().lower():
                continue
            if from_time and s["start"] < from_time:
                continue
            if to_time and s["start"] > to_time:
                continue
            out.append({"id": s["id"], "center": s["center"], "start_utc": s["start"],
                        "capacity": s["capacity"], "available_seats": left})
        return out


def book(applicant_id, slot_id):
    applicant = applicant_id.strip().upper()  # 'ab1' and 'AB1' are the same person
    if not applicant:
        raise DomainError("INVALID_APPLICANT_ID", "applicant_id must not be empty", 422)
    with lock:
        slot = slots.get(slot_id)
        if not slot:
            raise DomainError("SLOT_NOT_FOUND", f"No slot {slot_id}", 404)
        t = now()
        if slot["start"] <= t:
            raise DomainError("SLOT_IN_PAST", "Slot has already started or passed")
        if any(b["applicant_id"] == applicant and b["status"] == "active"
                and b["start_utc"] > t for b in bookings.values()):
            raise DomainError("ALREADY_HAS_BOOKING", "Applicant already has an active booking")
        if _seats_taken(slot_id) >= slot["capacity"]:
            raise DomainError("SLOT_FULL", "No seats left in this slot")
        b = {"booking_id": str(uuid.uuid4()), "applicant_id": applicant, "slot_id": slot_id,
             "start_utc": slot["start"], "status": "active", "booked_at_utc": t}
        bookings[b["booking_id"]] = b
        return b


def cancel(booking_id):
    with lock:
        b = bookings.get(booking_id)
        if not b:
            raise DomainError("BOOKING_NOT_FOUND", "No such booking", 404)
        if b["status"] != "active":
            raise DomainError("ALREADY_CANCELLED", "Booking is already cancelled")
        t = now()
        if b["start_utc"] - t < CUTOFF:
            raise DomainError("CANCELLATION_WINDOW_CLOSED", "Cancel at least 24 hours before the slot")
        b["status"] = "cancelled"
        b["cancelled_at_utc"] = t
        return b
def get_slot(slot_id):
    """One slot with live availability. Unlike list_slots, this also shows full or past slots."""
    with lock:
        s = slots.get(slot_id)
        if not s:
            raise DomainError("SLOT_NOT_FOUND", f"No slot {slot_id}", 404)
        return {"id": s["id"], "center": s["center"], "start_utc": s["start"],
                "capacity": s["capacity"], "available_seats": s["capacity"] - _seats_taken(slot_id),
                "is_past": s["start"] <= now()}


def get_booking(booking_id):
    with lock:
        b = bookings.get(booking_id)
        if not b:
            raise DomainError("BOOKING_NOT_FOUND", "No such booking", 404)
        return dict(b)


def list_bookings_for(applicant_id, include_cancelled=False):
    """An applicant's bookings, oldest first. Active only unless include_cancelled is set."""
    applicant = applicant_id.strip().upper()
    if not applicant:
        raise DomainError("INVALID_APPLICANT_ID", "applicant_id must not be empty", 422)
    with lock:
        mine = [dict(b) for b in bookings.values()
                if b["applicant_id"] == applicant and (include_cancelled or b["status"] == "active")]
        return sorted(mine, key=lambda b: b["booked_at_utc"])


def reschedule(booking_id, new_slot_id):
    """Move an active booking to another slot in one step.

    Every check runs first and nothing is changed until all pass, so a failed
    reschedule never loses the applicant's current seat. The old seat is freed
    and the new one taken in the same locked step.
    """
    with lock:
        b = bookings.get(booking_id)
        if not b:
            raise DomainError("BOOKING_NOT_FOUND", "No such booking", 404)
        if b["status"] != "active":
            raise DomainError("ALREADY_CANCELLED", "Booking is cancelled, make a new booking instead")
        if b["slot_id"] == new_slot_id:
            raise DomainError("SAME_SLOT", "Booking is already in this slot")
        new = slots.get(new_slot_id)
        if not new:
            raise DomainError("SLOT_NOT_FOUND", f"No slot {new_slot_id}", 404)
        t = now()
        if b["start_utc"] - t < CUTOFF:  # same 24h rule as cancelling the current slot
            raise DomainError("CANCELLATION_WINDOW_CLOSED",
                              "Can only reschedule at least 24 hours before the current slot")
        if new["start"] <= t:
            raise DomainError("SLOT_IN_PAST", "New slot has already started or passed")
        if _seats_taken(new_slot_id) >= new["capacity"]:
            raise DomainError("SLOT_FULL", "No seats left in the new slot")
        b["slot_id"] = new_slot_id
        b["start_utc"] = new["start"]
        b["rescheduled_at_utc"] = t
        return dict(b)