"""
Google Calendar integration for checking availability and creating bookings.
Falls back to a local schedule system if Google credentials aren't configured.
"""

import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

# Business hours config
BUSINESS_HOURS = {
    "start": 9,   # 9 AM
    "end": 21,    # 9 PM
    "slot_minutes": 30,
    "days": [0, 1, 2, 3, 5, 6],  # Sun-Thu + Sat (closed Friday)
}

_google_service = None


def _init_google():
    """Initialize Google Calendar API client."""
    global _google_service
    if _google_service:
        return _google_service

    if not GOOGLE_CREDENTIALS_FILE or not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        _google_service = build("calendar", "v3", credentials=credentials)
        print("Google Calendar API connected!")
        return _google_service
    except Exception as e:
        print(f"Google Calendar init failed: {e}")
        return None


def _fuzzy_match(word, targets):
    """Simple fuzzy match — returns the target if edit distance is small enough."""
    word = word.lower()
    for target in targets:
        if word == target:
            return target
        # Allow up to 2 character difference for words >= 4 chars
        if len(word) >= 4 and len(target) >= 4:
            # Check if word starts with same 3 chars
            if word[:3] == target[:3] and abs(len(word) - len(target)) <= 2:
                return target
            # Check substring containment
            if target in word or word in target:
                return target
    return None


# Common misspellings map
_SPELLING_FIXES = {
    "tomorow": "tomorrow", "tommorow": "tomorrow", "tommorrow": "tomorrow",
    "tomorrw": "tomorrow", "tomorr": "tomorrow", "tmrw": "tomorrow", "tmr": "tomorrow",
    "2morrow": "tomorrow", "2mrw": "tomorrow",
    "tday": "today", "2day": "today", "toady": "today", "todya": "today",
    "yestrday": "yesterday", "yest": "yesterday",
    "munday": "monday", "mondy": "monday", "mnday": "monday",
    "tueday": "tuesday", "tuseday": "tuesday", "tusday": "tuesday", "teusday": "tuesday",
    "wendsday": "wednesday", "wensday": "wednesday", "wednsday": "wednesday", "wednseday": "wednesday",
    "thrusday": "thursday", "thurday": "thursday", "thusday": "thursday", "thursdy": "thursday",
    "firday": "friday", "frday": "friday", "friady": "friday",
    "sturday": "saturday", "saterday": "saturday", "satruday": "saturday",
    "sundy": "sunday", "sundya": "sunday", "suday": "sunday",
    # Months
    "jan": "january", "feb": "february", "febuary": "february",
    "mar": "march", "apr": "april", "jun": "june", "jul": "july",
    "aug": "august", "sep": "september", "sept": "september",
    "oct": "october", "nov": "november", "dec": "december",
}


def _fix_spelling(text):
    """Fix common date-related misspellings."""
    words = text.lower().split()
    fixed = []
    for w in words:
        fixed.append(_SPELLING_FIXES.get(w, w))
    return " ".join(fixed)


def _parse_date(date_str):
    """Parse various date formats into a date object. Handles misspellings."""
    date_str = _fix_spelling(date_str.strip().lower())
    today = datetime.now()

    # Handle relative dates
    if "today" in date_str or date_str in ("now", "this afternoon", "this morning", "this evening"):
        return today.date()
    if "tomorrow" in date_str:
        return (today + timedelta(days=1)).date()
    if "day after tomorrow" in date_str or "day after tmr" in date_str:
        return (today + timedelta(days=2)).date()

    # Handle "next week", "next monday", etc.
    if "next week" in date_str:
        # Next Monday
        days_ahead = (0 - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (today + timedelta(days=days_ahead)).date()

    # Handle "in X days"
    import re
    in_days = re.search(r'in\s+(\d+)\s+days?', date_str)
    if in_days:
        return (today + timedelta(days=int(in_days.group(1)))).date()

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    # Try fuzzy matching day names
    for word in date_str.split():
        matched = _fuzzy_match(word, day_names)
        if matched:
            i = day_names.index(matched)
            current_day = today.weekday()
            diff = (i - current_day) % 7
            if diff == 0:
                diff = 7
            return (today + timedelta(days=diff)).date()

    # Also check if any day name is a substring
    for i, day in enumerate(day_names):
        if day in date_str:
            current_day = today.weekday()
            diff = (i - current_day) % 7
            if diff == 0:
                diff = 7
            return (today + timedelta(days=diff)).date()

    # Try common formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d", "%d/%m/%Y", "%B %d", "%b %d",
                "%B %d, %Y", "%b %d, %Y", "%d %B", "%d %b", "%d %B %Y", "%d %b %Y"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.year == 1900:  # No year provided
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today.date():
                    parsed = parsed.replace(year=today.year + 1)
            return parsed.date()
        except ValueError:
            continue

    # Try extracting month + day from natural text like "april 15" or "15 april"
    month_names = ["january","february","march","april","may","june",
                   "july","august","september","october","november","december"]
    for word in date_str.split():
        matched_month = _fuzzy_match(word, month_names)
        if matched_month:
            # Find a number nearby
            nums = re.findall(r'\d+', date_str)
            if nums:
                day_num = int(nums[0])
                month_num = month_names.index(matched_month) + 1
                try:
                    result = today.replace(month=month_num, day=day_num)
                    if result.date() < today.date():
                        result = result.replace(year=today.year + 1)
                    return result.date()
                except ValueError:
                    pass

    return None


def _parse_time(time_str):
    """Parse various time formats into hour and minute."""
    time_str = time_str.strip().lower().replace(".", ":")

    # Handle range format like "09:00 AM - 10:00 AM" — extract start time
    if " - " in time_str:
        time_str = time_str.split(" - ")[0].strip()

    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M", "%H"):
        try:
            parsed = datetime.strptime(time_str, fmt)
            return parsed.hour, parsed.minute
        except ValueError:
            continue

    # Handle "2pm", "2 pm", "14:00"
    import re
    match = re.match(r'(\d{1,2})\s*(am|pm)?', time_str)
    if match:
        hour = int(match.group(1))
        ampm = match.group(2)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        return hour, 0

    return None, None


def check_availability_google(date_obj, hour, minute):
    """Check availability using Google Calendar API."""
    service = _init_google()
    if not service:
        return None  # Signal to use local fallback

    start_dt = datetime.combine(date_obj, datetime.min.time().replace(hour=hour, minute=minute))
    end_dt = start_dt + timedelta(minutes=BUSINESS_HOURS["slot_minutes"])

    try:
        events = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start_dt.isoformat() + "Z",
            timeMax=end_dt.isoformat() + "Z",
            singleEvents=True,
        ).execute()

        return len(events.get("items", [])) == 0
    except Exception as e:
        print(f"Google Calendar check failed: {e}")
        return None


