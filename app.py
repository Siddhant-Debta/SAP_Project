import streamlit as st
import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BACKEND_URL = "http://127.0.0.1:5000"


# ✅ Login Page
def login():
    st.title("🔑 Login to AI Academic System")
    username = st.text_input("Enter your username:")
    role = st.selectbox("Select your role:", ["Student", "Mentor", "Admin"])

    if st.button("Login") and username:
        st.session_state["username"] = username
        st.session_state["role"] = role
        st.session_state["logged_in"] = True
        st.query_params.update(role=role)  # Updated from experimental_set_query_params

# ✅ Logout Function
def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.query_params.clear()  # Updated from experimental_set_query_params
    st.rerun()  # Updated from experimental_rerun

# ✅ Navigation Bar
def navigation_bar():
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if st.button("🔄 Refresh"):
            st.rerun()  # Updated from experimental_rerun
    with col3:
        if st.button("🚪 Logout"):
            logout()

# ✅ Student Dashboard
def student_dashboard():
    st.title("🎓 Student Dashboard")
    st.write(f"👋 Welcome, {st.session_state['username']}")
    navigation_bar()

    # 📚 Ask an Academic Question
    st.subheader("📚 Ask an Academic Question")
    question = st.text_input("Enter your question:")
    if st.button("Ask"):
        with st.spinner("🤖 Processing..."):
            response = requests.post(f"{BACKEND_URL}/academic", json={"student_id": st.session_state["username"], "query": question})
            if response.status_code == 200:
                st.success(response.json().get("response", "❌ Error processing AI response."))
            else:
                st.error("❌ AI Error. Please try again.")

    # 📝 Request Leave
    st.subheader("📝 Request Leave")
    leave_days = st.number_input("Number of Leave Days", min_value=1, step=1)
    if st.button("Apply Leave"):
        response = requests.post(f"{BACKEND_URL}/leave", json={"student_id": st.session_state["username"], "days": leave_days})
        if response.status_code == 200:
            st.success(response.json().get("message", "❌ Error processing response."))
        else:
            st.error("❌ Backend error.")

    # 📌 Leave Status
    st.subheader("📌 Your Leave Requests")
    response = requests.get(f"{BACKEND_URL}/student-leave-status", params={"student_id": st.session_state["username"]})

    if response.status_code == 200:
        leave_requests = response.json().get("requests", [])
        if leave_requests:
            for req in leave_requests:
                st.write(f"📌 **Mentor:** {req['mentor_id']} | **Days:** {req['days']} | **Status:** {req['status']}")
        else:
            st.write("No leave requests found.")
    else:
        st.error("❌ Error fetching leave status.")

    # 📜 Generate Certificate
    st.subheader("📜 Generate Certificate")
    cert_type = st.selectbox("Select Certificate Type:", ["Bonafide", "NOC"])

    # Custom template option
    use_custom_template = st.checkbox("Use custom template")
    custom_template = None

    if use_custom_template:
        st.write("Upload your custom certificate template (PDF):")
        template_file = st.file_uploader("Upload template", type=["pdf"])
        if template_file:
            custom_template = template_file.getvalue()

    if st.button("Generate Certificate"):
        payload = {
            "student_id": st.session_state["username"],
            "cert_type": cert_type
        }

        files = {}
        if custom_template:
            files = {"template": ("template.pdf", custom_template, "application/pdf")}

        if files:
            response = requests.post(f"{BACKEND_URL}/certificate", data=payload, files=files, stream=True)
        else:
            response = requests.post(f"{BACKEND_URL}/certificate", json=payload, stream=True)

        if response.status_code == 200:
            # Save the generated certificate locally
            cert_filename = f"{st.session_state['username']}_certificate.pdf"
            with open(cert_filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            st.success("✅ Certificate generated successfully!")
            st.download_button("📥 Download Certificate", open(cert_filename, "rb"), file_name=cert_filename, mime="application/pdf")

        else:
            st.error("❌ Error generating certificate. Please try again.")


# ✅ Mentor Dashboard
def mentor_dashboard():
    st.title("👨‍🏫 Mentor Dashboard")
    st.write(f"👋 Welcome, {st.session_state['username']}")
    navigation_bar()

    # 📌 Leave Requests
    st.subheader("📌 Pending Leave Requests")
    response = requests.get(f"{BACKEND_URL}/mentor-leave-requests", params={"mentor_id": st.session_state["username"]})

    if response.status_code == 200:
        leave_requests = response.json().get("requests", [])
        if leave_requests:
            for req in leave_requests:
                st.write(f"📌 **Student:** {req['student_id']} | **Days:** {req['days']} | **Status:** {req['status']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"✅ Approve {req['id']}"):
                        requests.post(f"{BACKEND_URL}/approve-leave", json={"leave_id": req["id"]})
                        st.success("✅ Leave Approved!")
                with col2:
                    if st.button(f"❌ Reject {req['id']}"):
                        requests.post(f"{BACKEND_URL}/reject-leave", json={"leave_id": req["id"]})
                        st.error("❌ Leave Rejected!")
        else:
            st.write("No pending leave requests.")
    else:
        st.error("❌ Error fetching leave requests.")

# ✅ Admin Dashboard
def admin_dashboard():
    st.title("⚙️ Admin Dashboard")
    navigation_bar()

    # 📂 Upload AI Training Data
    st.subheader("📂 Upload AI Training Data (JSON/CSV/Excel/PDF)")
    uploaded_file = st.file_uploader("Upload JSON/CSV/Excel/PDF File", type=["csv", "xlsx", "json", "pdf"])
    if uploaded_file and st.button("Upload"):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        response = requests.post(f"{BACKEND_URL}/upload-data", files=files)
        if response.status_code == 200:
            st.success(response.json().get("message", "✅ File uploaded successfully!"))
        else:
            st.error("❌ Error processing file.")

    # 👨‍🏫 Assign Mentors
    st.subheader("👨‍🏫 Assign Mentors to Students")
    student_id = st.text_input("Enter Student ID:")
    mentor_id = st.text_input("Enter Mentor ID:")
    if st.button("Assign Mentor"):
        response = requests.post(f"{BACKEND_URL}/assign-mentor", json={"student_id": student_id, "mentor_id": mentor_id})
        if response.status_code == 200:
            st.success(response.json().get("message", "✅ Mentor assigned successfully!"))
        else:
            st.error("❌ Error assigning mentor.")

    # 📜 Manage Certificate Templates
    st.subheader("📜 Manage Certificate Templates")
    template_type = st.selectbox("Template Type:", ["Bonafide", "NOC"])
    template_file = st.file_uploader("Upload Default Template", type=["pdf"])

    if template_file and st.button("Set Default Template"):
        files = {"template": (template_file.name, template_file.getvalue())}
        response = requests.post(
            f"{BACKEND_URL}/set-template",
            data={"template_type": template_type},
            files=files
        )
        if response.status_code == 200:
            st.success("✅ Default template updated successfully!")
        else:
            st.error("❌ Error updating template.")

# ✅ Main App Logic
if "logged_in" not in st.session_state:
    login()
else:
    role = st.session_state["role"]
    if role == "Student":
        student_dashboard()
    elif role == "Mentor":
        mentor_dashboard()
    elif role == "Admin":
        admin_dashboard()
