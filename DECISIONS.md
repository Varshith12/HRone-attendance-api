# DECISIONS.md

1. **Indexes.** A unique `emp_code` index protects employee identity, and `(department, emp_code)` supports department filtering and ordered employee lists. The `joined_on` index supports employee eligibility and headcount queries. A unique `(emp_code, date)` attendance index prevents duplicate daily records and supports employee/date lookup. `(date, emp_code)` supports date filtering and stable attendance ordering; `(status, date, emp_code)` supports status-filtered queries. I would avoid adding overlapping indexes without measuring their benefit because every index increases write and storage costs.

2. **Punch-in race.** Two identical requests may both pass an initial lookup, so that lookup cannot guarantee uniqueness. The unique compound attendance index is the final authority: one insert succeeds, and the other receives a duplicate-key error that the API translates to HTTP 409. This keeps correctness in MongoDB rather than relying on application timing.

3. **Ties.** The leaderboard uses competition ranking. Employees tied at the cutoff share the same rank, and all employees whose rank is within the requested limit are returned. Results are then ordered by total late minutes descending and employee code ascending for deterministic output.

4. **Headcount.** Department summary aggregates eligible employees separately from attendance logs. Therefore, an employee who has joined by month-end is counted even if they have no attendance records.

5. **At 100x scale.** I would benchmark representative large datasets, inspect execution statistics, and tune indexes using measured query plans before adding infrastructure or caching.
