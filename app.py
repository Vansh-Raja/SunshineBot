from flask import Flask, request, jsonify
from datetime import datetime, timedelta, timezone
from functions import (
    calendar_service,
    CALENDAR_ID,
    DOCTORS,
    WORKING_HOURS_START,
    WORKING_HOURS_END,
    SLOT_DURATION,
    parse_datetime,
    get_events_in_range,
    is_slot_available,
    get_available_slots,
    find_event_by_id,
    find_events_by_patient_phone,
    assign_doctor,
    create_appointment_logic,
    get_db_snapshot,
    init_db,
    sync_if_stale,
    upsert_patient,
    get_patient_by_phone,
    get_upcoming_appointments_by_phone,
    get_patient_appointments_by_phone,
    get_db,
    get_doctor_availability_slots,
)

app = Flask(__name__)

# Ensure SQLite exists and force a fresh sync on startup (Railway is ephemeral)
try:
    init_db()
    # Force immediate sync on boot so debug endpoints and checks have data
    sync_if_stale(max_age_seconds=0)
except Exception as _e:
    # Non-fatal for boot; endpoints can still attempt sync lazily
    print(f"Startup DB init/sync warning: {_e}")

# Background sync every 60 seconds (best-effort)
import threading
import time

def _background_sync_loop():
    while True:
        try:
            sync_if_stale(max_age_seconds=0)
        except Exception as _e:
            print(f"Background sync error: {_e}")
        time.sleep(60)

threading.Thread(target=_background_sync_loop, daemon=True).start()

# All configuration, calendar client, and helper functions are imported from functions.py

# ============================================
# ELEVENLABS WEBHOOK: CREATE APPOINTMENT (single MVP endpoint)
# ============================================

@app.route('/webhook/create_appointment', methods=['POST'])
def webhook_create_appointment():
    """
    ElevenLabs webhook: Create appointment
    """
    data = request.json or {}
    payload, status = create_appointment_logic(data)
    return jsonify(payload), status

# ============================================
# GET APPOINTMENTS BY PHONE (ALL STATUSES/TIMES)
# ============================================

@app.route('/api/appointments/by-phone', methods=['GET'])
def appointments_by_phone():
    try:
        phone = request.args.get('phone')
        if not phone:
            return jsonify({'success': False, 'resource_found': False, 'message': 'phone is required', 'data': None}), 400
        # Return all appointments for LLM-side filtering (past/future/cancelled/completed)
        appts = get_patient_appointments_by_phone(phone)
        # Add event_id alias for external_id for client convenience
        for a in appts:
            if isinstance(a, dict) and 'external_id' in a:
                a['event_id'] = a.get('external_id')
        found = len(appts) > 0
        return jsonify({'success': True, 'resource_found': found, 'message': 'Appointments fetched', 'data': {'phone': phone, 'appointments': appts, 'total': len(appts)}}), 200
    except Exception as e:
        return jsonify({'success': False, 'resource_found': False, 'message': str(e), 'data': None}), 500

# ============================================
# MANAGE APPOINTMENT: delete or reschedule by event_id
# ============================================

