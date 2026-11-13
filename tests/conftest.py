from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import service
from app.main import app

# 2026-11-13 11:30 IST. With the seed data this gives:
#   S4, S6 -> past | S5 -> bookable but < 24h (not cancellable) | S7, S8, S9 -> cancellable
#   S14 -> capacity 0 | S2, S11 -> capacity 1
NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """Freeze time and reset bookings so every test is deterministic and isolated."""
    service.bookings.clear()
    c = Clock(NOW)
    monkeypatch.setattr(service, "now", c)
    yield c
    service.bookings.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def book(client):
    def _book(applicant, slot):
        return client.post("/bookings", json={"applicant_id": applicant, "slot_id": slot})
    return _book


def code(resp):
    return resp.json()["detail"]["code"]