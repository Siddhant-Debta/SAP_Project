import streamlit as st
import sqlite3
import os
import datetime
import pandas as pd
import json
import PyPDF2
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io
from dotenv import load_dotenv
from groq import Groq

api_key = st.secrets["GROQ_API_KEY"]

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# Set up templates directory
TEMPLATES_DIR = os.path.join(os.getcwd(), "templates")
if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR)

# Database connection and initialization
def get_db_connection():
    conn = sqlite3.connect("leave_management.db", timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS certificate_templates (
            template_type TEXT PRIMARY KEY,
            file_path TEXT
        )
    """)

    conn.commit()
    conn.close()

initialize_db()

# ---- Backend Logic Functions ----

def assign_mentor(student_id, mentor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO mentor_assignments (student_id, mentor_id) VALUES (?, ?)", (student_id, mentor_id))
    conn.commit()
    conn.close()

def process_leave_request(student_id, days):
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
        return False, "No mentor found for this student."

    cursor.execute("""
        INSERT INTO leave_requests (student_id, mentor_id, days, start_date, end_date, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (student_id, mentor_id, days, start_date, end_date, status))

    conn.commit()
    conn.close()

    return True, f"Leave request for {days} days sent to {mentor_id}. Status: {status}."

def get_student_leave_status(student_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT mentor_id, days, start_date, end_date, status FROM leave_requests WHERE student_id = ?", (student_id,))
    requests = cursor.fetchall()
    conn.close()
    return [dict(r) for r in requests]

def get_mentor_leave_requests(mentor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, student_id, days, start_date, end_date, status FROM leave_requests WHERE mentor_id = ? AND status = 'pending'", (mentor_id,))
    requests = cursor.fetchall()
    conn.close()
    return [dict(r) for r in requests]

def approve_leave_request(leave_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE leave_requests SET status = 'approved' WHERE id = ?", (leave_id,))
    conn.commit()
    conn.close()

def reject_leave_request(leave_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE leave_requests SET status = 'rejected' WHERE id = ?", (leave_id,))
    conn.commit()
    conn.close()

def upload_ai_training_data(file):
    filename = file.name
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
            conn.close()
            return False, "Invalid file format. Supported formats: CSV, XLSX, JSON, PDF"

        conn.close()
        return True, "AI Training Data Uploaded Successfully."

    except Exception as e:
        conn.close()
        return False, f"Error processing file: {str(e)}"

def academic_query(query):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM academic_docs")
    documents = cursor.fetchall()
    conn.close()

    if not documents:
        return "No academic data available. Please upload training data."

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
        return ai_response

    except Exception as e:
        return f"AI Error: {str(e)}"

def set_certificate_template(template_type, template_file):
    template_filename = f"{template_type.lower()}_template.pdf"
    template_path = os.path.join(TEMPLATES_DIR, template_filename)
    with open(template_path, "wb") as f:
        f.write(template_file.getbuffer())

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO certificate_templates (template_type, file_path) VALUES (?, ?)",
        (template_type, template_path)
    )
    conn.commit()
    conn.close()

def generate_certificate(student_id, cert_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM certificate_templates WHERE template_type = ?", (cert_type,))
    template_record = cursor.fetchone()
    conn.close()

    filename = f"{student_id}_{cert_type.lower()}_certificate.pdf"
    filepath = os.path.join(os.getcwd(), filename)

    if template_record and os.path.exists(template_record["file_path"]):
        # Use the stored template to create certificate with overlay
        template_path = template_record["file_path"]
        reader = PyPDF2.PdfReader(template_path)
        writer = PyPDF2.PdfWriter()
        page = reader.pages[0]

        # Create overlay PDF with data
        overlay_bytes = io.BytesIO()
        c = canvas.Canvas(overlay_bytes, pagesize=letter)
        c.setFont("Helvetica", 12)
        c.drawString(100, 400, f"Student ID: {student_id}")
        c.drawString(100, 380, f"Certificate Type: {cert_type}")
        current_date = datetime.date.today().strftime("%d-%m-%Y")
        c.drawString(100, 360, f"Date Issued: {current_date}")
        c.save()

        overlay_bytes.seek(0)
        overlay_pdf = PyPDF2.PdfReader(overlay_bytes)
        page.merge_page(overlay_pdf.pages[0])
        writer.add_page(page)

        with open(filepath, "wb") as output_file:
            writer.write(output_file)
    else:
        # Generate a simple certificate from scratch
        c = canvas.Canvas(filepath, pagesize=letter)
        c.setTitle(f"{cert_type} Certificate")
        c.setFont("Helvetica-Bold", 24)
        c.drawCentredString(300, 750, "ACADEMIC INSTITUTION")
        c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(300, 700, f"{cert_type} Certificate")

        c.setFont("Helvetica", 14)
        current_date = datetime.date.today().strftime("%d-%m-%Y")

        if cert_type.lower() == "bonafide":
            c.drawString(50, 600, f"This is to certify that {student_id} is a bonafide student")
            c.drawString(50, 580, "of our institution and is currently pursuing their education with us.")
        elif cert_type.lower() == "noc":
            c.drawString(50, 600, f"This is to certify that {student_id} is granted a No Objection")
            c.drawString(50, 580, "Certificate for their intended activities outside the institution.")

        c.drawString(50, 400, f"Date: {current_date}")
        c.drawString(400, 400, "Signature")
        c.drawString(400, 380, "________________")
        c.drawString(400, 360, "Principal")

        c.rect(20, 20, 555, 800, stroke=1, fill=0)

        c.save()

    with open(filepath, "rb") as f:
        pdf_bytes = f.read()

    # Clean up after reading
    if os.path.exists(filepath):
        os.remove(filepath)

    return pdf_bytes

# ---- Streamlit UI ----

st.title("🎓 Student & Mentor Management Dashboard")

# Simple login simulation
if "username" not in st.session_state:
    st.session_state["username"] = None
if "role" not in st.session_state:
    st.session_state["role"] = "student"  # or "mentor" or "admin"

def login():
    st.session_state["username"] = st.session_state["input_username"]
    # For demo, assign roles simply by username:
    if st.session_state["username"].startswith("mentor"):
        st.session_state["role"] = "mentor"
    elif st.session_state["username"].startswith("admin"):
        st.session_state["role"] = "admin"
    else:
        st.session_state["role"] = "student"
    st.success(f"Logged in as {st.session_state['username']} ({st.session_state['role']})")

if not st.session_state["username"]:
    st.text_input("Enter your username", key="input_username")
    st.button("Login", on_click=login)
    st.stop()

st.write(f"Welcome, **{st.session_state['username']}**! Role: **{st.session_state['role']}**")

# Student Dashboard
if st.session_state["role"] == "student":
    st.header("📚 Ask an Academic Question")
    query = st.text_area("Enter your academic question here:")
    if st.button("Ask"):
        if query.strip() == "":
            st.warning("Please enter a question.")
        else:
            with st.spinner("Getting answer from AI..."):
                answer = academic_query(query)
            st.markdown(f"**Answer:** {answer}")

    st.header("📝 Request Leave")
    leave_days = st.number_input("Number of leave days:", min_value=1, max_value=30, step=1)
    if st.button("Submit Leave Request"):
        success, message = process_leave_request(st.session_state["username"], leave_days)
        if success:
            st.success(message)
        else:
            st.error(message)

    st.header("📌 Your Leave Requests")
    leave_requests = get_student_leave_status(st.session_state["username"])
    if leave_requests:
        for lr in leave_requests:
            st.write(f"- Days: {lr['days']}, From: {lr['start_date']} To: {lr['end_date']}, Status: {lr['status']} (Mentor: {lr['mentor_id']})")
    else:
        st.write("No leave requests found.")

    st.header("📤 Upload Academic Training Data")
    file = st.file_uploader("Upload CSV, XLSX, JSON, or PDF file for AI training data:")
    if file is not None:
        success, msg = upload_ai_training_data(file)
        if success:
            st.success(msg)
        else:
            st.error(msg)

    st.header("📄 Generate Certificate")
    cert_type = st.selectbox("Select certificate type:", ["Bonafide", "NOC"])
    if st.button("Generate Certificate"):
        pdf_bytes = generate_certificate(st.session_state["username"], cert_type)
        st.download_button(
            label=f"Download {cert_type} Certificate",
            data=pdf_bytes,
            file_name=f"{cert_type}_{st.session_state['username']}.pdf",
            mime="application/pdf"
        )

# Mentor Dashboard
elif st.session_state["role"] == "mentor":
    st.header("📝 Leave Requests from Students")
    mentor_id = st.session_state["username"]
    requests = get_mentor_leave_requests(mentor_id)
    if requests:
        for req in requests:
            st.write(f"Student: {req['student_id']} - Days: {req['days']}, From: {req['start_date']} To: {req['end_date']}")
            cols = st.columns(2)
            if cols[0].button(f"Approve {req['id']}"):
                approve_leave_request(req['id'])
                st.experimental_rerun()
            if cols[1].button(f"Reject {req['id']}"):
                reject_leave_request(req['id'])
                st.experimental_rerun()
    else:
        st.write("No pending leave requests.")

# Admin Dashboard for mentor assignment & template upload
elif st.session_state["role"] == "admin":
    st.header("🧑‍🏫 Assign Mentor to Student")
    student_id = st.text_input("Student ID:")
    mentor_id = st.text_input("Mentor ID:")
    if st.button("Assign Mentor"):
        if student_id and mentor_id:
            assign_mentor(student_id, mentor_id)
            st.success(f"Mentor {mentor_id} assigned to student {student_id}.")
        else:
            st.error("Please provide both Student ID and Mentor ID.")

    st.header("📁 Upload Certificate Template")
    template_type = st.selectbox("Select certificate template type:", ["Bonafide", "NOC"])
    template_file = st.file_uploader("Upload PDF template file:")
    if template_file is not None:
        if st.button("Upload Template"):
            if template_file.type == "application/pdf":
                set_certificate_template(template_type, template_file)
                st.success(f"{template_type} certificate template uploaded successfully.")
            else:
                st.error("Please upload a PDF file.")

else:
    st.error("Unknown role. Please login again.")
