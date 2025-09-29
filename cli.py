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


def main() -> None:
    menu = textwrap.dedent(
        """
        SunshineBot CLI
        ----------------
        1) Test appointment creation
        2) Check health
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
        elif choice in {"q", "quit", "exit"}:
            print("Bye!")
            sys.exit(0)
        else:
            print("Invalid choice. Try again.\n")


if __name__ == "__main__":
    main()


