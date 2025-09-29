from flask import Flask, request, jsonify
from datetime import datetime, timedelta
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
)

app = Flask(__name__)

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
# ENDPOINT 2: CHECK AVAILABILITY
# ============================================

@app.route('/api/availability', methods=['GET'])
def check_availability():
    """
    Check available time slots for a date and specialty
    
    Query Parameters:
    - date: YYYY-MM-DD (required)
    - specialty: cardiology, orthopedics, etc. (optional)
    
    Example: /api/availability?date=2025-10-15&specialty=cardiology
    """
    try:
        date = request.args.get('date')
        specialty = request.args.get('specialty', '').lower()
        
        if not date:
            return jsonify({
                'success': False,
                'error': 'Date parameter is required (format: YYYY-MM-DD)'
            }), 400
        
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return jsonify({
                'success': False,
                'error': 'Invalid date format. Use YYYY-MM-DD'
            }), 400
        
        # Get available slots
        available_slots = get_available_slots(date, specialty if specialty else None)
        
        # Get doctor info if specialty provided
        doctors_available = []
        if specialty and specialty in DOCTORS:
            doctors_available = DOCTORS[specialty]
        
        return jsonify({
            'success': True,
            'date': date,
            'specialty': specialty if specialty else 'all',
            'available_slots': available_slots,
            'doctors': doctors_available,
            'slot_duration_minutes': SLOT_DURATION,
            'total_available': len(available_slots)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# ENDPOINT 3: GET DOCTOR SCHEDULE
# ============================================

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    """
    Get the complete schedule for a date range
    
    Query Parameters:
    - start_date: YYYY-MM-DD (required)
    - end_date: YYYY-MM-DD (optional, defaults to start_date)
    - doctor: Doctor name filter (optional)
    
    Example: /api/schedule?start_date=2025-10-15&end_date=2025-10-20
    """
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date', start_date)
        doctor_filter = request.args.get('doctor', '')
        
        if not start_date:
            return jsonify({
                'success': False,
                'error': 'start_date parameter is required'
            }), 400
        
        # Parse dates
        start_dt = datetime.strptime(f"{start_date} 00:00", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{end_date} 23:59", "%Y-%m-%d %H:%M")
        
        # Get all events in range
        events = get_events_in_range(start_dt, end_dt)
        
        # Format schedule
        schedule = []
        for event in events:
            summary = event.get('summary', '')
            description = event.get('description', '')
            
            # Extract doctor name from summary
            doctor = ''
            if '[' in summary and ']' in summary:
                doctor = summary[summary.find('[')+1:summary.find(']')]
            
            # Skip if doctor filter doesn't match
            if doctor_filter and doctor_filter.lower() not in doctor.lower():
                continue
            
            # Extract patient name
            patient = summary.replace(f'[{doctor}]', '').strip()
            
            start_time = event['start'].get('dateTime', event['start'].get('date'))
            end_time = event['end'].get('dateTime', event['end'].get('date'))
            
            schedule.append({
                'id': event['id'],
                'doctor': doctor,
                'patient': patient,
                'start': start_time,
                'end': end_time,
                'description': description,
                'status': event.get('status', 'confirmed'),
                'link': event.get('htmlLink')
            })
        
        return jsonify({
            'success': True,
            'start_date': start_date,
            'end_date': end_date,
            'appointments': schedule,
            'total': len(schedule)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# ENDPOINT 4: RESCHEDULE APPOINTMENT
# ============================================

@app.route('/api/appointments/<appointment_id>/reschedule', methods=['PUT'])
def reschedule_appointment(appointment_id):
    """
    Reschedule an existing appointment
    
    Request Body:
    {
        "new_date": "2025-10-16",
        "new_time": "14:00"
    }
    """
    try:
        data = request.json
        
        new_date = data.get('new_date')
        new_time = data.get('new_time')
        
        if not new_date or not new_time:
            return jsonify({
                'success': False,
                'error': 'Both new_date and new_time are required'
            }), 400
        
        # Find the existing event
        event = find_event_by_id(appointment_id)
        
        if not event:
            return jsonify({
                'success': False,
                'error': 'Appointment not found'
            }), 404
        
        # Check if new slot is available
        if not is_slot_available(new_date, new_time):
            available = get_available_slots(new_date)
            return jsonify({
                'success': False,
                'error': 'New time slot not available',
                'available_slots': available[:5]
            }), 409
        
        # Update the event
        new_start_dt = parse_datetime(new_date, new_time)
        new_end_dt = new_start_dt + timedelta(minutes=SLOT_DURATION)
        
        event['start'] = {
            'dateTime': new_start_dt.isoformat(),
            'timeZone': 'Asia/Kolkata',
        }
        event['end'] = {
            'dateTime': new_end_dt.isoformat(),
            'timeZone': 'Asia/Kolkata',
        }
        
        # Add rescheduling note
        original_description = event.get('description', '')
        event['description'] = f"{original_description}\n\n[RESCHEDULED from original time]"
        
        updated_event = calendar_service.events().update(
            calendarId=CALENDAR_ID,
            eventId=appointment_id,
            body=event
        ).execute()
        
        return jsonify({
            'success': True,
            'message': 'Appointment rescheduled successfully',
            'appointment': {
                'id': updated_event['id'],
                'new_date': new_date,
                'new_time': new_time,
                'calendar_link': updated_event.get('htmlLink')
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# ENDPOINT 5: CANCEL APPOINTMENT
# ============================================

@app.route('/api/appointments/<appointment_id>', methods=['DELETE'])
def cancel_appointment(appointment_id):
    """
    Cancel an appointment
    
    Path Parameter:
    - appointment_id: The ID of the appointment to cancel
    """
    try:
        # Check if event exists
        event = find_event_by_id(appointment_id)
        
        if not event:
            return jsonify({
                'success': False,
                'error': 'Appointment not found'
            }), 404
        
        # Delete the event
        calendar_service.events().delete(
            calendarId=CALENDAR_ID,
            eventId=appointment_id
        ).execute()
        
        return jsonify({
            'success': True,
            'message': 'Appointment cancelled successfully',
            'appointment_id': appointment_id
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# ENDPOINT 6: GET PATIENT APPOINTMENTS
# ============================================

@app.route('/api/patients/<phone>/appointments', methods=['GET'])
def get_patient_appointments(phone):
    """
    Get all upcoming appointments for a patient by phone number
    
    Path Parameter:
    - phone: Patient's phone number
    """
    try:
        events = find_events_by_patient_phone(phone)
        
        appointments = []
        for event in events:
            summary = event.get('summary', '')
            description = event.get('description', '')
            
            # Extract doctor name
            doctor = ''
            if '[' in summary and ']' in summary:
                doctor = summary[summary.find('[')+1:summary.find(']')]
            
            start_time = event['start'].get('dateTime', event['start'].get('date'))
            
            appointments.append({
                'id': event['id'],
                'doctor': doctor,
                'start': start_time,
                'description': description,
                'status': event.get('status', 'confirmed'),
                'link': event.get('htmlLink')
            })
        
        return jsonify({
            'success': True,
            'phone': phone,
            'appointments': appointments,
            'total': len(appointments)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# ENDPOINT 7: GET APPOINTMENT DETAILS
# ============================================

@app.route('/api/appointments/<appointment_id>', methods=['GET'])
def get_appointment_details(appointment_id):
    """
    Get details of a specific appointment
    
    Path Parameter:
    - appointment_id: The ID of the appointment
    """
    try:
        event = find_event_by_id(appointment_id)
        
        if not event:
            return jsonify({
                'success': False,
                'error': 'Appointment not found'
            }), 404
        
        summary = event.get('summary', '')
        description = event.get('description', '')
        
        # Extract doctor name
        doctor = ''
        if '[' in summary and ']' in summary:
            doctor = summary[summary.find('[')+1:summary.find(']')]
        
        # Extract patient name
        patient = summary.replace(f'[{doctor}]', '').strip()
        
        return jsonify({
            'success': True,
            'appointment': {
                'id': event['id'],
                'doctor': doctor,
                'patient': patient,
                'start': event['start'].get('dateTime'),
                'end': event['end'].get('dateTime'),
                'description': description,
                'status': event.get('status', 'confirmed'),
                'link': event.get('htmlLink'),
                'created': event.get('created'),
                'updated': event.get('updated')
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

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
        'specialties': DOCTORS,
        'total_specialties': len(DOCTORS)
    }), 200

# Removed monolithic ElevenLabs webhook and internal helpers for MVP simplicity

# ============================================
# HEALTH CHECK & INFO
# ============================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Hospital Booking API',
        'version': '1.0.0'
    }), 200

@app.route('/', methods=['GET'])
def api_info():
    """API documentation"""
    return jsonify({
        'service': 'Hospital Appointment Booking API',
        'version': '1.0.0',
        'endpoints': {
            'POST /webhook/create_appointment': 'Create appointment (MVP single endpoint)',
            'GET /api/availability': 'Check available slots',
            'GET /api/schedule': 'Get doctor schedule',
            'PUT /api/appointments/<id>/reschedule': 'Reschedule appointment',
            'DELETE /api/appointments/<id>': 'Cancel appointment',
            'GET /api/patients/<phone>/appointments': 'Get patient appointments',
            'GET /api/appointments/<id>': 'Get appointment details',
            'GET /api/specialties': 'List all specialties',
        },
        'docs': 'See README for detailed API documentation'
    }), 200

# ============================================
# RUN SERVER
# ============================================

if __name__ == '__main__':
    print("🏥 Hospital Booking API Starting...")
    print(f"📅 Calendar ID: {CALENDAR_ID}")
    print(f"⏰ Working Hours: {WORKING_HOURS_START}:00 - {WORKING_HOURS_END}:00")
    print(f"⏱️  Slot Duration: {SLOT_DURATION} minutes")
    print(f"👨‍⚕️  Specialties: {', '.join(DOCTORS.keys())}")
    print("\n🚀 Server running on http://localhost:5000")
    print("📖 API docs at http://localhost:5000/\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True)