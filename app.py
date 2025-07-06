import os
import re
from datetime import datetime
from flask import Flask, request, render_template, send_file, redirect, url_for, session
from ics import Calendar, Event
import pdfplumber
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Needed for session storage

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

# In-memory storage for generated ICS
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
                    description = line.replace(match, "").strip()
                    description_parts = description.split()
                    if description_parts and description_parts[0].lower() in [
                        'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
                    ]:
                        description_parts = description_parts[1:]
                    description = ' '.join(description_parts).strip(' -–\t')

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

                            events_list.append((match, description))

                            event = Event()
                            event.name = description or "Academic Event"
                            event.begin = start_date
                            event.end = end_date
                            event.make_all_day()
                            calendar.events.add(event)
                    else:
                        try:
                            event_date = parse_date_string(match)
                        except Exception:
                            continue

                        events_list.append((match, description))

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

    # Store ICS content in session-like memory for download
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
    app.run()

