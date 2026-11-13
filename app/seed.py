SLOTS_JSON = [
    {"id": "S1", "center": "Delhi",  "start": "2026-11-20T10:00:00+05:30", "capacity": 2},
    {"id": "S2", "center": "Delhi",  "start": "2026-11-20T11:00:00+05:30", "capacity": 1},
    {"id": "S3", "center": "Mumbai", "start": "2026-11-21T09:30:00+05:30", "capacity": 3},
    {"id": "S4", "center": "Delhi",  "start": "2026-11-12T10:00:00+05:30", "capacity": 2},
    {"id": "S5", "center": "Mumbai", "start": "2026-11-14T09:00:00+05:30", "capacity": 1},
    {"id": "S6",  "center": "Delhi", "start": "2026-11-13T09:00:00+05:30", "capacity": 2},   # earlier today: past
    {"id": "S7",  "center": "Mumbai", "start": "2026-11-14T18:00:00+05:30", "capacity": 2},   # future but under 24h: bookable, not cancellable
    {"id": "S8",  "center": "Delhi",     "start": "2026-11-14T23:30:00+05:30", "capacity": 2},   # borderline: cancellable only until 23:30 IST on Nov 13
    {"id": "S9",  "center": "Bengaluru", "start": "2026-11-15T10:00:00+05:30", "capacity": 5},   # comfortably cancellable, bigger capacity
    {"id": "S10", "center": "Chennai",   "start": "2026-11-22T00:30:00+05:30", "capacity": 2},   # Nov 22 in IST but Nov 21 in UTC
    {"id": "S11", "center": "Kolkata",   "start": "2026-11-22T09:00:00Z",      "capacity": 1},   # already in UTC, capacity 1
    {"id": "S12", "center": "Mumbai",    "start": "2026-11-20T10:00:00+05:30", "capacity": 2},   # same start time as S1, different center
    {"id": "S13", "center": "Mumbai",    "start": "2027-01-15T09:00:00+05:30", "capacity": 10},  # far future, large capacity
    {"id": "S14", "center": "Delhi",     "start": "2026-11-25T14:00:00+05:30", "capacity": 0},   # zero capacity: never available
]