# SunshineBot — AI voice assistant for hospital appointments

AI voice bot + Flask API that books, reschedules, and cancels hospital visits. Google Calendar is the source of truth; SQLite/Postgres cache stays in sync every minute for fast lookups and conflict checks.

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Testing / CLI](#testing--cli)
- [License](#license)

## Overview
- AI voice assistant (ElevenLabs webhook) + REST API for hospital appointment booking.
- Enforces IST working hours, doctor-specific availability, and conflict-free slots via Google Calendar.
- Keeps a local SQLite/Postgres cache in sync every 60s for low-latency reads and offline resilience.

## Features
- Appointment lifecycle: create, reschedule, cancel; returns Calendar links and event IDs.
- Doctor availability + conflict checks (IST) with per-doctor working hours and slot duration.
- Patient identity by phone; full appointment history (past/future/cancelled/completed).
- Background sync: Google Calendar ↔ SQLite/Postgres every minute; startup bootstrap.
- Ops visibility: HTML DB viewer and JSON snapshot with IST/UTC projections.

## Architecture
```
Caller / ElevenLabs --> /webhook/create_appointment --> Flask API
Flask API <--> Google Calendar (source of truth)
Flask API <--> SQLite cache / Postgres (Railway)
Google Calendar <--> SQLite cache  (background sync ~60s)
Flask API --> Admin DB viewer (HTML)
Flask API --> Debug snapshot (JSON)
```

## Tech Stack
- Python, Flask, Waitress (WSGI)
- Google Calendar API with service-account OAuth
- SQLite (local cache) / Postgres (Railway)
- ZoneInfo for IST/UTC handling, threading for background sync
- dotenv for config, curl/CLI harnesses for testing

## Quick Start
1) Prereqs: Python 3.11+, Google service account JSON, Calendar ID; optional Postgres for persistence (Railway).  
2) Env:  
```bash
export SERVICE_ACCOUNT_JSON='…'   # or mount credentials.json
export CALENDAR_ID='your_calendar_id'
# optional overrides
export DB_PATH='sunshine.db'
# Postgres (if used): PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB
```
3) Install & run:  
```bash
pip install -r requirements.txt
python app.py   # uses Waitress if available, otherwise Flask dev server
```
4) Optional demo/seed: `python seed_demo_via_api.py` or `./seed_demo_via_curl.sh`

## API Endpoints (IST-aware)
| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness/version |
| `/` | GET | Service info + endpoint list |
| `/webhook/create_appointment` | POST | Book appointment (specialty, patient_name, patient_phone, date, time, reason?) |
| `/api/appointments/by-phone` | GET | All appointments for a phone (all statuses/times) |
| `/api/appointments/manage` | POST | Delete/reschedule by event_id (validates hours/conflicts) |
| `/api/availability/doctor` | GET | Available HH:MM slots for a doctor on a date |
| `/api/specialties` | GET | List specialties and doctors |
| `/api/patients` | POST | Upsert patient (phone, name) |
| `/api/patients/<phone>` | GET | Fetch patient |
| `/api/debug/db` | GET | JSON snapshot with counts and IST/UTC views |
| `/admin/db-viewer` | GET | HTML viewer for doctors/patients/appointments |

## Configuration
- Required: `SERVICE_ACCOUNT_JSON` (or `credentials.json` file), `CALENDAR_ID`
- Optional: `DB_PATH` (SQLite path) or Postgres vars (`PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DB`)
- Time zone: assumes Asia/Kolkata (IST) for scheduling and validation.
- Background sync: runs every 60s; forced sync on startup.

## Testing / CLI
- Interactive tester: `python cli.py`
- Smoke tests: `pytest test_calendar.py` (where applicable)

## License
This project is licensed under the [MIT License](LICENSE).
