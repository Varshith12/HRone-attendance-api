# REVIEW.md

## Starter defects and corrections

| # | Where in starter | Defect | How to detect it | Correction in final implementation |
|---|---|---|---|---|
| 1 | MongoClient configuration, lines 20–23 | A missing MongoDB URI silently falls back to localhost, and the database connection is not verified during health checks. | Unset the URI or make MongoDB unavailable and call `/health`. | Require configuration and make health check the database with a ping, returning an error when the database is unavailable. |
| 2 | `compute_late_minutes`, lines 33–38 | The calculation does not explicitly implement the required strict 10-minute threshold and whole-minute flooring. | Test arrivals at the threshold and immediately after it. | Apply the specified threshold and minute-flooring rule. |
| 3 | `compute_work_hours`, line 41 | Built-in `round` does not guarantee the specified decimal half-up rounding. | Test durations at rounding boundaries. | Use explicit decimal half-up rounding. |
| 4 | `compute_overtime`, lines 44–47 | The calculation does not implement the required 30-minute overtime threshold and does not correctly model overnight shifts. | Test the scheduled end boundary and an overnight shift. | Calculate the scheduled end for the correct shift date and apply the specified overtime threshold. |
| 5 | `EmployeeIn`, lines 53–60 | Fields use unrestricted strings; shift formats, dates, and business constraints are not adequately validated. | Submit malformed dates, shifts, or invalid field values. | Add request validation for the contract's accepted formats and constraints. |
| 6 | `health`, lines 72–74 | Always returns success without checking MongoDB. | Stop or disconnect MongoDB and call `/health`. | Ping MongoDB and return success only when the check passes. |
| 7 | `create_employee`, lines 77–85 | A read-before-insert duplicate check is vulnerable to concurrent requests; `datetime.now()` is naive. | Submit simultaneous requests with the same employee code. | Enforce uniqueness with a database index, handle duplicate-key errors, and use UTC timestamps. |
| 8 | `list_employees`, lines 88–96 | `skip = page * page_size` skips page one, and `total` counts every employee instead of the filtered query. There is no page-size validation or deterministic sort. | Compare page one with the first records; filter by department and compare total. | Validate pagination, count the filtered query, and sort by employee code before pagination. |
| 9 | `punch_in`, lines 99–121 | Unknown employees can cause a crash; falsey timestamp checks reject valid zero-like inputs inconsistently; local time is used; duplicate detection is race-prone; the response exposes an internal inserted ID. | Submit an unknown employee, boundary timestamps, duplicate simultaneous punches, and inspect the response. | Validate the employee and timestamp, use IST/UTC rules, enforce the unique attendance key, and avoid exposing MongoDB `_id`. |
| 10 | `list_attendance`, lines 124–150 | Fetches all matching records into Python, sorts and paginates in memory, does not validate pagination or dates, omits a stable secondary sort, and exposes internal IDs. | Query a large collection and compare pagination, ordering, and response fields. | Apply filters, count, sort, skip, limit, and projection in MongoDB; validate inputs and omit `_id`. |
| 11 | Remaining contract, lines 153–161 | Punch-out, regularization, analytics, and explain endpoints are absent from the starter. | Compare the registered routes with `openapi.yaml`. | Implement the missing routes and validate them against the contract. |

## Reviewed, not automatically treated as defects

- A unique compound index on `(emp_code, date)` is appropriate for enforcing one attendance record per employee per attendance date.
- The API uses MongoDB for persistent records; the correction is to move filtering, sorting, and pagination into database queries, not to remove MongoDB.
- Weekend attendance records can still matter for late-arrival and overtime metrics even though attendance percentages use weekdays.
- A leaderboard cutoff should include employees tied at the limit when competition ranking is required.

## Verification evidence

The development session exercised employee pagination, punch-in/punch-out validation, regularization, monthly analytics, department summary, leaderboard ties, trend calculations, and administrative explain responses. The consolidated explain test returned HTTP 200 for all five explain endpoint types; tested plans contained `IXSCAN` and no `COLLSCAN`. Invalid month and status inputs returned HTTP 422.

These results describe the tests run during development; they are not a claim that every possible input or the evaluator's large dataset has been tested.