@app.route('/api/appointments/manage', methods=['POST'])
def manage_appointment():
    try:
        data = request.json or {}
        action = (data.get('action') or '').strip().lower()
        event_id = data.get('event_id') or data.get('id') or data.get('external_id')
        if not event_id or action not in {'delete', 'reschedule'}:
            return jsonify({'success': False, 'resource_found': False, 'message': 'event_id and valid action (delete|reschedule) are required', 'data': None}), 400

        init_db()

        if action == 'delete':
            try:
                calendar_service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
            except Exception as _e:
                # If already deleted on Google, continue to update local DB
                pass
            try:
                conn = get_db()
                conn.execute("UPDATE appointments SET status='cancelled', updated_at_utc=datetime('now') WHERE external_id=?", (event_id,))
                conn.commit()
                conn.close()
            except Exception as _e:
                # Non-fatal for API success as long as calendar deletion succeeded
                pass
            return jsonify({'success': True, 'resource_found': True, 'message': 'Appointment deleted', 'data': {'event_id': event_id}}), 200

        # reschedule
        new_date = data.get('new_date') or data.get('date')
        new_time = data.get('new_time') or data.get('time')
        if not new_date or not new_time:
            return jsonify({'success': False, 'resource_found': True, 'message': 'new_date and new_time are required for reschedule', 'data': None}), 400

        # Working hours check in IST
        start_dt_local = parse_datetime(new_date, new_time)
        end_dt_local = start_dt_local + timedelta(minutes=SLOT_DURATION)
        if start_dt_local.hour < WORKING_HOURS_START or end_dt_local.hour > WORKING_HOURS_END:
            return jsonify({'success': False, 'resource_found': True, 'message': 'Requested time is outside working hours', 'data': None}), 200

        # Fetch appointment doctor_id for conflict check
        doctor_id = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT doctor_id FROM appointments WHERE external_id=?', (event_id,))
            row = cur.fetchone()
            doctor_id = row['doctor_id'] if row else None
            conn.close()
        except Exception:
            doctor_id = None

        # Conflict check against other confirmed appts for same doctor
        if doctor_id is not None:
            try:
                conn = get_db()
                cur = conn.cursor()
                start_ts_utc = start_dt_local.astimezone(timezone.utc).isoformat()
                end_ts_utc = end_dt_local.astimezone(timezone.utc).isoformat()
                cur.execute(
                    '''SELECT 1 FROM appointments
                       WHERE doctor_id=? AND status='confirmed' AND external_id != ?
                         AND NOT (end_ts_utc <= ? OR start_ts_utc >= ?)
                       LIMIT 1''',
                    (doctor_id, event_id, start_ts_utc, end_ts_utc)
                )
                conflict = cur.fetchone() is not None
                conn.close()
                if conflict:
                    return jsonify({'success': False, 'resource_found': True, 'message': 'Time slot not available', 'data': None}), 200
            except Exception:
                # If conflict check fails, proceed without blocking in MVP
                pass

        # Update on Google Calendar
        try:
            update_body = {
                'start': {'dateTime': start_dt_local.isoformat(), 'timeZone': 'Asia/Kolkata'},
                'end': {'dateTime': end_dt_local.isoformat(), 'timeZone': 'Asia/Kolkata'},
            }
            calendar_service.events().patch(calendarId=CALENDAR_ID, eventId=event_id, body=update_body).execute()
        except Exception as e:
            return jsonify({'success': False, 'resource_found': True, 'message': f'Calendar update failed: {e}', 'data': None}), 500

        # Update local DB
        try:
            conn = get_db()
            conn.execute(
                "UPDATE appointments SET start_ts_utc=?, end_ts_utc=?, updated_at_utc=datetime('now') WHERE external_id=?",
                (
                    start_dt_local.astimezone(timezone.utc).isoformat(),
                    end_dt_local.astimezone(timezone.utc).isoformat(),
                    event_id,
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        return jsonify({'success': True, 'resource_found': True, 'message': 'Appointment rescheduled', 'data': {'event_id': event_id, 'date': new_date, 'time': new_time}}), 200
    except Exception as e:
        return jsonify({'success': False, 'resource_found': False, 'message': str(e), 'data': None}), 500

# ============================================
# DOCTOR AVAILABILITY BY DAY
# ============================================

@app.route('/api/availability/doctor', methods=['GET'])
def availability_by_doctor():
    try:
        doctor_id = request.args.get('doctor_id')
        date = request.args.get('date')  # YYYY-MM-DD
        if not doctor_id or not date:
            return jsonify({'success': False, 'resource_found': False, 'message': 'doctor_id and date are required', 'data': None}), 400
        try:
            doctor_id_int = int(doctor_id)
        except ValueError:
            return jsonify({'success': False, 'resource_found': False, 'message': 'doctor_id must be an integer', 'data': None}), 400

        slots = get_doctor_availability_slots(doctor_id_int, date)
        return jsonify({'success': True, 'resource_found': True, 'message': 'Availability fetched', 'data': {'doctor_id': doctor_id_int, 'date': date, 'available_slots': slots}}), 200
    except Exception as e:
        return jsonify({'success': False, 'resource_found': False, 'message': str(e), 'data': None}), 500

# ============================================
# ENDPOINT 8: GET SPECIALTIES LIST
# ============================================

@app.route('/api/specialties', methods=['GET'])
def get_specialties():
    """
    Get list of all available specialties and their doctors
    """
    return jsonify({
        'success': True,
        'resource_found': True,
        'message': 'Specialties fetched',
        'data': {
        'specialties': DOCTORS,
        'total_specialties': len(DOCTORS)
        }
    }), 200

# Removed monolithic ElevenLabs webhook and internal helpers for MVP simplicity

# ============================================
# HEALTH CHECK & INFO
# ============================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'success': True,
        'resource_found': True,
        'message': 'OK',
        'data': {
        'status': 'healthy',
        'service': 'Hospital Booking API',
        'version': '1.0.0'
        }
    }), 200

