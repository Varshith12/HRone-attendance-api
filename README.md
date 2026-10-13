# Employee Attendance & Analytics API

A REST API built with FastAPI and MongoDB for employee management, attendance tracking, attendance regularization, and analytics.

## Technology stack

- Python 3.11+
- FastAPI and Pydantic
- PyMongo
- MongoDB 6.0+
- Uvicorn

## Features

- Create employees and list employees with department filtering and pagination.
- Record punch-in and punch-out events, including overnight shifts.
- List attendance records with filters and pagination.
- Regularize attendance with validation and an audit history.
- Generate monthly employee attendance analytics.
- Generate department summaries, late-arrival leaderboards, and daily department trends.
- Inspect MongoDB query plans through administrative explain endpoints.
- Create required MongoDB indexes safely and idempotently.

## Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
```

On Windows:

```powershell
.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure these environment variables in your local environment:

- `MONGO_URI`: your MongoDB connection string
- `MONGO_DB`: database name, for example `attendance_db`

Do not commit credentials, connection strings, or `.env` files. MongoDB Atlas or a local MongoDB instance can be used.

## Run the API

From the repository root:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open the interactive API documentation at `http://127.0.0.1:8000/docs`.

The health endpoint is available at `/health`.

## Sample data

The `sample_data/` directory contains example employee and attendance documents. Review `sample_seed.py` before loading sample records into a database; avoid loading them into a database containing records you need to preserve.

## Tests and implementation notes

The `tests/` directory contains project tests. Run them with:

```bash
pytest -q
```

The application and query behavior should be verified against the provided `openapi.yaml` contract before submission.

## Repository contents

- `app/main.py` — API implementation
- `requirements.txt` — Python dependencies
- `openapi.yaml` — API contract
- `DATA_MODEL.md` — MongoDB data model
- `sample_data/` and `sample_seed.py` — sample records and seeding utility
- `REVIEW.md` — starter defect review and verification evidence
- `DECISIONS.md` — design decisions and trade-offs

## Submission hygiene

Never commit MongoDB credentials, `.env` files, virtual environments, or local development backups.
