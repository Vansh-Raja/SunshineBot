import json
import sys
import textwrap
from typing import Any, Dict
from datetime import datetime, timedelta

import requests


BASE_URL = "https://sunshine.vanshraja.me"


def print_response(resp: requests.Response) -> None:
    print("\n=== HTTP RESPONSE ===")
    print(f"Status: {resp.status_code}")
    print("Headers:")
    for k, v in resp.headers.items():
        print(f"  {k}: {v}")
    print("Body:")
    try:
        parsed = resp.json()
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
    except Exception:
        print(resp.text)
    print("====================\n")


def input_or_default(prompt: str, default: str) -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    return val or default


def test_create_appointment() -> None:
    print("\n-- Test: Create Appointment --")
    specialty = input_or_default("Specialty", "cardiology")
    patient_name = input_or_default("Patient name", "Raj Kumar")
    patient_phone = input_or_default("Patient phone", "+911234567890")
    default_date = datetime.now().strftime("%Y-%m-%d")
    default_time = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")
    date = input_or_default("Date (YYYY-MM-DD)", default_date)
    time = input_or_default("Time (HH:MM)", default_time)
    reason = input_or_default("Reason", "Consultation")

    payload: Dict[str, Any] = {
        "specialty": specialty,
        "patient_name": patient_name,
        "patient_phone": patient_phone,
        "date": date,
        "time": time,
        "reason": reason,
    }

    url = f"{BASE_URL}/webhook/create_appointment"
    try:
        resp = requests.post(url, json=payload, timeout=30)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def test_health() -> None:
    print("\n-- Test: Health --")
    url = f"{BASE_URL}/health"
    try:
        resp = requests.get(url, timeout=15)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def test_add_patient() -> None:
    print("\n-- Test: Add/Update Patient --")
    phone = input_or_default("Patient phone", "+911234567890")
    name = input_or_default("Patient name", "Raj Kumar")
    url = f"{BASE_URL}/api/patients"
    payload = {"patient_phone": phone, "patient_name": name}
    try:
        resp = requests.post(url, json=payload, timeout=15)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def test_get_patient() -> None:
    print("\n-- Test: Get Patient --")
    phone = input_or_default("Patient phone", "+911234567890")
    url = f"{BASE_URL}/api/patients/{phone}"
    try:
        resp = requests.get(url, timeout=15)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def test_availability() -> None:
    print("\n-- Test: Availability --")
    date = input_or_default("Date (YYYY-MM-DD)", datetime.now().strftime("%Y-%m-%d"))
    specialty = input_or_default("Specialty (optional)", "")
    params = {"date": date}
    if specialty:
        params["specialty"] = specialty
    url = f"{BASE_URL}/api/availability"
    try:
        resp = requests.get(url, params=params, timeout=15)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def test_schedule() -> None:
    print("\n-- Test: Schedule --")
    start = input_or_default("Start date (YYYY-MM-DD)", datetime.now().strftime("%Y-%m-%d"))
    end = input_or_default("End date (YYYY-MM-DD)", start)
    doctor = input_or_default("Doctor filter (optional)", "")
    params = {"start_date": start, "end_date": end}
    if doctor:
        params["doctor"] = doctor
    url = f"{BASE_URL}/api/schedule"
    try:
        resp = requests.get(url, params=params, timeout=20)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def test_get_appointment() -> None:
    print("\n-- Test: Get Appointment --")
    appt_id = input_or_default("Appointment ID", "")
    if not appt_id:
        print("Appointment ID required")
        return
    url = f"{BASE_URL}/api/appointments/{appt_id}"
    try:
        resp = requests.get(url, timeout=15)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def test_cancel_appointment() -> None:
    print("\n-- Test: Cancel Appointment --")
    appt_id = input_or_default("Appointment ID", "")
    if not appt_id:
        print("Appointment ID required")
        return
    url = f"{BASE_URL}/api/appointments/{appt_id}"
    try:
        resp = requests.delete(url, timeout=15)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def test_reschedule() -> None:
    print("\n-- Test: Reschedule --")
    appt_id = input_or_default("Appointment ID", "")
    if not appt_id:
        print("Appointment ID required")
        return
    new_date = input_or_default("New date (YYYY-MM-DD)", datetime.now().strftime("%Y-%m-%d"))
    new_time = input_or_default("New time (HH:MM)", (datetime.now() + timedelta(hours=2)).strftime("%H:%M"))
    url = f"{BASE_URL}/api/appointments/{appt_id}/reschedule"
    payload = {"new_date": new_date, "new_time": new_time}
    try:
        resp = requests.put(url, json=payload, timeout=20)
        print_response(resp)
    except Exception as e:
        print(f"Request failed: {e}")


def main() -> None:
    menu = textwrap.dedent(
        """
        SunshineBot CLI
        ----------------
        1) Test appointment creation
        2) Check health
        3) Add/Update patient
        4) Get patient by phone
        5) Get appointments by phone
        q) Quit
        """
    )

    while True:
        print(menu)
        choice = input("Select an option: ").strip().lower()
        if choice == "1":
            test_create_appointment()
        elif choice == "2":
            test_health()
        elif choice == "3":
            test_add_patient()
        elif choice == "4":
            test_get_patient()
        elif choice == "5":
            # reuse get_patient_appointments via new by-phone endpoint
            print("\n-- Test: Appointments by phone --")
            phone = input_or_default("Patient phone", "+911234567890")
            url = f"{BASE_URL}/api/appointments/by-phone"
            try:
                resp = requests.get(url, params={"phone": phone}, timeout=15)
                print_response(resp)
            except Exception as e:
                print(f"Request failed: {e}")
        elif choice in {"q", "quit", "exit"}:
            print("Bye!")
            sys.exit(0)
        else:
            print("Invalid choice. Try again.\n")


if __name__ == "__main__":
    main()


