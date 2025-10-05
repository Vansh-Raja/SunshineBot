#!/bin/bash
set -euo pipefail

BASE_URL="https://sunshine.vanshraja.me"
DATE_TOMORROW_IST=$(TZ=Asia/Kolkata date -v+1d +%Y-%m-%d)

echo "Seeding patients to $BASE_URL ..."

curl -sS -X POST "$BASE_URL/api/patients" -H "Content-Type: application/json" \
  -d '{"patient_phone":"+917021954565","patient_name":"Vansh Raja"}' | jq . || true

curl -sS -X POST "$BASE_URL/api/patients" -H "Content-Type: application/json" \
  -d '{"patient_phone":"+911234567890","patient_name":"Raj Kumar"}' | jq . || true

curl -sS -X POST "$BASE_URL/api/patients" -H "Content-Type: application/json" \
  -d '{"patient_phone":"+919900112233","patient_name":"Aisha Khan"}' | jq . || true

curl -sS -X POST "$BASE_URL/api/patients" -H "Content-Type: application/json" \
  -d '{"patient_phone":"+919812345678","patient_name":"Rohit Sharma"}' | jq . || true

echo "\nSeeding appointments for $DATE_TOMORROW_IST (IST times) ..."

create_appt() {
  local specialty="$1"; shift
  local name="$1"; shift
  local phone="$1"; shift
  local time24="$1"; shift
  local reason="$1"; shift
  curl -sS -X POST "$BASE_URL/webhook/create_appointment" -H "Content-Type: application/json" \
    -d "{\"specialty\":\"$specialty\",\"patient_name\":\"$name\",\"patient_phone\":\"$phone\",\"date\":\"$DATE_TOMORROW_IST\",\"time\":\"$time24\",\"reason\":\"$reason\"}" | jq . || true
}

# Vansh: two appointments
create_appt "general"     "Vansh Raja"   "+917021954565" "10:00" "Consultation"
create_appt "cardiology"  "Vansh Raja"   "+917021954565" "15:00" "Follow-up"

# Others: one each
create_appt "orthopedics" "Aisha Khan"   "+919900112233" "11:00" "Knee pain"
create_appt "dermatology" "Rohit Sharma" "+919812345678" "12:30" "Rash"
create_appt "general"     "Raj Kumar"    "+911234567890" "16:00" "Consultation"

echo "\nDone. Verify using: $BASE_URL/admin/db-viewer or $BASE_URL/api/appointments/by-phone?phone=+917021954565"