def create_google_event(date_obj, hour, minute, customer_name, customer_email=""):
    """Create a Google Calendar event."""
    service = _init_google()
    if not service:
        return None

    start_dt = datetime.combine(date_obj, datetime.min.time().replace(hour=hour, minute=minute))
    end_dt = start_dt + timedelta(minutes=BUSINESS_HOURS["slot_minutes"])

    event = {
        "summary": f"Appointment - {customer_name}",
        "description": f"Booked via ChatGenius chatbot\nCustomer: {customer_name}\nEmail: {customer_email}",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
    }

    if customer_email:
        event["attendees"] = [{"email": customer_email}]

    try:
        created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        return created.get("id", "")
    except Exception as e:
        print(f"Google event creation failed: {e}")
        return None


# ── Local fallback schedule ──
# Stores booked slots in memory (for demo without Google credentials)
_local_bookings = set()


def check_availability_local(date_obj, hour, minute):
    """Check availability using local in-memory schedule."""
    # Not on a business day
    if date_obj.weekday() not in BUSINESS_HOURS["days"]:
        return False
    # Already in the past
    now = datetime.now()
    slot_dt = datetime.combine(date_obj, datetime.min.time().replace(hour=hour, minute=minute))
    if slot_dt < now:
        return False
    # Check if already booked
    key = f"{date_obj.isoformat()}_{hour:02d}:{minute:02d}"
    return key not in _local_bookings


def book_local(date_obj, hour, minute):
    """Book a slot in local schedule."""
    key = f"{date_obj.isoformat()}_{hour:02d}:{minute:02d}"
    _local_bookings.add(key)


def get_available_slots(date_str):
    """Get list of available time slots for a given date string."""
    date_obj = _parse_date(date_str)
    if not date_obj:
        return None, "I couldn't understand that date. Could you try a format like 'Monday', 'tomorrow', or '2026-04-10'?"

    if date_obj.weekday() not in BUSINESS_HOURS["days"]:
        return None, f"Sorry, we're closed on Fridays. Our business hours are Sunday to Thursday, {BUSINESS_HOURS['start']}AM to {BUSINESS_HOURS['end'] - 12}PM."

    now = datetime.now()
    if date_obj < now.date():
        return None, "That date has already passed. Could you pick a future date?"

    slots = []
    for hour in range(BUSINESS_HOURS["start"], BUSINESS_HOURS["end"]):
        for minute in [0, 30]:
            # Try Google first, fall back to local
            available = check_availability_google(date_obj, hour, minute)
            if available is None:
                available = check_availability_local(date_obj, hour, minute)

            if available:
                time_str = datetime.min.replace(hour=hour, minute=minute).strftime("%I:%M %p")
                slots.append({"time": time_str, "hour": hour, "minute": minute})

    if not slots:
        return None, f"Sorry, no slots are available on {date_obj.strftime('%A, %B %d')}. Would you like to try a different date?"

    return {"date": date_obj, "date_display": date_obj.strftime("%A, %B %d, %Y"), "slots": slots}, None


def book_appointment(date_str, time_str, customer_name, customer_email=""):
    """Book an appointment at the given date and time."""
    date_obj = _parse_date(date_str)
    if not date_obj:
        return None, "Could not parse the date."

    hour, minute = _parse_time(time_str)
    if hour is None:
        return None, "Could not parse the time."

    # Try Google Calendar first
    google_event_id = create_google_event(date_obj, hour, minute, customer_name, customer_email)

    if google_event_id is None:
        # Use local fallback
        if not check_availability_local(date_obj, hour, minute):
            return None, "Sorry, that slot was just taken. Please pick another time."
        book_local(date_obj, hour, minute)
        google_event_id = ""

    # Preserve the full range format (e.g. "09:00 AM - 10:00 AM") if provided
    display_time = time_str.strip() if " - " in time_str else datetime.min.replace(hour=hour, minute=minute).strftime("%I:%M %p")
    display_date = date_obj.strftime("%A, %B %d, %Y")

    return {
        "date": date_obj.isoformat(),
        "date_display": display_date,
        "time": display_time,
        "calendar_event_id": google_event_id,
    }, None
