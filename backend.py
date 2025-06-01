from flask import Flask, request, jsonify, send_file
import sqlite3
import os
import datetime
import pandas as pd
import json
import time
import PyPDF2
from dotenv import load_dotenv
from groq import Groq
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize Flask App & Groq Client
app = Flask(__name__)
client = Groq(api_key=GROQ_API_KEY)

# Create templates directory if it doesn't exist
TEMPLATES_DIR = os.path.join(os.getcwd(), "templates")
if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR)

# ✅ Database Connection
def get_db_connection():
    conn = sqlite3.connect("leave_management.db", timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

# ✅ Create Tables If Not Exists
def initialize_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            mentor_id TEXT,
            days INTEGER,
            start_date TEXT DEFAULT CURRENT_DATE,
            end_date TEXT,
            status TEXT CHECK(status IN ('pending', 'approved', 'rejected'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mentor_assignments (
            student_id TEXT PRIMARY KEY,
            mentor_id TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS academic_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT
        )
    """)

    # New table for certificate templates
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS certificate_templates (
            template_type TEXT PRIMARY KEY,
            file_path TEXT
        )
    """)

    conn.commit()
    conn.close()

initialize_db()

# ✅ Assign Mentor API
@app.route("/assign-mentor", methods=["POST"])
def assign_mentor():
    data = request.json
    student_id = data["student_id"]
    mentor_id = data["mentor_id"]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO mentor_assignments (student_id, mentor_id) VALUES (?, ?)", (student_id, mentor_id))
    conn.commit()
    conn.close()

    return jsonify({"message": f"✅ Assigned Mentor {mentor_id} to Student {student_id}."})

# ✅ Request Leave API (Auto-approve if ≤ 5 days)
@app.route("/leave", methods=["POST"])
def process_leave():
    data = request.json
    student_id = data["student_id"]
    days = data["days"]
    start_date = datetime.date.today().strftime("%Y-%m-%d")
    end_date = (datetime.date.today() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT mentor_id FROM mentor_assignments WHERE student_id = ?", (student_id,))
    mentor = cursor.fetchone()

    if days <= 5:
        status = "approved"
        mentor_id = "Auto-Approved"
    elif mentor:
        status = "pending"
        mentor_id = mentor["mentor_id"]
    else:
        conn.close()
        return jsonify({"message": "❌ No mentor found for this student."}), 400

    cursor.execute("""
        INSERT INTO leave_requests (student_id, mentor_id, days, start_date, end_date, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (student_id, mentor_id, days, start_date, end_date, status))

    conn.commit()
    conn.close()

    return jsonify({"message": f"✅ Leave request for {days} days sent to {mentor_id}. Status: {status}."})

# ✅ Fetch Student Leave Requests
@app.route("/student-leave-status", methods=["GET"])
def student_leave_status():
    student_id = request.args.get("student_id")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT mentor_id, days, start_date, end_date, status FROM leave_requests WHERE student_id = ?", (student_id,))
    requests = cursor.fetchall()
    conn.close()

    return jsonify({"requests": [dict(req) for req in requests]})

# ✅ Fetch Mentor Leave Requests
@app.route("/mentor-leave-requests", methods=["GET"])
def mentor_leave_requests():
    mentor_id = request.args.get("mentor_id")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, student_id, days, start_date, end_date, status FROM leave_requests WHERE mentor_id = ? AND status = 'pending'", (mentor_id,))
    requests = cursor.fetchall()
    conn.close()

    return jsonify({"requests": [dict(req) for req in requests]})

# ✅ Approve Leave (Mentor Action)
@app.route("/approve-leave", methods=["POST"])
def approve_leave():
    data = request.json
    leave_id = data["leave_id"]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE leave_requests SET status = 'approved' WHERE id = ?", (leave_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "✅ Leave request approved."})

# ✅ Reject Leave (Mentor Action)
@app.route("/reject-leave", methods=["POST"])
def reject_leave():
    data = request.json
    leave_id = data["leave_id"]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE leave_requests SET status = 'rejected' WHERE id = ?", (leave_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "❌ Leave request rejected."})

# ✅ Upload AI Training Data (Admin)
@app.route("/upload-data", methods=["POST"])
def upload_ai_data():
    if "file" not in request.files:
        return jsonify({"message": "❌ No file uploaded."}), 400

    file = request.files["file"]
    filename = file.filename

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if filename.endswith(".csv") or filename.endswith(".xlsx"):
            df = pd.read_csv(file) if filename.endswith(".csv") else pd.read_excel(file)
            for _, row in df.iterrows():
                cursor.execute("INSERT INTO academic_docs (content) VALUES (?)", (json.dumps(row.to_dict()),))
            conn.commit()

        elif filename.endswith(".json"):
            data = json.load(file)
            cursor.execute("INSERT INTO academic_docs (content) VALUES (?)", (json.dumps(data),))
            conn.commit()

        elif filename.endswith(".pdf"):
            reader = PyPDF2.PdfReader(file)
            text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
            cursor.execute("INSERT INTO academic_docs (content) VALUES (?)", (text,))
            conn.commit()
        else:
            return jsonify({"message": "❌ Invalid file format. Supported formats: CSV, XLSX, JSON, PDF"}), 400

        conn.close()
        return jsonify({"message": "✅ AI Training Data Uploaded Successfully."})

    except Exception as e:
        return jsonify({"message": f"❌ Error processing file: {str(e)}"}), 500

# ✅ AI Academic Query Processing (Groq SDK)
@app.route("/academic", methods=["POST"])
def academic_query():
    data = request.json
    student_id = data["student_id"]
    query = data["query"]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM academic_docs")
    documents = cursor.fetchall()
    conn.close()

    if not documents:
        return jsonify({"response": "❌ No academic data available. Please upload training data."})

    knowledge_base = " ".join([doc[0] for doc in documents])[:4000]

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a helpful academic assistant."},
                {"role": "user", "content": f"{query}\n\nContext:\n{knowledge_base}"}
            ],
            model="llama-3.3-70b-versatile",
        )

        ai_response = chat_completion.choices[0].message.content
        return jsonify({"response": ai_response})

    except Exception as e:
        return jsonify({"response": f"❌ AI Error: {str(e)}"})

# ✅ Set Certificate Template API (Admin)
@app.route("/set-template", methods=["POST"])
def set_template():
    if "template" not in request.files:
        return jsonify({"message": "❌ No template file uploaded."}), 400

    template_type = request.form.get("template_type")
    if not template_type:
        return jsonify({"message": "❌ Template type not specified."}), 400

    template_file = request.files["template"]

    # Save the template file
    template_filename = f"{template_type.lower()}_template.pdf"
    template_path = os.path.join(TEMPLATES_DIR, template_filename)
    template_file.save(template_path)

    # Update the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO certificate_templates (template_type, file_path) VALUES (?, ?)",
        (template_type, template_path)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": f"✅ {template_type} template updated successfully."})

# ✅ Generate Certificate API
@app.route("/certificate", methods=["POST"])
def generate_certificate():
    # Check if it's a multipart form data (with template file)
    if request.files and "template" in request.files:
        student_id = request.form.get("student_id")
        cert_type = request.form.get("cert_type")
        template_file = request.files["template"]

        # Use the uploaded template
        custom_template = True
        template_data = template_file.read()
    else:
        # JSON data without custom template
        if request.is_json:
            data = request.json
        else:
            data = request.form

        student_id = data.get("student_id")
        cert_type = data.get("cert_type")

        # Check if there's a stored template
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM certificate_templates WHERE template_type = ?", (cert_type,))
        template_record = cursor.fetchone()
        conn.close()

        if template_record and os.path.exists(template_record["file_path"]):
            custom_template = True
            with open(template_record["file_path"], "rb") as f:
                template_data = f.read()
        else:
            custom_template = False

    # Create the certificate file path
    filename = f"{student_id}_{cert_type.lower()}_certificate.pdf"
    filepath = os.path.join(os.getcwd(), filename)

    if custom_template:
        # Save the template temporarily to use it
        temp_template_path = os.path.join(os.getcwd(), "temp_template.pdf")
        with open(temp_template_path, "wb") as f:
            f.write(template_data)

        # Use PyPDF2 to modify the template
        reader = PyPDF2.PdfReader(temp_template_path)
        writer = PyPDF2.PdfWriter()

        # Get the first page
        page = reader.pages[0]

        # Create a new PDF to overlay the data
        overlay_bytes = io.BytesIO()
        c = canvas.Canvas(overlay_bytes)

        # Add the certificate data
        c.setFont("Helvetica", 12)
        c.drawString(100, 400, f"Student ID: {student_id}")
        c.drawString(100, 380, f"Certificate Type: {cert_type}")
        current_date = datetime.date.today().strftime("%d-%m-%Y")
        c.drawString(100, 360, f"Date Issued: {current_date}")
        c.save()

        # Create a new PDF reader from the overlay data
        overlay_bytes.seek(0)
        overlay_pdf = PyPDF2.PdfReader(overlay_bytes)

        # Merge the template with the overlay
        page.merge_page(overlay_pdf.pages[0])
        writer.add_page(page)

        # Save the merged PDF
        with open(filepath, "wb") as output_file:
            writer.write(output_file)

        # Clean up the temporary template
        if os.path.exists(temp_template_path):
            os.remove(temp_template_path)

    else:
        # Generate a standard certificate
        c = canvas.Canvas(filepath)

        # Set up the certificate
        c.setTitle(f"{cert_type} Certificate")
        c.setFont("Helvetica-Bold", 24)

        # Certificate header
        c.drawCentredString(300, 750, "ACADEMIC INSTITUTION")
        c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(300, 700, f"{cert_type} Certificate")

        # Certificate content
        c.setFont("Helvetica", 14)
        current_date = datetime.date.today().strftime("%d-%m-%Y")

        if cert_type == "Bonafide":
            c.drawString(50, 600, f"This is to certify that {student_id} is a bonafide student")
            c.drawString(50, 580, "of our institution and is currently pursuing their education with us.")
        elif cert_type == "NOC":
            c.drawString(50, 600, f"This is to certify that {student_id} is granted a No Objection")
            c.drawString(50, 580, "Certificate for their intended activities outside the institution.")

        # Footer
        c.drawString(50, 400, f"Date: {current_date}")
        c.drawString(400, 400, "Signature")
        c.drawString(400, 380, "________________")
        c.drawString(400, 360, "Principal")

        # Add a border
        c.rect(20, 20, 555, 800, stroke=1, fill=0)

        # Save the PDF
        c.save()

    # Send the file
    try:
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return jsonify({"message": f"❌ Error generating certificate: {str(e)}"}),
# ✅ Run Server
if __name__ == "__main__":
    app.run(debug=True)
