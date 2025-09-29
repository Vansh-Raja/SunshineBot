from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
import os

load_dotenv()

# ============================================
# GOOGLE CALENDAR SETUP
# ============================================

SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'credentials.json'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

calendar_service = build('calendar', 'v3', credentials=credentials)

# Your calendar ID from .env
CALENDAR_ID = os.getenv('CALENDAR_ID')

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
    """Convert date (YYYY-MM-DD) and time (HH:MM) to datetime object"""
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")


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
        # Validate required fields
        required_fields = ['specialty', 'patient_name', 'patient_phone', 'date', 'time']
        for field in required_fields:
            if field not in data or data.get(field) in (None, ''):
                return ({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }, 400)

        specialty = data['specialty']
        patient_name = data['patient_name']
        patient_phone = data['patient_phone']
        patient_email = data.get('patient_email', '')
        date = data['date']
        time = data['time']
        reason = data.get('reason', 'General consultation')

        # Check if specialty exists
        if specialty.lower() not in DOCTORS:
            return ({
                'success': False,
                'error': f'Unknown specialty: {specialty}. Available: {", ".join(DOCTORS.keys())}'
            }, 400)

        # Check if slot is available
        if not is_slot_available(date, time):
            # Get alternative slots
            available = get_available_slots(date, specialty)
            return ({
                'success': False,
                'error': 'Time slot not available',
                'available_slots': available[:5]
            }, 409)

        # Assign doctor
        doctor = assign_doctor(specialty)

        # Create event in Google Calendar
        start_dt = parse_datetime(date, time)
        end_dt = start_dt + timedelta(minutes=SLOT_DURATION)

        event = {
            'summary': f'[{doctor}] {patient_name}',
            'description': f'''\
Specialty: {specialty}
Doctor: {doctor}
Patient: {patient_name}
Phone: {patient_phone}
Email: {patient_email}
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

        return ({
            'success': True,
            'message': f'Appointment booked successfully with {doctor}',
            'appointment': {
                'id': created_event['id'],
                'doctor': doctor,
                'patient_name': patient_name,
                'specialty': specialty,
                'date': date,
                'time': time,
                'duration_minutes': SLOT_DURATION,
                'calendar_link': created_event.get('htmlLink')
            }
        }, 201)

    except Exception as e:
        return ({
            'success': False,
            'error': str(e)
        }, 500)


