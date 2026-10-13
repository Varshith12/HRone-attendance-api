"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator, Field
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

load_dotenv(override=False)

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI is required.")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[MONGO_DB]

IST = timezone(timedelta(hours=5, minutes=30))
PRESENCE_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}
ALL_STATUSES = PRESENCE_STATUSES | {"ABSENT", "LEAVE"}

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def now_utc() -> datetime:
    """Return the current UTC time truncated to whole seconds."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def ist_date(value: datetime) -> date:
    """Return the calendar date of a datetime in Indian Standard Time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST).date()


def parse_calendar_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Date must use YYYY-MM-DD format.")
    if parsed.isoformat() != value:
        raise HTTPException(status_code=422, detail="Date must use YYYY-MM-DD format.")
    return parsed


def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    attendance_date: Optional[str] = None,
) -> int:
    local = (
        punch_in.astimezone(IST)
        if punch_in.tzinfo
        else punch_in.replace(tzinfo=timezone.utc).astimezone(IST)
    )
    day = parse_calendar_date(attendance_date) if attendance_date else local.date()
    hour, minute = map(int, shift_start.split(":"))
    scheduled = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(
        hour=hour, minute=minute
    )
    actual = punch_in.astimezone(IST) if punch_in.tzinfo else punch_in.replace(
        tzinfo=timezone.utc
    ).astimezone(IST)

    delta_seconds = (actual - scheduled).total_seconds()
    if delta_seconds <= 600:
        return 0
    return int(delta_seconds // 60)


def money_round(value: float, places: int = 2) -> float:
    from decimal import Decimal, ROUND_HALF_UP

    quantum = Decimal("1").scaleb(-places)
    return float(
        Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    )


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = (punch_out - punch_in).total_seconds()
    return money_round(seconds / 3600, 2)


def compute_overtime(
    punch_out: datetime,
    shift_end: str,
    date_str: str,
    shift_start: Optional[str] = None,
) -> int:
    day = parse_calendar_date(date_str)
    end_hour, end_minute = map(int, shift_end.split(":"))
    scheduled_end = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(
        hour=end_hour, minute=end_minute
    )

    if shift_start is not None and shift_end <= shift_start:
        scheduled_end += timedelta(days=1)

    actual = (
        punch_out.astimezone(IST)
        if punch_out.tzinfo
        else punch_out.replace(tzinfo=timezone.utc).astimezone(IST)
    )
    delta_seconds = (actual - scheduled_end).total_seconds()

    if delta_seconds < 1800:
        return 0
    return int(delta_seconds // 60)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return None

        # Reject floats, strings, booleans, and epoch seconds.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("punched_at must be an integer in epoch milliseconds.")

        if value < 100_000_000_000:
            raise ValueError("punched_at must be epoch milliseconds, not seconds.")

        try:
            datetime.fromtimestamp(value / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise ValueError("punched_at is outside the supported range.")

        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value not in {"PRESENT", "WFH", "ON_DUTY"}:
            raise ValueError("status must be PRESENT, WFH, or ON_DUTY.")
        return value




class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("punched_at must be an epoch-millisecond integer.")
        if value < 100_000_000_000:
            raise ValueError("punched_at must be milliseconds, not seconds.")
        try:
            datetime.fromtimestamp(value / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise ValueError("punched_at is outside the supported range.")
        return value


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).replace(microsecond=0)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="emp_code already exists")

    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = {}
    if department is not None:
        query["department"] = department

    total = db.employees.count_documents(query)
    skip = (page - 1) * page_size

    items = list(
        db.employees.find(query, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Use an explicitly supplied epoch-millisecond timestamp, or current UTC.
    ts = (
        datetime.fromtimestamp(body.punched_at / 1000, timezone.utc)
        if body.punched_at is not None
        else datetime.now(timezone.utc)
    )
    ts = ts.replace(microsecond=0)

    # Attendance date is based on IST, with the overnight-shift rule applied.
    local_ts = ts.astimezone(IST)
    shift_end_hour, shift_end_minute = map(int, emp["shift_end"].split(":"))
    shift_end = local_ts.replace(
        hour=shift_end_hour,
        minute=shift_end_minute,
        second=0,
        microsecond=0,
    )

    attendance_day = local_ts.date()
    if emp["shift_end"] <= emp["shift_start"] and local_ts.time().replace(tzinfo=None) < shift_end.time().replace(tzinfo=None):
        attendance_day -= timedelta(days=1)

    date_str = attendance_day.isoformat()

    doc = {
        "emp_code": body.emp_code,
        "date": date_str,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"], date_str),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Attendance already exists for this employee and date",
        )

    # Never expose MongoDB's internal _id.
    doc.pop("_id", None)
    return doc




@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    ts = (
        datetime.fromtimestamp(body.punched_at / 1000, timezone.utc)
        if body.punched_at is not None
        else datetime.now(timezone.utc)
    ).replace(microsecond=0)

    # Find the latest record that had already started by the punch-out time.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": ts},
        },
        sort=[("punch_in", -1), ("date", -1)],
    )

    if record is None:
        raise HTTPException(status_code=404, detail="No attendance record found")

    if record.get("punch_out") is not None:
        raise HTTPException(status_code=409, detail="Attendance already punched out")

    punch_in_time = record["punch_in"]
    if punch_in_time.tzinfo is None:
        punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

    if ts <= punch_in_time:
        raise HTTPException(status_code=422, detail="Punch-out must be after punch-in")

    elapsed_seconds = (ts - punch_in_time).total_seconds()
    if elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(status_code=422, detail="Punch-out cannot be more than 24 hours after punch-in")

    work_hours = compute_work_hours(punch_in_time, ts)
    overtime = compute_overtime(
        ts,
        emp["shift_end"],
        record["date"],
        emp["shift_start"],
    )
    half_day = work_hours < 4.50

    # Conditional update ensures only one concurrent punch-out can succeed.
    result = db.attendance_logs.update_one(
        {"_id": record["_id"], "punch_out": None},
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="Attendance was updated concurrently")

    updated = db.attendance_logs.find_one({"_id": record["_id"]}, {"_id": 0})
    return updated


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = {}

    if emp_code is not None:
        query["emp_code"] = emp_code

    if date_from is not None or date_to is not None:
        date_filter = {}
        if date_from is not None:
            parse_calendar_date(date_from)
            date_filter["$gte"] = date_from
        if date_to is not None:
            parse_calendar_date(date_to)
            date_filter["$lte"] = date_to
        if date_from is not None and date_to is not None and date_from > date_to:
            raise HTTPException(status_code=422, detail="date_from must not be after date_to")
        query["date"] = date_filter

    if status is not None:
        if status not in ALL_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid attendance status")
        query["status"] = status

    total = db.attendance_logs.count_documents(query)
    skip = (page - 1) * page_size

    items = list(
        db.attendance_logs.find(query, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }




class RegularizationIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    by: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def validate_patch_timestamp(cls, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Punch timestamps must be integer epoch milliseconds.")
        if value < 100_000_000_000:
            raise ValueError("Punch timestamps must be milliseconds, not seconds.")
        try:
            datetime.fromtimestamp(value / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise ValueError("Punch timestamp is outside the supported range.")
        return value

    @field_validator("status")
    @classmethod
    def validate_patch_status(cls, value):
        if value is not None and value not in ALL_STATUSES:
            raise ValueError("Invalid attendance status.")
        return value




@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizationIn,
):
    attendance_day = parse_calendar_date(date).isoformat()

    employee = db.employees.find_one({"emp_code": emp_code})
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    record = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": attendance_day}
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    supplied = body.model_fields_set
    if not supplied.intersection({"status", "punch_in", "punch_out"}):
        raise HTTPException(status_code=422, detail="No attendance changes supplied")

    old_status = record["status"]
    new_status = body.status if "status" in supplied else old_status
    if new_status not in ALL_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid attendance status")

    old_in = record.get("punch_in")
    old_out = record.get("punch_out")

    def as_utc(value):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    new_in = (
        datetime.fromtimestamp(body.punch_in / 1000, timezone.utc).replace(microsecond=0)
        if "punch_in" in supplied and body.punch_in is not None
        else as_utc(old_in)
    )
    new_out = (
        datetime.fromtimestamp(body.punch_out / 1000, timezone.utc).replace(microsecond=0)
        if "punch_out" in supplied and body.punch_out is not None
        else as_utc(old_out)
    )

    if new_status in {"ABSENT", "LEAVE"}:
        if ("punch_in" in supplied and body.punch_in is not None) or (
            "punch_out" in supplied and body.punch_out is not None
        ):
            raise HTTPException(
                status_code=422,
                detail="ABSENT and LEAVE cannot be combined with supplied punch times",
            )
        new_in = None
        new_out = None
    elif new_in is None:
        raise HTTPException(
            status_code=422,
            detail="Presence statuses require a punch_in timestamp",
        )

    if new_in is not None and ist_date(new_in).isoformat() != attendance_day:
        raise HTTPException(
            status_code=422,
            detail="punch_in must fall on the attendance date in IST",
        )

    if new_out is not None:
        if new_in is None or new_out <= new_in:
            raise HTTPException(
                status_code=422,
                detail="punch_out must be after punch_in",
            )
        if (new_out - new_in).total_seconds() > 24 * 60 * 60:
            raise HTTPException(
                status_code=422,
                detail="punch_out cannot be more than 24 hours after punch_in",
            )

    new_late = (
        compute_late_minutes(new_in, employee["shift_start"], attendance_day)
        if new_in is not None and new_status in PRESENCE_STATUSES
        else 0
    )
    new_hours = compute_work_hours(new_in, new_out) if new_in is not None and new_out is not None else None
    new_overtime = (
        compute_overtime(new_out, employee["shift_end"], attendance_day, employee["shift_start"])
        if new_out is not None
        else 0
    )
    new_half_day = new_hours < 4.50 if new_hours is not None else False

    old_values = {
        "status": old_status,
        "punch_in": as_utc(old_in),
        "punch_out": as_utc(old_out),
    }
    new_values = {
        "status": new_status,
        "punch_in": new_in,
        "punch_out": new_out,
    }

    changes = {}
    for field_name in ("status", "punch_in", "punch_out"):
        if old_values[field_name] != new_values[field_name]:
            changes[field_name] = {
                "from": (
                    int(old_values[field_name].timestamp() * 1000)
                    if field_name in {"punch_in", "punch_out"} and old_values[field_name] is not None
                    else old_values[field_name]
                ),
                "to": (
                    int(new_values[field_name].timestamp() * 1000)
                    if field_name in {"punch_in", "punch_out"} and new_values[field_name] is not None
                    else new_values[field_name]
                ),
            }

    if not changes:
        raise HTTPException(status_code=422, detail="No effective changes supplied")

    history_entry = {
        "at": now_utc(),
        "by": body.by,
        "reason": body.reason,
        "changes": changes,
    }

    # Compare the old state and history length so concurrent edits cannot
    # silently overwrite the record or its audit history.
    filter_query = {
        "_id": record["_id"],
        "status": old_status,
        "history": record.get("history", []),
        "punch_in": record.get("punch_in"),
        "punch_out": record.get("punch_out"),
    }
    update_result = db.attendance_logs.update_one(
        filter_query,
        {
            "$set": {
                "status": new_status,
                "punch_in": new_in,
                "punch_out": new_out,
                "late_minutes": new_late,
                "work_hours": new_hours,
                "overtime_minutes": new_overtime,
                "half_day": new_half_day,
            },
            "$push": {"history": history_entry},
        },
    )

    if update_result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Attendance changed concurrently; reload and retry",
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]},
        {"_id": 0},
    )

    # Convert timestamps to epoch milliseconds in the API response.
    for field_name in ("punch_in", "punch_out"):
        value = updated.get(field_name)
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            updated[field_name] = int(value.timestamp() * 1000)

    for entry in updated.get("history", []):
        value = entry.get("at")
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            entry["at"] = int(value.timestamp() * 1000)

    return updated


# --------------------------------------------------------------------------- #
@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(
    emp_code: str,
    month: str = Query(..., description="Month in YYYY-MM format"),
):
    import re
    from calendar import monthrange
    from decimal import Decimal, ROUND_HALF_UP

    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(status_code=422, detail="month must use YYYY-MM format")

    try:
        year, month_number = map(int, month.split('-'))
        month_start = date(year, month_number, 1)
        month_end = date(year, month_number, monthrange(year, month_number)[1])
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    employee = db.employees.find_one({"emp_code": emp_code}, {"_id": 0})
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    joined_on = parse_calendar_date(employee["joined_on"])
    first_working_date = max(joined_on, month_start)
    working_days = 0
    current_day = first_working_date
    while current_day <= month_end:
        if current_day.weekday() < 5:
            working_days += 1
        current_day += timedelta(days=1)

    records = list(db.attendance_logs.find(
        {"emp_code": emp_code, "date": {"$gte": month_start.isoformat(), "$lte": month_end.isoformat()}},
        {"_id": 0, "date": 1, "status": 1, "half_day": 1, "late_minutes": 1},
    ))

    present_days = Decimal("0")
    leave_days = 0
    late_count = 0
    for record in records:
        status = record.get("status")
        if status in PRESENCE_STATUSES:
            record_date = parse_calendar_date(record["date"])
            if record_date.weekday() < 5:
                present_days += Decimal("0.5") if record.get("half_day") is True else Decimal("1")
        if status == "LEAVE":
            leave_days += 1
        if record.get("late_minutes", 0) > 0:
            late_count += 1

    attendance_pct = None
    if working_days > 0:
        attendance_pct = float((present_days * Decimal("100") / Decimal(working_days)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    return {
        "emp_code": emp_code,
        "name": employee["name"],
        "department": employee["department"],
        "month": month,
        "working_days": working_days,
        "present_days": float(present_days),
        "leave_days": leave_days,
        "late_count": late_count,
        "attendance_pct": attendance_pct,
    }



@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., description="Month in YYYY-MM format"),
    department: Optional[str] = None,
):
    import re
    from calendar import monthrange
    from decimal import Decimal, ROUND_HALF_UP

    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(status_code=422, detail="month must use YYYY-MM format")

    try:
        year, month_number = map(int, month.split("-"))
        month_start = date(year, month_number, 1)
        month_end = date(year, month_number, monthrange(year, month_number)[1])
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    employee_match = {"joined_on": {"$lte": month_end.isoformat()}}
    if department is not None:
        employee_match["department"] = department

    # Headcount includes employees who have no attendance records.
    employee_counts = list(db.employees.aggregate([
        {"$match": employee_match},
        {"$group": {"_id": "$department", "headcount": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]))

    # Aggregate monthly attendance and join employee details.
    attendance_match = {
        "date": {
            "$gte": month_start.isoformat(),
            "$lte": month_end.isoformat(),
        }
    }
    if department is not None:
        attendance_pipeline = [
            {"$match": attendance_match},
            {"$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }},
            {"$unwind": "$employee"},
            {"$match": {"employee.department": department}},
        ]
    else:
        attendance_pipeline = [
            {"$match": attendance_match},
            {"$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }},
            {"$unwind": "$employee"},
        ]

    attendance_pipeline += [
        {"$match": {"employee.joined_on": {"$lte": month_end.isoformat()}}},
        {"$addFields": {
            "_weekday": {
                "$dayOfWeek": {
                    "$dateFromString": {"dateString": "$date"}
                }
            }
        }},
        {"$group": {
            "_id": "$employee.department",
            "present_days": {"$sum": {
                "$cond": [
                    {"$and": [
                        {"$in": ["$status", list(PRESENCE_STATUSES)]},
                        {"$gte": ["$_weekday", 2]},
                        {"$lte": ["$_weekday", 6]},
                    ]},
                    {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                    0,
                ]
            }},
            "avg_work_hours": {"$avg": {
                "$cond": [
                    {"$and": [
                        {"$in": ["$status", list(PRESENCE_STATUSES)]},
                        {"$ne": ["$work_hours", None]},
                    ]},
                    "$work_hours",
                    None,
                ]
            }},
            "late_count": {"$sum": {
                "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
            }},
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "leave_count": {"$sum": {
                "$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]
            }},
            "on_duty_count": {"$sum": {
                "$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]
            }},
        }},
    ]

    stats_by_department = {
        item["_id"]: item
        for item in db.attendance_logs.aggregate(attendance_pipeline)
    }

    output = []
    for item in employee_counts:
        dept = item["_id"]
        stats = stats_by_department.get(dept, {})
        average = stats.get("avg_work_hours")

        if average is not None:
            average = float(Decimal(str(average)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ))

        present_days = float(Decimal(str(stats.get("present_days", 0))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ))

        output.append({
            "department": dept,
            "headcount": item["headcount"],
            "present_days": present_days,
            "avg_work_hours": average,
            "late_count": stats.get("late_count", 0),
            "total_late_minutes": stats.get("total_late_minutes", 0),
            "leave_count": stats.get("leave_count", 0),
            "on_duty_count": stats.get("on_duty_count", 0),
        })

    return output



@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., description="Month in YYYY-MM format"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
):
    import re
    from calendar import monthrange

    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(status_code=422, detail="month must use YYYY-MM format")

    try:
        year, month_number = map(int, month.split("-"))
        month_start = date(year, month_number, 1)
        month_end = date(year, month_number, monthrange(year, month_number)[1])
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    pipeline = [
        {"$match": {
            "date": {
                "$gte": month_start.isoformat(),
                "$lte": month_end.isoformat(),
            },
            "late_minutes": {"$gt": 0},
        }},
        {"$group": {
            "_id": "$emp_code",
            "total_late_minutes": {"$sum": "$late_minutes"},
            "late_count": {"$sum": 1},
        }},
        {"$lookup": {
            "from": "employees",
            "localField": "_id",
            "foreignField": "emp_code",
            "as": "employee",
        }},
        {"$unwind": "$employee"},
    ]

    if department is not None:
        pipeline.append({"$match": {"employee.department": department}})

    pipeline += [
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$setWindowFields": {
            "sortBy": {"total_late_minutes": -1},
            "output": {
                "rank": {"$rank": {}},
            },
        }},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$project": {
            "_id": 0,
            "emp_code": "$_id",
            "name": "$employee.name",
            "department": "$employee.department",
            "total_late_minutes": 1,
            "late_count": 1,
            "rank": 1,
        }},
    ]

    return list(db.attendance_logs.aggregate(pipeline))



@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    import re
    from decimal import Decimal, ROUND_HALF_UP

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", from_date):
        raise HTTPException(status_code=422, detail="'from' must use YYYY-MM-DD format")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", to_date):
        raise HTTPException(status_code=422, detail="'to' must use YYYY-MM-DD format")

    try:
        start_date = parse_calendar_date(from_date)
        end_date = parse_calendar_date(to_date)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid calendar date")

    if start_date > end_date:
        raise HTTPException(status_code=422, detail="'from' must be on or before 'to'")

    total_days = (end_date - start_date).days + 1
    if total_days > 92:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 92 days")

    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(status_code=404, detail="Department not found")

    date_strings = []
    current_date = start_date
    while current_date <= end_date:
        date_strings.append(current_date.isoformat())
        current_date += timedelta(days=1)

    attendance_pipeline = [
        {"$match": {
            "date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}
        }},
        {"$lookup": {
            "from": "employees",
            "localField": "emp_code",
            "foreignField": "emp_code",
            "as": "employee",
        }},
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department}},
        {"$group": {
            "_id": "$date",
            "present_count": {"$sum": {
                "$cond": [
                    {"$in": ["$status", list(PRESENCE_STATUSES)]},
                    {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                    0,
                ]
            }},
            "late_count": {"$sum": {
                "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
            }},
        }},
    ]
    attendance_by_date = {
        item["_id"]: item
        for item in db.attendance_logs.aggregate(attendance_pipeline)
    }

    employees = list(db.employees.find(
        {
            "department": department,
            "joined_on": {"$lte": end_date.isoformat()},
        },
        {"_id": 0, "joined_on": 1},
    ))

    rows = []
    for date_string in date_strings:
        day = parse_calendar_date(date_string)
        headcount = sum(
            1 for employee in employees
            if employee["joined_on"] <= date_string
        )
        stats = attendance_by_date.get(date_string, {})
        present_count = float(stats.get("present_count", 0))
        late_count = stats.get("late_count", 0)
        working_day = day.weekday() < 5

        if not working_day or headcount == 0:
            attendance_rate = None
        else:
            attendance_rate = float(
                (Decimal(str(present_count)) * Decimal("100") / Decimal(headcount))
                .quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            )

        rows.append({
            "date": date_string,
            "working_day": working_day,
            "headcount": headcount,
            "present_count": present_count,
            "late_count": late_count,
            "attendance_rate": attendance_rate,
            "moving_avg_7d": None,
        })

    # Average the non-null attendance rates in the current row and
    # previous six rows, within the requested date range only.
    for index, row in enumerate(rows):
        rates = [
            item["attendance_rate"]
            for item in rows[max(0, index - 6):index + 1]
            if item["attendance_rate"] is not None
        ]
        if rates:
            row["moving_avg_7d"] = float(
                (sum(Decimal(str(rate)) for rate in rates) / Decimal(len(rates)))
                .quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            )

    return rows



