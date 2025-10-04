from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from functions import init_db, upsert_patient, upsert_appointment_row, get_doctor_id_by_name, assign_doctor, SLOT_DURATION


def to_utc_iso(dt_ist: datetime) -> str:
    if dt_ist.tzinfo is None:
        dt_ist = dt_ist.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return dt_ist.astimezone(timezone.utc).isoformat()


def main() -> None:
    init_db()

    # Demo patients
    patients = [
        {"name": "Vansh Raja", "phone": "+917021954565"},  # must have 2 appts
        {"name": "Aisha Khan", "phone": "+919900112233"},
        {"name": "Rohit Sharma", "phone": "+919812345678"},
        {"name": "Raj Kumar", "phone": "+911234567890"},  # default from cli.py
    ]

    for p in patients:
        upsert_patient(p["phone"], p["name"]) 

    # Choose specialties and doctors deterministically via assign_doctor
    specialties = ["general", "cardiology", "orthopedics", "dermatology"]

    ist = ZoneInfo("Asia/Kolkata")
    now_ist = datetime.now(ist)
    tomorrow_ist = (now_ist + timedelta(days=1)).replace(second=0, microsecond=0)

    # Build 5 appointments for tomorrow in IST
    # Vansh: 2 appointments
    vansh_phone = "+917021954565"
    vansh_name = "Vansh Raja"
    slots = [
        (vansh_phone, vansh_name, "general", 10, 0),    # 10:00
        (vansh_phone, vansh_name, "cardiology", 15, 0), # 15:00
        ("+919900112233", "Aisha Khan", "orthopedics", 11, 0),
        ("+919812345678", "Rohit Sharma", "dermatology", 12, 30),
        ("+911234567890", "Raj Kumar", "general", 16, 0),
    ]

    for phone, name, specialty, hour, minute in slots:
        # Appointment window in IST
        start_local = tomorrow_ist.replace(hour=hour, minute=minute)
        end_local = start_local + timedelta(minutes=SLOT_DURATION)

        doctor_name = assign_doctor(specialty)
        doctor_id = get_doctor_id_by_name(doctor_name)
        if doctor_id is None:
            # Ensure DB seeded
            init_db()
            doctor_id = get_doctor_id_by_name(doctor_name)
            if doctor_id is None:
                continue

        # External IDs for demo rows; ensure uniqueness
        external_id = f"demo-{phone.strip('+')}-{specialty}-{start_local.strftime('%Y%m%d%H%M')}"

        upsert_appointment_row(
            external_id=external_id,
            patient_phone=phone,
            doctor_id=doctor_id,
            specialty=specialty,
            start_ts_utc=to_utc_iso(start_local),
            end_ts_utc=to_utc_iso(end_local),
            status="confirmed",
            html_link="",
            description=f"Demo seed for {name} ({phone})",
            updated_at_utc=datetime.utcnow().isoformat(),
        )

    print("Seeded demo patients and 5 appointments for tomorrow in IST.")


if __name__ == "__main__":
    main()


