from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
import os
import json
import sqlite3

load_dotenv()

# ============================================
# GOOGLE CALENDAR SETUP
# ============================================

SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'credentials.json'

# Prefer credentials from SERVICE_ACCOUNT_JSON (Railway-friendly). Fallback to file if absent.
credentials = None
SERVICE_ACCOUNT_JSON = os.getenv('SERVICE_ACCOUNT_JSON')
if SERVICE_ACCOUNT_JSON:
    try:
        service_info = json.loads(SERVICE_ACCOUNT_JSON)
        credentials = service_account.Credentials.from_service_account_info(
            service_info, scopes=SCOPES
        )
    except Exception:
        credentials = None

if credentials is None:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )

calendar_service = build('calendar', 'v3', credentials=credentials)

# Your calendar ID from .env
CALENDAR_ID = os.getenv('CALENDAR_ID')

# ============================================
# SQLITE SETUP (MVP cache/index)
# ============================================

DB_PATH = os.getenv('DB_PATH', 'sunshine.db')


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    # Tables
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS patients (
               patient_phone TEXT PRIMARY KEY,
               name TEXT,
               created_at TEXT DEFAULT (datetime('now')),
               updated_at TEXT DEFAULT (datetime('now'))
           )'''
    )

    cur.execute(
        '''CREATE TABLE IF NOT EXISTS doctors (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE,
               specialty TEXT,
               working_hours_start INTEGER,
               working_hours_end INTEGER,
               slot_duration INTEGER,
               active INTEGER DEFAULT 1,
               created_at TEXT DEFAULT (datetime('now')),
               updated_at TEXT DEFAULT (datetime('now'))
           )'''
    )

    cur.execute(
        '''CREATE TABLE IF NOT EXISTS appointments (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               external_id TEXT UNIQUE,
               patient_phone TEXT,
               doctor_id INTEGER,
               specialty TEXT,
               start_ts_utc TEXT,
               end_ts_utc TEXT,
               status TEXT,
               html_link TEXT,
               description TEXT,
               created_at_utc TEXT DEFAULT (datetime('now')),
               updated_at_utc TEXT
           )'''
    )

    cur.execute('CREATE INDEX IF NOT EXISTS idx_appt_doctor_start ON appointments(doctor_id, start_ts_utc)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_appt_phone_start ON appointments(patient_phone, start_ts_utc)')

    cur.execute(
        '''CREATE TABLE IF NOT EXISTS sync_state (
               id INTEGER PRIMARY KEY CHECK (id = 1),
               last_sync_at_utc TEXT,
               sync_token TEXT
           )'''
    )
    cur.execute('INSERT OR IGNORE INTO sync_state(id) VALUES (1)')
    conn.commit()
    
    # Seed one doctor per specialty from DOCTORS config (first entry only)
    for specialty, names in DOCTORS.items():
        if not names:
            continue
        name = names[0]
        cur.execute(
            '''INSERT OR IGNORE INTO doctors(name, specialty, working_hours_start, working_hours_end, slot_duration)
               VALUES (?, ?, ?, ?, ?)''',
            (name, specialty, WORKING_HOURS_START, WORKING_HOURS_END, SLOT_DURATION)
        )
    conn.commit()
    conn.close()


def get_doctor_id_by_name(name: str) -> int | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id FROM doctors WHERE name = ?', (name,))
    row = cur.fetchone()
    conn.close()
    return row['id'] if row else None


def upsert_patient(patient_phone: str, name: str | None) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO patients(patient_phone, name)
           VALUES(?, ?)
           ON CONFLICT(patient_phone) DO UPDATE SET
             name=excluded.name,
             updated_at=datetime('now')''',
        (patient_phone, name)
    )
    conn.commit()
    conn.close()


