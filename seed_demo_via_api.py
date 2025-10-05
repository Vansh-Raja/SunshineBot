import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Tuple

import requests


BASE_URL = "https://sunshine.vanshraja.me"


def post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = requests.post(url, json=payload, timeout=30)
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        return {"status": resp.status_code, "ok": resp.ok, "body": body}
    except Exception as e:
        return {"status": 0, "ok": False, "error": str(e)}


def seed_patients(patients: List[Tuple[str, str]]) -> None:
    url = f"{BASE_URL}/api/patients"
    for phone, name in patients:
        payload = {"patient_phone": phone, "patient_name": name}
        result = post_json(url, payload)
        print(f"Add/Update patient {name} ({phone}) => {result['status']}")
        print(json.dumps(result.get("body", result), indent=2, ensure_ascii=False))


def seed_appointments(appts: List[Dict[str, str]]) -> None:
    url = f"{BASE_URL}/webhook/create_appointment"
    for appt in appts:
        result = post_json(url, appt)
        who = f"{appt['patient_name']} ({appt['patient_phone']})"
        when = f"{appt['date']} {appt['time']}"
        spec = appt['specialty']
        print(f"Create appt {who} [{spec}] @ {when} => {result['status']}")
        print(json.dumps(result.get("body", result), indent=2, ensure_ascii=False))


def main() -> None:
    ist = ZoneInfo("Asia/Kolkata")
    today_ist = datetime.now(ist)
    tomorrow_ist = (today_ist + timedelta(days=1)).date()
    date_str = tomorrow_ist.strftime("%Y-%m-%d")

    # Patients: ensure Raj Kumar default exists; Vansh must have two appts
    patients = [
        ("+917021954565", "Vansh Raja"),
        ("+911234567890", "Raj Kumar"),
        ("+919900112233", "Aisha Khan"),
        ("+919812345678", "Rohit Sharma"),
    ]

    seed_patients(patients)

    # Five appointments tomorrow (IST): Vansh x2, others x1
    appointments = [
        {"specialty": "general",      "patient_name": "Vansh Raja",   "patient_phone": "+917021954565", "date": date_str, "time": "10:00", "reason": "Consultation"},
        {"specialty": "cardiology",   "patient_name": "Vansh Raja",   "patient_phone": "+917021954565", "date": date_str, "time": "15:00", "reason": "Follow-up"},
        {"specialty": "orthopedics",  "patient_name": "Aisha Khan",   "patient_phone": "+919900112233", "date": date_str, "time": "11:00", "reason": "Knee pain"},
        {"specialty": "dermatology",  "patient_name": "Rohit Sharma", "patient_phone": "+919812345678", "date": date_str, "time": "12:30", "reason": "Rash"},
        {"specialty": "general",      "patient_name": "Raj Kumar",    "patient_phone": "+911234567890", "date": date_str, "time": "16:00", "reason": "Consultation"},
    ]

    seed_appointments(appointments)
    print("Completed seeding via API.")


if __name__ == "__main__":
    main()


