from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import service

app = FastAPI(title="Biometrics Appointment API (all times UTC)")


class BookingCreate(BaseModel):
    applicant_id: str = Field(..., min_length=1, max_length=64)
    slot_id: str


@app.exception_handler(service.DomainError)
async def handle_domain_error(_: Request, exc: service.DomainError):
    return JSONResponse(status_code=exc.status,
                        content={"detail": {"code": exc.code, "message": exc.message}})


# Plain `def` so FastAPI runs these in a threadpool; the lock in service.py keeps them consistent.
@app.get("/slots")
def get_slots(center: Optional[str] = None,
              from_time: Optional[datetime] = Query(None, description="UTC, use trailing Z"),
              to_time: Optional[datetime] = Query(None, description="UTC, use trailing Z")):
    return service.list_slots(center, from_time, to_time)


@app.post("/bookings", status_code=201)
def create_booking(body: BookingCreate):
    return service.book(body.applicant_id, body.slot_id)


@app.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: str):
    return service.cancel(booking_id)

class RescheduleRequest(BaseModel):
    new_slot_id: str


@app.get("/slots/{slot_id}")
def get_slot_by_id(slot_id: str):
    return service.get_slot(slot_id)


@app.get("/bookings")
def list_bookings(applicant_id: str, include_cancelled: bool = False):
    return service.list_bookings_for(applicant_id, include_cancelled)


@app.get("/bookings/{booking_id}")
def get_booking_by_id(booking_id: str):
    return service.get_booking(booking_id)


@app.post("/bookings/{booking_id}/reschedule")
def reschedule_booking(booking_id: str, body: RescheduleRequest):
    return service.reschedule(booking_id, body.new_slot_id)