def get_patient_by_phone(patient_phone: str) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT patient_phone, name, created_at, updated_at FROM patients WHERE patient_phone = ?', (patient_phone,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_upcoming_appointments_by_phone(patient_phone: str, limit: int = 50) -> list[dict]:
    conn = get_db()
    cur = conn.cursor()
    # Use SQLite datetime() to avoid lexical string comparison issues
    cur.execute(
        '''SELECT id, external_id, patient_phone, doctor_id, specialty, start_ts_utc, end_ts_utc, status, html_link
           FROM appointments
           WHERE patient_phone = ?
             AND status = 'confirmed'
             AND datetime(end_ts_utc) >= datetime('now')
           ORDER BY datetime(start_ts_utc) ASC
           LIMIT ?''',
        (patient_phone, limit)
    )
    rows = cur.fetchall()
    conn.close()
    ist = ZoneInfo("Asia/Kolkata")
    appts = []
    for r in rows:
        d = dict(r)
        try:
            start_utc = datetime.fromisoformat(d.get('start_ts_utc'))
            end_utc = datetime.fromisoformat(d.get('end_ts_utc'))
            if start_utc.tzinfo is None:
                start_utc = start_utc.replace(tzinfo=timezone.utc)
            if end_utc.tzinfo is None:
                end_utc = end_utc.replace(tzinfo=timezone.utc)
            d['start_ist'] = start_utc.astimezone(ist).strftime('%Y-%m-%d %H:%M')
            d['end_ist'] = end_utc.astimezone(ist).strftime('%Y-%m-%d %H:%M')
        except Exception:
            d['start_ist'] = d.get('start_ts_utc')
            d['end_ist'] = d.get('end_ts_utc')
        appts.append(d)
    return appts


def has_overlap(doctor_id: int, start_ts_utc: str, end_ts_utc: str) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''SELECT 1 FROM appointments
           WHERE doctor_id = ? AND status = 'confirmed'
             AND NOT (end_ts_utc <= ? OR start_ts_utc >= ?)
           LIMIT 1''',
        (doctor_id, start_ts_utc, end_ts_utc)
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def upsert_appointment_row(*, external_id: str, patient_phone: str, doctor_id: int, specialty: str,
                           start_ts_utc: str, end_ts_utc: str, status: str, html_link: str | None,
                           description: str | None, updated_at_utc: str | None) -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO appointments(external_id, patient_phone, doctor_id, specialty,
                                    start_ts_utc, end_ts_utc, status, html_link, description,
                                    created_at_utc, updated_at_utc)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
           ON CONFLICT(external_id) DO UPDATE SET
             patient_phone=excluded.patient_phone,
             doctor_id=excluded.doctor_id,
             specialty=excluded.specialty,
             start_ts_utc=excluded.start_ts_utc,
             end_ts_utc=excluded.end_ts_utc,
             status=excluded.status,
             html_link=excluded.html_link,
             description=excluded.description,
             updated_at_utc=excluded.updated_at_utc''',
        (external_id, patient_phone, doctor_id, specialty, start_ts_utc, end_ts_utc, status,
         html_link or '', description or '', updated_at_utc or datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def _parse_phone_from_description(desc: str) -> str | None:
    if not desc:
        return None
    for line in desc.splitlines():
        if 'Phone:' in line:
            return line.split('Phone:')[-1].strip()
    return None


def _parse_patient_name_from_description(desc: str) -> str | None:
    if not desc:
        return None
    for line in desc.splitlines():
        if 'Patient:' in line:
            return line.split('Patient:')[-1].strip()
    return None


def _event_times_to_utc_iso(event: dict) -> tuple[str, str]:
    start_str = event['start'].get('dateTime') or event['start'].get('date')
    end_str = event['end'].get('dateTime') or event['end'].get('date')
    # Expect dateTime with offset like +05:30; fallback: treat as UTC if no offset
    def to_utc(s: str) -> str:
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc).isoformat()
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            # last resort: return as-is
            return s
    return to_utc(start_str), to_utc(end_str)