@app.get("/admin/explain/{endpoint}")
def admin_explain(
    endpoint: str,
    month: Optional[str] = None,
    emp_code: Optional[str] = None,
    department: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: int = Query(10, ge=1, le=50),
):
    import re
    from calendar import monthrange

    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }
    if endpoint not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported explain endpoint")

    def parse_month(value):
        if value is None or not re.fullmatch(r"\d{4}-\d{2}", value):
            raise HTTPException(status_code=422, detail="month must use YYYY-MM format")
        try:
            year, month_num = map(int, value.split("-"))
            first = date(year, month_num, 1)
            last = date(year, month_num, monthrange(year, month_num)[1])
            return first, last
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid month")

    if endpoint == "attendance_list":
        query = {}
        if emp_code is not None:
            query["emp_code"] = emp_code
        if date_from is not None or date_to is not None:
            date_filter = {}
            if date_from is not None:
                parse_calendar_date(date_from)
                date_filter["$gte"] = date_from
            if date_to is not None:
                parse_calendar_date(date_to)
                date_filter["$lte"] = date_to
            if date_from and date_to and date_from > date_to:
                raise HTTPException(status_code=422, detail="date_from must not be after date_to")
            query["date"] = date_filter
        if status is not None:
            if status not in ALL_STATUSES:
                raise HTTPException(status_code=422, detail="Invalid status")
            query["status"] = status
        collection = db.attendance_logs
        explain_command = {
            "find": collection.name,
            "filter": query,
            "sort": {"date": -1, "emp_code": 1},
            "skip": (page - 1) * page_size,
            "limit": page_size,
        }

    elif endpoint == "employee_monthly":
        if not emp_code:
            raise HTTPException(status_code=422, detail="emp_code is required")
        first, last = parse_month(month)
        collection = db.attendance_logs
        explain_command = {
            "aggregate": collection.name,
            "pipeline": [
                {"$match": {
                    "emp_code": emp_code,
                    "date": {"$gte": first.isoformat(), "$lte": last.isoformat()},
                }},
                {"$sort": {"date": 1}},
            ],
            "cursor": {},
        }

        employee_collection = db.employees
        employee_explain_command = {
            "find": employee_collection.name,
            "filter": {"emp_code": emp_code},
            "projection": {"_id": 0},
        }

    elif endpoint == "department_summary":
        first, last = parse_month(month)

        collection = db.employees
        employee_filter = {"joined_on": {"$lte": last.isoformat()}}
        if department is not None:
            employee_filter["department"] = department

        explain_command = {
            "aggregate": collection.name,
            "pipeline": [
                {"$match": employee_filter},
                {"$group": {
                    "_id": "$department",
                    "headcount": {"$sum": 1},
                }},
                {"$sort": {"_id": 1}},
            ],
            "cursor": {},
        }

        attendance_collection = db.attendance_logs
        attendance_match = {
            "date": {
                "$gte": first.isoformat(),
                "$lte": last.isoformat(),
            }
        }

        attendance_pipeline = [{"$match": attendance_match}]
        attendance_pipeline.append({
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }
        })
        attendance_pipeline.append({"$unwind": "$employee"})

        if department is not None:
            attendance_pipeline.append({
                "$match": {"employee.department": department}
            })

        attendance_pipeline.append({
            "$match": {"employee.joined_on": {"$lte": last.isoformat()}}
        })

        attendance_pipeline.extend([
            {"$addFields": {
                "_weekday": {
                    "$dayOfWeek": {
                        "$dateFromString": {"dateString": "$date"}
                    }
                }
            }},
            {"$group": {
                "_id": "$employee.department",
                "present_days": {"$sum": {
                    "$cond": [
                        {"$and": [
                            {"$in": ["$status", list(PRESENCE_STATUSES)]},
                            {"$gte": ["$_weekday", 2]},
                            {"$lte": ["$_weekday", 6]},
                        ]},
                        {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                        0,
                    ]
                }},
                "avg_work_hours": {"$avg": {
                    "$cond": [
                        {"$and": [
                            {"$in": ["$status", list(PRESENCE_STATUSES)]},
                            {"$ne": ["$work_hours", None]},
                        ]},
                        "$work_hours",
                        None,
                    ]
                }},
                "late_count": {"$sum": {
                    "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                }},
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "leave_count": {"$sum": {
                    "$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]
                }},
                "on_duty_count": {"$sum": {
                    "$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]
                }},
            }},
            {"$sort": {"_id": 1}},
        ])

        attendance_explain_command = {
            "aggregate": attendance_collection.name,
            "pipeline": attendance_pipeline,
            "cursor": {},
        }

    elif endpoint == "late_leaderboard":
        first, last = parse_month(month)
        pipeline = [
            {"$match": {
                "date": {"$gte": first.isoformat(), "$lte": last.isoformat()},
                "late_minutes": {"$gt": 0},
            }},
            {"$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }},
            {"$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }},
            {"$unwind": "$employee"},
        ]

        if department is not None:
            pipeline.append({"$match": {"employee.department": department}})

        pipeline += [
            {"$sort": {"total_late_minutes": -1, "_id": 1}},
            {"$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {"rank": {"$rank": {}}},
            }},
            {"$match": {"rank": {"$lte": limit}}},
            {"$sort": {"total_late_minutes": -1, "_id": 1}},
            {"$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1,
                "rank": 1,
            }},
        ]

        collection = db.attendance_logs
        explain_command = {
            "aggregate": collection.name,
            "pipeline": pipeline,
            "cursor": {},
        }

    else:  # department_trend
        if not department:
            raise HTTPException(status_code=422, detail="department is required")
        if not from_date or not to_date:
            raise HTTPException(status_code=422, detail="'from' and 'to' are required")
        start_date = parse_calendar_date(from_date)
        end_date = parse_calendar_date(to_date)
        if start_date > end_date:
            raise HTTPException(status_code=422, detail="'from' must be on or before 'to'")
        if (end_date - start_date).days + 1 > 92:
            raise HTTPException(status_code=422, detail="Date range cannot exceed 92 days")
        collection = db.attendance_logs
        explain_command = {
            "aggregate": collection.name,
            "pipeline": [
                {"$match": {
                    "date": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}
                }},
                {"$lookup": {
                    "from": "employees",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "employee",
                }},
                {"$unwind": "$employee"},
                {"$match": {"employee.department": department}},
                {"$group": {
                    "_id": "$date",
                    "present_count": {"$sum": {
                        "$cond": [
                            {"$in": ["$status", list(PRESENCE_STATUSES)]},
                            {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                            0,
                        ]
                    }},
                    "late_count": {"$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }},
                }},
            ],
            "cursor": {},
        }

        employee_collection = db.employees
        employee_explain_command = {
            "find": employee_collection.name,
            "filter": {
                "department": department,
                "joined_on": {"$lte": end_date.isoformat()},
            },
            "projection": {"_id": 0, "joined_on": 1},
        }

    try:
        explained = db.command({
            "explain": explain_command,
            "verbosity": "executionStats",
        })
        attendance_explained = None
        employee_explained = None

        if endpoint == "department_summary":
            attendance_explained = db.command({
                "explain": attendance_explain_command,
                "verbosity": "executionStats",
            })

        if endpoint in {"employee_monthly", "department_trend"}:
            employee_explained = db.command({
                "explain": employee_explain_command,
                "verbosity": "executionStats",
            })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Explain failed: {type(exc).__name__}")

    # MongoDB explain output can contain BSON Timestamp and other BSON types.
    # Convert them to JSON-safe Extended JSON before FastAPI serializes the response.
    from bson.json_util import dumps as bson_dumps
    import json

    return json.loads(bson_dumps({
        "endpoint": endpoint,
        "collection": collection.name,
        "explain": explained,
        **(
            {"attendance_explain": attendance_explained}
            if attendance_explained is not None else {}
        ),
        **(
            {"employee_explain": employee_explained}
            if employee_explained is not None else {}
        ),
    }))


# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #


def ensure_indexes():
    """Create core indexes safely; repeated calls are idempotent."""
    db.employees.create_index(
        [("emp_code", 1)], unique=True, name="uq_employee_emp_code"
    )
    db.employees.create_index(
        [("department", 1), ("emp_code", 1)],
        name="ix_employee_department_code"
    )
    db.employees.create_index(
        [("joined_on", 1)], name="ix_employee_joined_on"
    )
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True, name="uq_attendance_employee_date"
    )
    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="ix_attendance_date_code"
    )
    db.attendance_logs.create_index(
        [("status", 1), ("date", -1), ("emp_code", 1)],
        name="ix_attendance_status_date_code"
    )


@app.on_event("startup")
def initialize_database():
    ensure_indexes()
