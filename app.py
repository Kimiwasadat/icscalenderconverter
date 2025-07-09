import os
import re
from datetime import datetime, timedelta
from flask import Flask, request, render_template, send_file, session
from ics import Calendar, Event
import pdfplumber
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'supersecretkey'

DEFAULT_YEAR = 2025

KEYWORDS = [
    "college closed",
    "start of classes",
    "start of spring term",
    "start of fall term",
    "first day of saturday classes",
    "last day of classes",
    "no classes",
    "final exam",
    "final examinations",
    "classes follow",
    "end of",
    "spring recess",
]

date_pattern = r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b(?:\s*[-–]\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?)?'

ics_storage = {}

def parse_date_string(date_str):
    parts = date_str.strip().split('/')
    if len(parts) == 2:
        month, day = map(int, parts)
        year = DEFAULT_YEAR
    elif len(parts) == 3:
        month, day, year = map(int, parts)
        if year < 100:
            year += 2000
    else:
        raise ValueError(f"Invalid date format: {date_str}")
    return datetime(year, month, day)

def strip_header_weekdays(desc):
    # Remove things like "Wednesday" or "Wednesday - Thursday" at start
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    parts = desc.split()
    while parts and parts[0].lower() in weekdays:
        parts.pop(0)
        if parts and parts[0] in ['-', '–']:
            parts.pop(0)
    return ' '.join(parts)

def clean_description(raw_desc, line_lower):
    # Special normalization
    if "college closed" in line_lower:
        return "College Closed"
    if "no classes scheduled" in line_lower:
        return "No classes scheduled"

    # Remove leading weekday header
    desc = strip_header_weekdays(raw_desc)

    # Clean punctuation
    desc = desc.strip(' ;:-–').strip()

    return desc

def extract_events(file_stream):
    calendar = Calendar()
    events_list = []

    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            lines = text.split('\n')
            for line in lines:
                line_lower = line.lower()
                if not any(keyword in line_lower for keyword in KEYWORDS):
                    continue

                matches = re.findall(date_pattern, line)
                if not matches:
                    continue

                for match in matches:
                    raw_desc = line.replace(match, "").strip()
                    description = clean_description(raw_desc, line_lower)

                    # Handle date ranges as ONE event
                    if '-' in match or '–' in match:
                        date_parts = re.split(r'[-–]', match)
                        if len(date_parts) == 2:
                            start_str = date_parts[0].strip()
                            end_str = date_parts[1].strip()
                            try:
                                start_date = parse_date_string(start_str)
                                end_date = parse_date_string(end_str)
                            except Exception:
                                continue

                            # Format date range for table
                            date_string = f"{start_date.strftime('%m/%d')}-{end_date.strftime('%m/%d')}"
                            events_list.append((date_string, description))

                            # ICS single multi-day event
                            event = Event()
                            event.name = description or "Academic Event"
                            event.begin = start_date
                            event.end = end_date + timedelta(days=1)
                            event.make_all_day()
                            calendar.events.add(event)
                    else:
                        try:
                            event_date = parse_date_string(match)
                        except Exception:
                            continue

                        date_string = event_date.strftime("%m/%d")
                        events_list.append((date_string, description))

                        event = Event()
                        event.name = description or "Academic Event"
                        event.begin = event_date
                        event.make_all_day()
                        calendar.events.add(event)

    return events_list, str(calendar)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'pdf_file' not in request.files:
        return "No file uploaded", 400

    file = request.files['pdf_file']
    if file.filename == '':
        return "No selected file", 400

    events, ics_content = extract_events(file)

    # Store ICS in memory for download
    session_id = os.urandom(8).hex()
    ics_storage[session_id] = ics_content

    return render_template('results.html', events=events, ics_id=session_id)

@app.route('/download/<ics_id>')
def download_ics(ics_id):
    if ics_id not in ics_storage:
        return "File not found", 404

    ics_data = ics_storage[ics_id]
    buffer = BytesIO()
    buffer.write(ics_data.encode('utf-8'))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='text/calendar',
        as_attachment=True,
        download_name='important_dates.ics'
    )

if __name__ == "__main__":
    app.run(debug=True)
