# SunshineBot

Base URL: https://sunshine.vanshraja.me

Endpoints (IST-aware, Google Calendar is source of truth; SQLite cache syncs every minute):

| Endpoint | Method | Parameters | Returns |
|---------|--------|------------|---------|
| /health | GET | - | { success, resource_found:true, message, data:{ status, service, version } } |
| / | GET | - | { success, resource_found:true, message, data:{ endpoints, docs } } |
| /webhook/create_appointment | POST | body: { specialty, patient_name, patient_phone, date, time, reason? } | 200: { success, resource_found:true, message, data:{ id, doctor, patient_name, specialty, date, time, duration_minutes, calendar_link } }; 200 (slot busy/outside hours): { success:false, resource_found:true, message, data:null } |
| /api/appointments/by-phone | GET | query: phone | { success, resource_found, message, data:{ phone, appointments[], total } } |
| /api/specialties | GET | - | { success, resource_found:true, message, data:{ specialties, total_specialties } } |
| /api/patients | POST | body: { patient_phone, patient_name } | { success, resource_found:true, message, data:{ patient_phone, name } } |
| /api/patients/<phone> | GET | path: phone | 200 with data if exists, or { success:true, resource_found:false, message, data:null } |
| /api/debug/db | GET | query: limit? | { success, resource_found:true, message, data:{ last_sync_at_utc, counts, doctors[], patients[], appointments[] (start_ist/end_ist) } } |
| /admin/db-viewer | GET | query: limit? | HTML viewer |

Notes
- Times displayed are IST; UTC used internally.
- DB initializes and syncs on startup; background sync every 60s.
- Persistent DB: Postgres. Env vars: PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB.

CLI tester
- Run `python cli.py` to interactively test endpoints.