@app.route('/', methods=['GET'])
def api_info():
    """API documentation"""
    return jsonify({
        'success': True,
        'resource_found': True,
        'message': 'API info',
        'data': {
        'service': 'Hospital Appointment Booking API',
        'version': '1.0.0',
        'endpoints': {
                'GET /api/debug/db': 'Debug: snapshot of SQLite state',
                'GET /admin/db-viewer': 'HTML viewer for SQLite data',
                'POST /webhook/create_appointment': 'Create appointment (MVP single endpoint)',
                'GET /api/patients/<phone>': 'Get patient by phone',
                'POST /api/patients': 'Create or update patient (phone, name)',
                'GET /api/appointments/by-phone': 'Get appointments by patient phone (all statuses and times)',
                'GET /api/specialties': 'List all specialties'
        },
        'docs': 'See README for detailed API documentation'
        }
    }), 200

# ============================================
# DEBUG: DB SNAPSHOT
# ============================================

@app.route('/api/debug/db', methods=['GET'])
def debug_db_snapshot():
    try:
        limit = request.args.get('limit', default='100')
        try:
            limit_int = int(limit)
        except ValueError:
            limit_int = 100
        snapshot = get_db_snapshot(limit=limit_int)
        return jsonify({'success': True, 'resource_found': True, 'message': 'Snapshot fetched', 'data': snapshot}), 200
    except Exception as e:
        return jsonify({'success': False, 'resource_found': False, 'message': str(e), 'data': None}), 500

# ============================================
# ADMIN: SIMPLE DB VIEWER (HTML)
# ============================================

