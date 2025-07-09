import os
import re
from datetime import datetime, timedelta
from flask import Flask, request, render_template, send_file, session
from ics import Calendar, Event
import pdfplumber
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'supersecretkey'

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

def extract_academic_year_from_header(pdf):
    try:
        first_page = pdf.pages[0]
        text = first_page.extract_text()
        if text:
            lines = text.split('\n')
            for line in lines:
                match = re.search(r'(Fall|Spring|Summer)\s+(\d{4})', line, re.IGNORECASE)
                if match:
                    return int(match.group(2))
    except Exception as e:
        print(f"⚠️ Error reading header for year: {e}")
    return None

def parse_date_string(date_str, header_year=None):
    parts = date_str.strip().split('/')
    if len(parts) == 3:
        month, day, year = map(int, parts)
        if year < 100:
            year += 2000
        return datetime(year, month, day)
    elif len(parts) == 2 and header_year:
        month, day = map(int, parts)
        return datetime(header_year, month, day)
    else:
        raise ValueError(f"Date format invalid or missing year: {date_str}")

def strip_header_weekdays(desc):
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    parts = desc.split()
    result = []
    skipping = True
    for part in parts:
        lowered = part.lower().strip(',-–')
        if skipping and (lowered in weekdays or lowered in ['-', '–']):
            continue
        else:
            skipping = False
            result.append(part)
    return ' '.join(result)

def clean_description(raw_desc, line_lower):
    if "college closed" in line_lower:
        return "College Closed"
    if "no classes scheduled" in line_lower:
        return "No classes scheduled"
    desc = strip_header_weekdays(raw_desc)
    desc = desc.strip(' ;:-–').strip()
    return desc

def extract_events(file_stream):
    calendar = Calendar()
    events_list = []

    with pdfplumber.open(file_stream) as pdf:
        header_year = extract_academic_year_from_header(pdf)
        session['header_year'] = header_year

        if header_year:
            print(f"✅ Detected Academic Year: {header_year}")
        else:
            print("⚠️ Could not detect academic year in header. MM/DD dates will be skipped.")

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

                    if '-' in match or '–' in match:
                        date_parts = re.split(r'[-–]', match)
                        if len(date_parts) == 2:
                            start_str = date_parts[0].strip()
                            end_str = date_parts[1].strip()
                            try:
                                start_date = parse_date_string(start_str, header_year)
                                end_date = parse_date_string(end_str, header_year)
                            except Exception as e:
                                print(f"⚠️ Skipping range '{match}': {e}")
                                continue

                            date_string = f"{start_date.strftime('%m/%d/%Y')}-{end_date.strftime('%m/%d/%Y')}"
                            events_list.append((date_string, description))

                            event = Event()
                            event.name = description or "Academic Event"
                            event.begin = start_date
                            event.end = end_date + timedelta(days=1)
                            event.make_all_day()
                            calendar.events.add(event)
                    else:
                        try:
                            event_date = parse_date_string(match, header_year)
                        except Exception as e:
                            print(f"⚠️ Skipping date '{match}': {e}")
                            continue

                        date_string = event_date.strftime("%m/%d/%Y")
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

    session_id = os.urandom(8).hex()
    ics_storage[session_id] = ics_content

    return render_template('results.html', events=events, ics_id=session_id, errors=[])

@app.route('/generate', methods=['POST'])
def generate():
    header_year = session.get('header_year')
    dates = request.form.getlist('dates')
    descriptions = request.form.getlist('descriptions')
    calendar = Calendar()
    errors = []

    events_list = []
    for i, (date, desc) in enumerate(zip(dates, descriptions), start=1):
        if not date.strip() or not desc.strip():
            errors.append(f"Row {i}: Missing date or description.")
            continue

        date = date.strip()
        desc = desc.strip()

        if '-' in date or '–' in date:
            date_parts = re.split(r'[-–]', date)
            if len(date_parts) == 2:
                try:
                    start_date = parse_date_string(date_parts[0].strip(), header_year)
                    end_date = parse_date_string(date_parts[1].strip(), header_year)
                    event = Event()
                    event.name = desc
                    event.begin = start_date
                    event.end = end_date + timedelta(days=1)
                    event.make_all_day()
                    calendar.events.add(event)
                    events_list.append((date, desc))
                except Exception as e:
                    errors.append(f"Row {i}: Invalid date range. {str(e)}")
            else:
                errors.append(f"Row {i}: Invalid date range format.")
        else:
            try:
                event_date = parse_date_string(date, header_year)
                event = Event()
                event.name = desc
                event.begin = event_date
                event.make_all_day()
                calendar.events.add(event)
                events_list.append((date, desc))
            except Exception as e:
                errors.append(f"Row {i}: Invalid date. {str(e)}")

    session_id = os.urandom(8).hex()
    ics_storage[session_id] = str(calendar)

    return render_template('results.html', events=events_list, ics_id=session_id, errors=errors)

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