def sync_if_stale(max_age_seconds: int = 60) -> None:
    """Refresh local DB from Google if last sync is older than max_age_seconds.
    MVP: windowed fetch (-7d .. +90d), no push; upsert appointments only.
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT last_sync_at_utc FROM sync_state WHERE id=1')
        row = cur.fetchone()
        now_utc = datetime.utcnow()
        if row and row['last_sync_at_utc']:
            try:
                last = datetime.fromisoformat(row['last_sync_at_utc'])
            except Exception:
                last = now_utc - timedelta(seconds=max_age_seconds + 1)
            if (now_utc - last).total_seconds() <= max_age_seconds:
                conn.close()
                return
        conn.close()

        # Windowed fetch (include past appointments too)
        time_min = (now_utc - timedelta(days=180)).isoformat() + 'Z'
        time_max = (now_utc + timedelta(days=90)).isoformat() + 'Z'

        page_token = None
        while True:
            events_result = calendar_service.events().list(
                calendarId=CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime',
                pageToken=page_token
            ).execute()
            items = events_result.get('items', [])
            for ev in items:
                summary = ev.get('summary', '')
                description = ev.get('description', '')
                # Extract doctor name from summary format "[Doctor] Patient"
                doctor_name = ''
                if '[' in summary and ']' in summary:
                    doctor_name = summary[summary.find('[')+1:summary.find(']')]
                doctor_id = get_doctor_id_by_name(doctor_name) if doctor_name else None
                if doctor_id is None:
                    # Unknown doctor; skip in MVP
                    continue
                phone = _parse_phone_from_description(description) or ''
                patient_name = _parse_patient_name_from_description(description)
                start_utc, end_utc = _event_times_to_utc_iso(ev)
                status = ev.get('status', 'confirmed')
                # Ensure patient exists if we have a phone number
                if phone:
                    try:
                        upsert_patient(phone, patient_name)
                    except Exception:
                        pass
                # Compute local status: cancelled | completed | confirmed
                try:
                    end_dt = datetime.fromisoformat(end_utc)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    end_dt = now_utc
                if status == 'cancelled':
                    computed_status = 'cancelled'
                elif end_dt < datetime.now(timezone.utc):
                    computed_status = 'completed'
                else:
                    computed_status = 'confirmed'

                upsert_appointment_row(
                    external_id=ev['id'],
                    patient_phone=phone,
                    doctor_id=doctor_id,
                    specialty=ev.get('summary', ''),
                    start_ts_utc=start_utc,
                    end_ts_utc=end_utc,
                    status=computed_status,
                    html_link=ev.get('htmlLink'),
                    description=description,
                    updated_at_utc=ev.get('updated')
                )
            page_token = events_result.get('nextPageToken')
            if not page_token:
                break

        conn = get_db()
        # Backfill: mark any past confirmed appointments as completed
        try:
            conn.execute("""
                UPDATE appointments
                SET status='completed', updated_at_utc=datetime('now')
                WHERE status='confirmed' AND datetime(end_ts_utc) < datetime('now')
            """)
        except Exception:
            pass

        conn.execute('UPDATE sync_state SET last_sync_at_utc=? WHERE id=1', (datetime.utcnow().isoformat(),))
        conn.commit()
        conn.close()
    except Exception:
        # Ignore sync errors in MVP; endpoint can still proceed
        pass


def get_db_snapshot(limit: int = 100) -> dict:
    """Return a lightweight snapshot of DB state for debugging."""
    conn = get_db()
    cur = conn.cursor()
    # Sync state
    cur.execute('SELECT last_sync_at_utc FROM sync_state WHERE id=1')
    sync_row = cur.fetchone()

    # Doctors
    cur.execute('SELECT id, name, specialty, active FROM doctors ORDER BY name LIMIT ?', (limit,))
    doctors = [dict(r) for r in cur.fetchall()]

    # Patients
    cur.execute('SELECT patient_phone, name FROM patients ORDER BY updated_at DESC LIMIT ?', (limit,))
    patients = [dict(r) for r in cur.fetchall()]

    # Appointments (recent past to future) with IST projections
    cur.execute(
        '''SELECT id, external_id, patient_phone, doctor_id, specialty, start_ts_utc, end_ts_utc, status, html_link
           FROM appointments
           WHERE datetime(end_ts_utc) >= datetime('now')
           ORDER BY datetime(start_ts_utc) ASC
           LIMIT ?''',
        (limit,)
    )
    rows = cur.fetchall()
    appointments = []
    ist = ZoneInfo("Asia/Kolkata")
    for r in rows:
        d = dict(r)
        try:
            start_utc = datetime.fromisoformat(d.get('start_ts_utc'))
            end_utc = datetime.fromisoformat(d.get('end_ts_utc'))
            if start_utc.tzinfo is None:
                start_utc = start_utc.replace(tzinfo=timezone.utc)
            if end_utc.tzinfo is None:
                end_utc = end_utc.replace(tzinfo=timezone.utc)
            d['start_ist'] = start_utc.astimezone(ist).strftime('%Y-%m-%d %H:%M')
            d['end_ist'] = end_utc.astimezone(ist).strftime('%Y-%m-%d %H:%M')
        except Exception:
            d['start_ist'] = d.get('start_ts_utc')
            d['end_ist'] = d.get('end_ts_utc')
        appointments.append(d)

    conn.close()
    return {
        'last_sync_at_utc': sync_row['last_sync_at_utc'] if sync_row else None,
        'counts': {
            'doctors': len(doctors),
            'patients': len(patients),
            'appointments': len(appointments),
        },
        'doctors': doctors,
        'patients': patients,
        'appointments': appointments,
    }

# ============================================
# DOCTOR CONFIGURATION
# ============================================

# Map specialties to available doctors
DOCTORS = {
    'cardiology': ['Dr. Mehta', 'Dr. Shah'],
    'orthopedics': ['Dr. Patel', 'Dr. Kumar'],
    'general': ['Dr. Singh', 'Dr. Verma'],
    'ent': ['Dr. Reddy'],
    'dermatology': ['Dr. Chopra']
}

# Working hours
WORKING_HOURS_START = 9  # 9 AM
WORKING_HOURS_END = 17   # 5 PM
SLOT_DURATION = 30       # 30 minutes per appointment

# ============================================
# HELPER FUNCTIONS
# ============================================

def parse_datetime(date_str, time_str):
    """Convert date (YYYY-MM-DD) and time (HH:MM) to timezone-aware IST datetime"""
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=ZoneInfo("Asia/Kolkata"))


def get_events_in_range(start_datetime: datetime, end_datetime: datetime):
    """Get all events from calendar in a time range"""
    events_result = calendar_service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_datetime.isoformat() + 'Z',
        timeMax=end_datetime.isoformat() + 'Z',
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    return events_result.get('items', [])


def is_slot_available(date: str, time: str, duration_minutes: int = 30) -> bool:
    """Check if a specific time slot is available"""
    start_dt = parse_datetime(date, time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # Check if within working hours
    if start_dt.hour < WORKING_HOURS_START or end_dt.hour > WORKING_HOURS_END:
        return False

    # Check for conflicts with existing appointments
    events = get_events_in_range(start_dt, end_dt)

    return len(events) == 0


def get_available_slots(date: str, specialty: str | None = None):
    """Get all available time slots for a given date"""
    available_slots: list[str] = []

    # Generate all possible slots
    current_time = datetime.strptime(f"{date} {WORKING_HOURS_START:02d}:00", "%Y-%m-%d %H:%M")
    end_time = datetime.strptime(f"{date} {WORKING_HOURS_END:02d}:00", "%Y-%m-%d %H:%M")

    while current_time < end_time:
        time_str = current_time.strftime("%H:%M")

        if is_slot_available(date, time_str):
            available_slots.append(time_str)

        current_time += timedelta(minutes=SLOT_DURATION)

    return available_slots


def find_event_by_id(event_id: str):
    """Find an event by its ID"""
    try:
        event = calendar_service.events().get(
            calendarId=CALENDAR_ID,
            eventId=event_id
        ).execute()
        return event
    except Exception:
        return None


def find_events_by_patient_phone(phone: str):
    """Find all upcoming events for a patient by phone number"""
    now = datetime.now()
    future = now + timedelta(days=90)  # Next 90 days

    events = get_events_in_range(now, future)

    patient_events = []
    for event in events:
        description = event.get('description', '')
        if phone in description:
            patient_events.append(event)

    return patient_events


def assign_doctor(specialty: str) -> str:
    """Assign a doctor from the specialty pool"""
    doctors = DOCTORS.get(specialty.lower(), ['Dr. General'])
    return doctors[0]


# ============================================
# BUSINESS LOGIC
# ============================================

def create_appointment_logic(data: dict):
    """Create an appointment in Google Calendar from provided data.

    Returns a tuple of (response_dict, http_status_code).
    """
    try:
        # Ensure DB is initialized and fresh
        init_db()
        sync_if_stale(max_age_seconds=60)
        # Validate required fields
        required_fields = ['specialty', 'patient_name', 'patient_phone', 'date', 'time']
        for field in required_fields:
            if field not in data or data.get(field) in (None, ''):
                return ({
                    'success': False,
                    'resource_found': False,
                    'message': f"Missing required field: {field}",
                    'data': None
                }, 400)

        specialty = data['specialty']
        patient_name = data['patient_name']
        patient_phone = data['patient_phone']
        # patient_email removed per requirements
        date = data['date']
        time = data['time']
        reason = data.get('reason', 'General consultation')

        # Check if specialty exists
        if specialty.lower() not in DOCTORS:
            return ({
                'success': False,
                'resource_found': False,
                'message': f'Unknown specialty: {specialty}. Available: {", ".join(DOCTORS.keys())}',
                'data': None
            }, 400)

        # Working hours check in local time window
        start_dt_local = parse_datetime(date, time)
        end_dt_local = start_dt_local + timedelta(minutes=SLOT_DURATION)
        if start_dt_local.hour < WORKING_HOURS_START or end_dt_local.hour > WORKING_HOURS_END:
            return ({
                'success': False,
                'resource_found': True,
                'message': 'Requested time is outside working hours',
                'data': None
            }, 200)

        # Local overlap check using SQLite
        # Convert to UTC ISO for DB comparison
        start_ts_utc = start_dt_local.astimezone(timezone.utc).isoformat()
        end_ts_utc = end_dt_local.astimezone(timezone.utc).isoformat()

        # Determine doctor id
        doctor = assign_doctor(specialty)
        doctor_id = get_doctor_id_by_name(doctor)
        if doctor_id is None:
            # Seed doctor to DB if missing (edge case)
            init_db()
            doctor_id = get_doctor_id_by_name(doctor)

        if has_overlap(doctor_id, start_ts_utc, end_ts_utc):
            return ({
                'success': False,
                'resource_found': True,
                'message': 'Time slot not available',
                'data': None
            }, 200)

        # Create event in Google Calendar
        start_dt = start_dt_local
        end_dt = end_dt_local

        event = {
            'summary': f'[{doctor}] {patient_name}',
            'description': f'''\
Specialty: {specialty}
Doctor: {doctor}
Patient: {patient_name}
Phone: {patient_phone}
Reason: {reason}
'''.strip(),
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 60},
                ],
            },
        }

        created_event = calendar_service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()

        # Upsert patient and appointment into DB
        upsert_patient(patient_phone, patient_name)
        upsert_appointment_row(
            external_id=created_event['id'],
            patient_phone=patient_phone,
            doctor_id=doctor_id,
            specialty=specialty,
            start_ts_utc=start_ts_utc,
            end_ts_utc=end_ts_utc,
            status='confirmed',
            html_link=created_event.get('htmlLink'),
            description=event.get('description'),
            updated_at_utc=created_event.get('updated')
        )

        return ({
            'success': True,
            'resource_found': True,
            'message': f'Appointment booked successfully with {doctor}',
            'data': {
                'id': created_event['id'],
                'doctor': doctor,
                'patient_name': patient_name,
                'specialty': specialty,
                'date': date,
                'time': time,
                'duration_minutes': SLOT_DURATION,
                'calendar_link': created_event.get('htmlLink')
            }
        }, 200)

    except Exception as e:
        return ({
            'success': False,
            'resource_found': False,
            'message': str(e),
            'data': None
        }, 500)