@app.route('/admin/db-viewer', methods=['GET'])
def admin_db_viewer():
    try:
        # Ensure DB schema/seed is up-to-date so all doctors appear
        try:
            init_db()
        except Exception:
            pass
        limit = request.args.get('limit', default='100')
        try:
            limit_int = int(limit)
        except ValueError:
            limit_int = 100
        snapshot = get_db_snapshot(limit=limit_int)

        # Render minimal HTML table
        def h(text):
            return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        rows_doctors = ''.join([
            f"<tr><td>{d.get('id')}</td><td>{h(d.get('name'))}</td><td>{h(d.get('specialty'))}</td><td>{d.get('active')}</td></tr>"
            for d in snapshot.get('doctors', [])
        ])

        rows_patients = ''.join([
            f"<tr><td>{h(p.get('patient_phone'))}</td><td>{h(p.get('name'))}</td></tr>"
            for p in snapshot.get('patients', [])
        ])

        rows_appts = ''.join([
            f"<tr>"
            f"<td>{a.get('id')}</td>"
            f"<td>{h(a.get('external_id'))}</td>"
            f"<td>{h(next((p.get('name') for p in snapshot.get('patients', []) if p.get('patient_phone') == a.get('patient_phone')), ''))}</td>"
            f"<td>{h(a.get('patient_phone'))}</td>"
            f"<td>{h(next((d.get('name') for d in snapshot.get('doctors', []) if d.get('id') == a.get('doctor_id')), str(a.get('doctor_id'))))}</td>"
            f"<td>{h(a.get('specialty'))}</td>"
            f"<td>{h(a.get('start_ist'))}</td>"
            f"<td>{h(a.get('end_ist'))}</td>"
            f"<td><span class='status {h(str(a.get('status')))}'>{h(a.get('status'))}</span></td>"
            f"</tr>"
            for a in snapshot.get('appointments', [])
        ])

        html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset='utf-8' />
  <title>DB Viewer</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 20px; background:#0d0d0d; color:#eaeaea; }}
    h1 {{ margin-top: 0; color:#eaeaea; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
    th, td {{ border: 1px solid #2b2b2b; padding: 10px; font-size: 14px; color:#eaeaea; }}
    th {{ background: #1f1f1f; text-align: left; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #171717; }}
    tr:nth-child(odd) {{ background: #111111; }}
    caption {{ text-align: left; font-weight: bold; margin: 8px 0; color:#eaeaea; }}
    .meta {{ color: #9e9e9e; margin-bottom: 16px; }}
    .status.confirmed {{ color: #70e000; font-weight: 600; }}
    .status.completed {{ color: #ffd166; font-weight: 600; }}
    .status.cancelled {{ color: #ef476f; font-weight: 600; }}
  </style>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <meta http-equiv='Cache-Control' content='no-store' />
  <meta http-equiv='Pragma' content='no-cache' />
  <meta http-equiv='Expires' content='0' />
  <link rel='icon' href='data:,'>
  <script> </script>
  <meta http-equiv='Content-Security-Policy' content="default-src 'self' 'unsafe-inline' data:;">
  <meta name='robots' content='noindex, nofollow'>
  <meta name='referrer' content='no-referrer'>
  <meta name='color-scheme' content='light dark'>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <meta http-equiv='X-Content-Type-Options' content='nosniff'>
  <meta http-equiv='X-Frame-Options' content='DENY'>
  <meta http-equiv='X-XSS-Protection' content='1; mode=block'>
  <meta name='format-detection' content='telephone=no'>
  <meta name='theme-color' content='#000000'>
</head>
<body>
  <h1>SQLite Viewer</h1>
  <div class='meta'>Last Sync (UTC): {h(snapshot.get('last_sync_at_utc'))} · Showing up to {limit_int} rows</div>

  <table>
    <caption>Doctors ({len(snapshot.get('doctors', []))})</caption>
    <thead><tr><th>ID</th><th>Name</th><th>Specialty</th><th>Active</th></tr></thead>
    <tbody>{rows_doctors}</tbody>
  </table>

  <table>
    <caption>Patients ({len(snapshot.get('patients', []))})</caption>
    <thead><tr><th>Phone</th><th>Name</th></tr></thead>
    <tbody>{rows_patients}</tbody>
  </table>

  <table>
    <caption>Appointments ({len(snapshot.get('appointments', []))})</caption>
    <thead>
      <tr>
        <th>ID</th>
        <th>EventID</th>
        <th>Patient</th>
        <th>Phone</th>
        <th>Doctor</th>
        <th>Specialty</th>
        <th>Start (IST)</th>
        <th>End (IST)</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>{rows_appts}</tbody>
  </table>

  <p class='meta'>For a JSON view, use <code>/api/debug/db</code>.</p>
</body>
</html>
        """
        return html, 200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}
    except Exception as e:
        return f"Error: {e}", 500, {'Content-Type': 'text/plain; charset=utf-8'}

# ============================================
# PATIENT ENDPOINTS
# ============================================

@app.route('/api/patients', methods=['POST'])
def create_or_update_patient():
    try:
        data = request.json or {}
        phone = data.get('patient_phone') or data.get('phone')
        name = data.get('patient_name') or data.get('name')
        if not phone or not name:
            return jsonify({'success': False, 'resource_found': False, 'message': 'patient_phone and patient_name are required', 'data': None}), 400
        init_db()
        upsert_patient(phone, name)
        return jsonify({'success': True, 'resource_found': True, 'message': 'Patient upserted', 'data': {'patient_phone': phone, 'name': name}}), 200
    except Exception as e:
        return jsonify({'success': False, 'resource_found': False, 'message': str(e), 'data': None}), 500


@app.route('/api/patients/<phone>', methods=['GET'])
def get_patient(phone):
    try:
        init_db()
        patient = get_patient_by_phone(phone)
        if not patient:
            return jsonify({'success': True, 'resource_found': False, 'message': 'Patient not found', 'data': None}), 200
        return jsonify({'success': True, 'resource_found': True, 'message': 'Patient fetched', 'data': patient}), 200
    except Exception as e:
        return jsonify({'success': False, 'resource_found': False, 'message': str(e), 'data': None}), 500

# ============================================
# RUN SERVER
# ============================================

if __name__ == '__main__':
    print("🏥 Hospital Booking API Starting...")
    print(f"📅 Calendar ID: {CALENDAR_ID}")
    print(f"⏰ Working Hours: {WORKING_HOURS_START}:00 - {WORKING_HOURS_END}:00")
    print(f"⏱️  Slot Duration: {SLOT_DURATION} minutes")
    print(f"👨‍⚕️  Specialties: {', '.join(DOCTORS.keys())}")
    print("\n🚀 Server starting...")

    import os
    port = int(os.getenv('PORT', '5000'))
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=port)
    except Exception:
        app.run(host='0.0.0.0', port=port, debug=False)