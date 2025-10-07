## SunshineBot — AI Voice Assistant for Hospital Appointments (MVP)

### What it is
SunshineBot is a production-ready MVP voice assistant that answers calls, recognizes returning patients by phone number, and manages appointments end-to-end using Google Calendar—while keeping a local SQLite cache in sync every minute for reliability and fast lookups.

---

### Functions (Current MVP)
1) Patient identification and context
- Auto-identifies returning callers by phone number as soon as the call connects
- Looks up patient profile and recent/upcoming visits

2) Create new appointments
- Confirms details with the caller before action (doctor/specialty, date/time, reason) in IST
- Assigns the appropriate doctor per specialty; enforces working hours and avoids conflicts
- Creates Google Calendar events with standard titles: "[Doctor Name] Patient Name"
- Persists to local DB; syncs with Google every minute

3) List patient appointments (all statuses)
- Retrieves all appointments for the caller (past, future, cancelled, completed)
- Filters results conversationally (e.g., “What do I have tomorrow?”, “When was my last visit with Dr Reddy?”)
- Returns event IDs so follow-up actions (reschedule/cancel) are straightforward

4) Manage existing appointments
- Reschedule: confirms new date/time, updates Calendar and DB
- Cancel: confirms intent, deletes Calendar event and marks DB as cancelled

5) Patient record management
- Adds/updates minimal patient profile (phone + name) only when needed (just-in-time, after intent to book)


---

### How it works (High-level)
1) Caller dials → Bot greets warmly and checks caller ID to identify patient
2) Bot understands intent (book, check schedule, reschedule, cancel)
3) Before taking action, bot reads back and confirms details
4) Bot performs the requested action via API (Calendar + local DB)
5) Bot summarizes the outcome in IST (and offers helpful next steps)

---

### Future Improvements
1) WhatsApp/Email integration
- Send confirmations, reminders, and changes via WhatsApp or email; two-way confirmation flows

2) Improved latency handling
- Replace free-tier infrastructure/services with optimized production components for low-latency, seamless conversations

3) Expanded knowledge (RAG)
- Enrich with more hospital FAQs, department details, prep instructions, insurance info for robust Q&A

4) Multi-language support
- Support regional languages; locale-aware formatting and TTS voices

---

### Demo Scenarios (MVP)
- “Book dermatology tomorrow at 3 PM.” → Bot confirms and books
- “What appointments do I have tomorrow?” → Bot lists tomorrow’s visits
- “Reschedule my cardiology from 3 PM to 4 PM.” → Bot confirms intent and reschedules
- “Cancel my 12:30 dermatology.” → Bot confirms and cancels
