from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
load_dotenv()

# Setup credentials
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'credentials.json'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

service = build('calendar', 'v3', credentials=credentials)

# Your calendar ID
CALENDAR_ID = os.getenv('CALENDAR_ID')

# Test: Create a test event
def test_create_event():
    now = datetime.now()
    start_time = now + timedelta(hours=1)
    end_time = start_time + timedelta(minutes=30)
    
    event = {
        'summary': 'TEST - Delete Me',
        'description': 'This is a test event',
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': 'Asia/Kolkata',
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': 'Asia/Kolkata',
        },
    }
    
    try:
        created_event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()
        
        print("✅ SUCCESS!")
        print(f"Event created: {created_event['summary']}")
        print(f"Event ID: {created_event['id']}")
        print(f"Link: {created_event.get('htmlLink')}")
        print("\nCheck your Google Calendar - you should see 'TEST - Delete Me' event!")
        
    except Exception as e:
        print("❌ ERROR:")
        print(str(e))

if __name__ == '__main__':
    test_create_event()