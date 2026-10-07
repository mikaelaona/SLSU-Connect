import os
import secrets
import string

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    flash,
    render_template_string
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# APP CONFIGURATION
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "study-sched-development-secret"
)

# Render PostgreSQL URL
database_url = os.environ.get("DATABASE_URL")

if database_url:
    # Some PostgreSQL URLs may use postgres://
    # SQLAlchemy expects postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url

else:
    # Allows you to run the app locally without PostgreSQL.
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///study_sched.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =========================================================
# DATABASE MODELS
# =========================================================

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(100),
        nullable=False
    )

    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )


class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(
        db.Integer,
        db.ForeignKey("student.id"),
        nullable=False
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    subject = db.Column(
        db.String(100)
    )

    date = db.Column(
        db.String(30),
        nullable=False
    )

    start_time = db.Column(
        db.String(30)
    )

    end_time = db.Column(
        db.String(30)
    )


class Deadline(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(
        db.Integer,
        db.ForeignKey("student.id"),
        nullable=False
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    description = db.Column(
        db.Text
    )

    due_date = db.Column(
        db.String(30),
        nullable=False
    )

    completed = db.Column(
        db.Boolean,
        default=False
    )


class StudyGroup(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(150),
        nullable=False
    )

    code = db.Column(
        db.String(20),
        unique=True,
        nullable=False
    )

    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("student.id"),
        nullable=False
    )


class GroupMember(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    group_id = db.Column(
        db.Integer,
        db.ForeignKey("study_group.id"),
        nullable=False
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey("student.id"),
        nullable=False
    )


class GroupTask(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    group_id = db.Column(
        db.Integer,
        db.ForeignKey("study_group.id"),
        nullable=False
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    description = db.Column(
        db.Text
    )

    due_date = db.Column(
        db.String(30)
    )

    completed = db.Column(
        db.Boolean,
        default=False
    )


class Review(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey("student.id"),
        nullable=False
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    content = db.Column(
        db.Text
    )


# =========================================================
# CREATE DATABASE TABLES
# =========================================================

with app.app_context():
    db.create_all()


# =========================================================
# HTML TEMPLATE
# =========================================================

BASE_STYLE = """
<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, Helvetica, sans-serif;
    background: #f4f7fb;
    color: #172033;
}

.navbar {
    background: #4f46e5;
    color: white;
    padding: 18px 5%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 15px;
}

.logo {
    font-size: 24px;
    font-weight: bold;
}

.navbar a {
    color: white;
    text-decoration: none;
    margin: 5px 8px;
}

.navbar a:hover {
    text-decoration: underline;
}

.container {
    width: 92%;
    max-width: 1100px;
    margin: 35px auto;
}

.dashboard {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 20px;
}

.two-column {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}

.card {
    background: white;
    padding: 25px;
    border-radius: 16px;
    margin-bottom: 20px;
    box-shadow: 0 5px 20px rgba(0,0,0,0.07);
}

.card h2 {
    margin-top: 0;
}

.item {
    padding: 14px 0;
    border-bottom: 1px solid #e5e7eb;
}

.item:last-child {
    border-bottom: none;
}

label {
    display: block;
    font-weight: bold;
    margin-top: 15px;
    margin-bottom: 7px;
}

input,
textarea {
    width: 100%;
    padding: 12px;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    font-size: 15px;
}

textarea {
    min-height: 120px;
    resize: vertical;
}

button,
.button {
    display: inline-block;
    background: #4f46e5;
    color: white;
    border: none;
    padding: 11px 17px;
    border-radius: 8px;
    text-decoration: none;
    cursor: pointer;
    margin-top: 15px;
}

button:hover,
.button:hover {
    background: #3730a3;
}

.danger {
    background: #dc2626;
}

.danger:hover {
    background: #b91c1c;
}

.auth {
    min-height: 85vh;
    display: flex;
    align-items: center;
    justify-content: center;
}

.auth-card {
    width: 420px;
    max-width: 92%;
    background: white;
    padding: 35px;
    border-radius: 18px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.1);
}

.auth-card h1 {
    text-align: center;
    color: #4f46e5;
}

.auth-card button {
    width: 100%;
}

.message {
    width: 92%;
    max-width: 1100px;
    margin: 20px auto;
    padding: 14px;
    background: #dbeafe;
    color: #1e40af;
    border-radius: 8px;
}

.group-code {
    background: #eef2ff;
    border: 2px dashed #6366f1;
    padding: 25px;
    border-radius: 15px;
    text-align: center;
    margin-bottom: 25px;
}

.group-code h1 {
    color: #4f46e5;
    letter-spacing: 5px;
}

.review {
    white-space: pre-wrap;
    line-height: 1.7;
}

.small {
    color: #6b7280;
}

@media (max-width: 750px) {

    .dashboard,
    .two-column {
        grid-template-columns: 1fr;
    }

    .navbar {
        flex-direction: column;
        align-items: flex-start;
    }

    .navbar a {
        display: block;
        margin: 8px 0;
    }
}

</style>
"""


def page(title, content):
    """Creates a complete HTML page."""

    logged_in = "student_id" in session

    navigation = ""

    if logged_in:
        navigation = f"""
        <nav>
            <a href="{url_for('dashboard')}">Dashboard</a>
            <a href="{url_for('schedule')}">Schedule</a>
            <a href="{url_for('deadlines')}">Deadlines</a>
            <a href="{url_for('groups')}">Groups</a>
            <a href="{url_for('review_pad')}">Review Pad</a>
            <a href="{url_for('logout')}">Logout</a>
        </nav>
        """

    messages = ""

    for message in session.pop("_flashes", []):
        messages += f"""
        <div class="message">
            {message[1]}
        </div>
        """

    return f"""
    <!DOCTYPE html>

    <html>

    <head>

        <meta charset="UTF-8">

        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>{title} - Study Sched</title>

        {BASE_STYLE}

    </head>

    <body>

        <header class="navbar">

            <div class="logo">
                📚 Study Sched
            </div>

            {navigation}

        </header>

        {messages}

        {content}

    </body>

    </html>
    """


# =========================================================
# LOGIN REQUIRED
# =========================================================

def require_login():

    if "student_id" not in session:
        return False

    return True


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    if require_login():
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:

            flash("Please complete all fields.")

            return redirect(url_for("register"))

        if len(password) < 6:

            flash("Password must contain at least 6 characters.")

            return redirect(url_for("register"))

        existing = Student.query.filter_by(
            email=email
        ).first()

        if existing:

            flash("This email is already registered.")

            return redirect(url_for("login"))

        student = Student(
            name=name,
            email=email,
            password=generate_password_hash(password)
        )

        db.session.add(student)
        db.session.commit()

        session["student_id"] = student.id
        session["student_name"] = student.name

        return redirect(url_for("dashboard"))

    content = """

    <div class="auth">

        <div class="auth-card">

            <h1>Study Sched</h1>

            <p>
                Create your student account.
            </p>

            <form method="POST">

                <label>Full Name</label>

                <input
                    type="text"
                    name="name"
                    required
                >

                <label>Email</label>

                <input
                    type="email"
                    name="email"
                    required
                >

                <label>Password</label>

                <input
                    type="password"
                    name="password"
                    minlength="6"
                    required
                >

                <button type="submit">
                    Create Account
                </button>

            </form>

            <p>
                Already have an account?
                <a href="/login">Login</a>
            </p>

        </div>

    </div>

    """

    return page("Register", content)


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        student = Student.query.filter_by(
            email=email
        ).first()

        if not student:

            flash("Invalid email or password.")

            return redirect(url_for("login"))

        if not check_password_hash(
            student.password,
            password
        ):

            flash("Invalid email or password.")

            return redirect(url_for("login"))

        session["student_id"] = student.id
        session["student_name"] = student.name

        return redirect(url_for("dashboard"))

    content = """

    <div class="auth">

        <div class="auth-card">

            <h1>📚 Study Sched</h1>

            <p>
                Student Login
            </p>

            <form method="POST">

                <label>Email</label>

                <input
                    type="email"
                    name="email"
                    required
                >

                <label>Password</label>

                <input
                    type="password"
                    name="password"
                    required
                >

                <button type="submit">
                    Login
                </button>

            </form>

            <p>
                Don't have an account?
                <a href="/register">Register</a>
            </p>

        </div>

    </div>

    """

    return page("Login", content)


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if not require_login():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    schedules = (
        Schedule.query
        .filter_by(student_id=student_id)
        .order_by(Schedule.date, Schedule.start_time)
        .limit(5)
        .all()
    )

    deadlines = (
        Deadline.query
        .filter_by(
            student_id=student_id,
            completed=False
        )
        .order_by(Deadline.due_date)
        .limit(5)
        .all()
    )

    memberships = GroupMember.query.filter_by(
        student_id=student_id
    ).all()

    groups = []

    for membership in memberships:

        group = db.session.get(
            StudyGroup,
            membership.group_id
        )

        if group:
            groups.append(group)

    schedule_html = ""

    if schedules:

        for item in schedules:

            schedule_html += f"""
            <div class="item">

                <strong>{item.title}</strong>

                <p>
                    {item.subject or "No subject"}
                </p>

                <small>
                    📅 {item.date}
                    {item.start_time or ""}
                </small>

            </div>
            """

    else:

        schedule_html = "<p>No schedules yet.</p>"

    deadline_html = ""

    if deadlines:

        for item in deadlines:

            deadline_html += f"""
            <div class="item">

                <strong>
                    {item.title}
                </strong>

                <p>
                    Due: {item.due_date}
                </p>

            </div>
            """

    else:

        deadline_html = "<p>No upcoming deadlines.</p>"

    group_html = ""

    if groups:

        for group in groups:

            group_html += f"""
            <div class="item">

                <strong>
                    {group.name}
                </strong>

                <p>
                    Code: {group.code}
                </p>

                <a href="/groups/{group.id}">
                    Open Group
                </a>

            </div>
            """

    else:

        group_html = "<p>No groups yet.</p>"

    content = f"""

    <main class="container">

        <h1>
            Welcome, {session["student_name"]}! 👋
        </h1>

        <p class="small">
            Stay organized and keep up with your studies.
        </p>

        <div class="dashboard">

            <div class="card">

                <h2>📅 Schedule</h2>

                {schedule_html}

                <a class="button"
                   href="/schedule">
                    Manage Schedule
                </a>

            </div>


            <div class="card">

                <h2>⏰ Deadlines</h2>

                {deadline_html}

                <a class="button"
                   href="/deadlines">
                    Manage Deadlines
                </a>

            </div>


            <div class="card">

                <h2>👥 Group Tasks</h2>

                {group_html}

                <a class="button"
                   href="/groups">
                    Manage Groups
                </a>

            </div>


            <div class="card">

                <h2>📝 Review Pad</h2>

                <p>
                    Write and save your study notes,
                    reviewers, and important information.
                </p>

                <a class="button"
                   href="/review-pad">
                    Open Review Pad
                </a>

            </div>

        </div>

    </main>

    """

    return page("Dashboard", content)


# =========================================================
# SCHEDULE
# =========================================================

@app.route("/schedule", methods=["GET", "POST"])
def schedule():

    if not require_login():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    if request.method == "POST":

        item = Schedule(
            student_id=student_id,
            title=request.form.get("title", ""),
            subject=request.form.get("subject", ""),
            date=request.form.get("date", ""),
            start_time=request.form.get("start_time", ""),
            end_time=request.form.get("end_time", "")
        )

        db.session.add(item)
        db.session.commit()

        return redirect(url_for("schedule"))

    schedules = (
        Schedule.query
        .filter_by(student_id=student_id)
        .order_by(Schedule.date, Schedule.start_time)
        .all()
    )

    items = ""

    for item in schedules:

        items += f"""
        <div class="card">

            <h3>{item.title}</h3>

            <p>
                Subject:
                {item.subject or "None"}
            </p>

            <p>
                📅 {item.date}
            </p>

            <p>
                ⏰ {item.start_time or "Any time"}
                -
                {item.end_time or ""}
            </p>

            <a
                class="button danger"
                href="/schedule/delete/{item.id}">
                Delete
            </a>

        </div>
        """

    content = f"""

    <main class="container">

        <h1>📅 My Schedule</h1>

        <div class="card">

            <h2>Add Schedule</h2>

            <form method="POST">

                <label>Activity</label>

                <input
                    name="title"
                    placeholder="Mathematics Class"
                    required
                >

                <label>Subject</label>

                <input
                    name="subject"
                    placeholder="Mathematics"
                >

                <label>Date</label>

                <input
                    type="date"
                    name="date"
                    required
                >

                <label>Start Time</label>

                <input
                    type="time"
                    name="start_time"
                >

                <label>End Time</label>

                <input
                    type="time"
                    name="end_time"
                >

                <button type="submit">
                    Add Schedule
                </button>

            </form>

        </div>

        <h2>Your Schedule</h2>

        {items or "<p>No schedules yet.</p>"}

    </main>

    """

    return page("Schedule", content)


@app.route("/schedule/delete/<int:item_id>")
def delete_schedule(item_id):

    if not require_login():
        return redirect(url_for("login"))

    item = db.session.get(
        Schedule,
        item_id
    )

    if item and item.student_id == session["student_id"]:

        db.session.delete(item)
        db.session.commit()

    return redirect(url_for("schedule"))


# =========================================================
# DEADLINES
# =========================================================

@app.route("/deadlines", methods=["GET", "POST"])
def deadlines():

    if not require_login():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    if request.method == "POST":

        deadline = Deadline(
            student_id=student_id,
            title=request.form.get("title", ""),
            description=request.form.get(
                "description",
                ""
            ),
            due_date=request.form.get(
                "due_date",
                ""
            )
        )

        db.session.add(deadline)
        db.session.commit()

        return redirect(url_for("deadlines"))

    deadline_list = (
        Deadline.query
        .filter_by(student_id=student_id)
        .order_by(Deadline.due_date)
        .all()
    )

    deadline_html = ""

    for item in deadline_list:

        status = (
            "Completed"
            if item.completed
            else "Not Completed"
        )

        deadline_html += f"""
        <div class="card">

            <h3>{item.title}</h3>

            <p>
                {item.description or "No description."}
            </p>

            <strong>
                📅 Due: {item.due_date}
            </strong>

            <p>
                Status: {status}
            </p>

            <a
                class="button"
                href="/deadlines/complete/{item.id}">
                Toggle Complete
            </a>

        </div>
        """

    content = f"""

    <main class="container">

        <h1>⏰ Deadlines</h1>

        <div class="card">

            <h2>Add Deadline</h2>

            <form method="POST">

                <label>Title</label>

                <input
                    name="title"
                    placeholder="Science Project"
                    required
                >

                <label>Description</label>

                <textarea
                    name="description"
                    placeholder="Assignment details..."
                ></textarea>

                <label>Due Date</label>

                <input
                    type="date"
                    name="due_date"
                    required
                >

                <button type="submit">
                    Add Deadline
                </button>

            </form>

        </div>

        {deadline_html or "<p>No deadlines yet.</p>"}

    </main>

    """

    return page("Deadlines", content)


@app.route("/deadlines/complete/<int:item_id>")
def complete_deadline(item_id):

    if not require_login():
        return redirect(url_for("login"))

    item = db.session.get(
        Deadline,
        item_id
    )

    if item and item.student_id == session["student_id"]:

        item.completed = not item.completed

        db.session.commit()

    return redirect(url_for("deadlines"))


# =========================================================
# GROUP CODE
# =========================================================

def generate_group_code():

    characters = string.ascii_uppercase + string.digits

    while True:

        code = "".join(
            secrets.choice(characters)
            for _ in range(8)
        )

        existing = StudyGroup.query.filter_by(
            code=code
        ).first()

        if not existing:
            return code


# =========================================================
# GROUPS
# =========================================================

@app.route("/groups")
def groups():

    if not require_login():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    memberships = GroupMember.query.filter_by(
        student_id=student_id
    ).all()

    group_list = []

    for membership in memberships:

        group = db.session.get(
            StudyGroup,
            membership.group_id
        )

        if group:
            group_list.append(group)

    group_html = ""

    for group in group_list:

        group_html += f"""
        <div class="card">

            <h3>
                {group.name}
            </h3>

            <p>
                Group Code:
                <strong>{group.code}</strong>
            </p>

            <a
                class="button"
                href="/groups/{group.id}">
                Open Group
            </a>

        </div>
        """

    content = f"""

    <main class="container">

        <h1>👥 Group Tasks</h1>

        <div class="two-column">

            <div class="card">

                <h2>Create New Group</h2>

                <form
                    method="POST"
                    action="/groups/create">

                    <label>Group Name</label>

                    <input
                        name="name"
                        placeholder="Science Project Team"
                        required
                    >

                    <button type="submit">
                        Create Group
                    </button>

                </form>

            </div>


            <div class="card">

                <h2>Join a Group</h2>

                <form
                    method="POST"
                    action="/groups/join">

                    <label>Group Code</label>

                    <input
                        name="code"
                        placeholder="AB12CD34"
                        required
                    >

                    <button type="submit">
                        Join Group
                    </button>

                </form>

            </div>

        </div>

        <h2>My Groups</h2>

        {group_html or "<p>You have not joined any groups yet.</p>"}

    </main>

    """

    return page("Groups", content)


# =========================================================
# CREATE GROUP
# =========================================================

@app.route("/groups/create", methods=["POST"])
def create_group():

    if not require_login():
        return redirect(url_for("login"))

    name = request.form.get(
        "name",
        ""
    ).strip()

    if not name:

        flash("Please enter a group name.")

        return redirect(url_for("groups"))

    code = generate_group_code()

    group = StudyGroup(
        name=name,
        code=code,
        owner_id=session["student_id"]
    )

    db.session.add(group)
    db.session.commit()

    member = GroupMember(
        group_id=group.id,
        student_id=session["student_id"]
    )

    db.session.add(member)
    db.session.commit()

    flash(
        f"Group created successfully! "
        f"Your code is {code}"
    )

    return redirect(
        url_for(
            "group_page",
            group_id=group.id
        )
    )


# =========================================================
# JOIN GROUP
# =========================================================

@app.route("/groups/join", methods=["POST"])
def join_group():

    if not require_login():
        return redirect(url_for("login"))

    code = request.form.get(
        "code",
        ""
    ).strip().upper()

    group = StudyGroup.query.filter_by(
        code=code
    ).first()

    if not group:

        flash("Group code not found.")

        return redirect(url_for("groups"))

    existing = GroupMember.query.filter_by(
        group_id=group.id,
        student_id=session["student_id"]
    ).first()

    if existing:

        flash("You are already a member of this group.")

        return redirect(
            url_for(
                "group_page",
                group_id=group.id
            )
        )

    member = GroupMember(
        group_id=group.id,
        student_id=session["student_id"]
    )

    db.session.add(member)
    db.session.commit()

    flash("You joined the group successfully!")

    return redirect(
        url_for(
            "group_page",
            group_id=group.id
        )
    )


# =========================================================
# GROUP PAGE
# =========================================================

@app.route("/groups/<int:group_id>")
def group_page(group_id):

    if not require_login():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    membership = GroupMember.query.filter_by(
        group_id=group_id,
        student_id=student_id
    ).first()

    if not membership:

        flash("You are not a member of this group.")

        return redirect(url_for("groups"))

    group = db.session.get(
        StudyGroup,
        group_id
    )

    if not group:

        flash("Group not found.")

        return redirect(url_for("groups"))

    tasks = GroupTask.query.filter_by(
        group_id=group_id
    ).order_by(
        GroupTask.due_date
    ).all()

    members_db = GroupMember.query.filter_by(
        group_id=group_id
    ).all()

    members = []

    for member in members_db:

        student = db.session.get(
            Student,
            member.student_id
        )

        if student:
            members.append(student)

    task_html = ""

    for task in tasks:

        status = (
            "Completed"
            if task.completed
            else "Not Completed"
        )

        task_html += f"""
        <div class="card">

            <h3>
                {task.title}
            </h3>

            <p>
                {task.description or "No description."}
            </p>

            <p>
                Status: {status}
            </p>

            <p>
                📅 Due:
                {task.due_date or "No deadline"}
            </p>

            <a
                class="button"
                href="/groups/{group.id}/tasks/{task.id}/complete">
                Toggle Complete
            </a>

        </div>
        """

    member_html = ""

    for member in members:

        member_html += f"""
        <p>
            👤 {member.name}
        </p>
        """

    content = f"""

    <main class="container">

        <h1>
            👥 {group.name}
        </h1>

        <div class="group-code">

            <p>
                Share this code with your classmates:
            </p>

            <h1>
                {group.code}
            </h1>

        </div>


        <div class="card">

            <h2>Add Group Task</h2>

            <form
                method="POST"
                action="/groups/{group.id}/tasks">

                <label>Task</label>

                <input
                    name="title"
                    placeholder="Research Chapter 1"
                    required
                >

                <label>Description</label>

                <textarea
                    name="description"
                    placeholder="Task details..."
                ></textarea>

                <label>Due Date</label>

                <input
                    type="date"
                    name="due_date"
                >

                <button type="submit">
                    Add Group Task
                </button>

            </form>

        </div>


        <h2>Group Tasks</h2>

        {task_html or "<p>No group tasks yet.</p>"}


        <h2>Members</h2>

        <div class="card">

            {member_html}

        </div>

    </main>

    """

    return page(
        group.name,
        content
    )


# =========================================================
# ADD GROUP TASK
# =========================================================

@app.route(
    "/groups/<int:group_id>/tasks",
    methods=["POST"]
)
def add_group_task(group_id):

    if not require_login():
        return redirect(url_for("login"))

    membership = GroupMember.query.filter_by(
        group_id=group_id,
        student_id=session["student_id"]
    ).first()

    if not membership:

        return "You are not a member of this group.", 403

    task = GroupTask(
        group_id=group_id,
        title=request.form.get(
            "title",
            ""
        ),
        description=request.form.get(
            "description",
            ""
        ),
        due_date=request.form.get(
            "due_date",
            ""
        )
    )

    db.session.add(task)
    db.session.commit()

    return redirect(
        url_for(
            "group_page",
            group_id=group_id
        )
    )


# =========================================================
# COMPLETE GROUP TASK
# =========================================================

@app.route(
    "/groups/<int:group_id>/tasks/<int:task_id>/complete"
)
def complete_group_task(group_id, task_id):

    if not require_login():
        return redirect(url_for("login"))

    membership = GroupMember.query.filter_by(
        group_id=group_id,
        student_id=session["student_id"]
    ).first()

    if not membership:

        return "Not a group member.", 403

    task = db.session.get(
        GroupTask,
        task_id
    )

    if task and task.group_id == group_id:

        task.completed = not task.completed

        db.session.commit()

    return redirect(
        url_for(
            "group_page",
            group_id=group_id
        )
    )


# =========================================================
# REVIEW PAD
# =========================================================

@app.route("/review-pad", methods=["GET", "POST"])
def review_pad():

    if not require_login():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    if request.method == "POST":

        review = Review(
            student_id=student_id,
            title=request.form.get(
                "title",
                ""
            ),
            content=request.form.get(
                "content",
                ""
            )
        )

        db.session.add(review)
        db.session.commit()

        return redirect(url_for("review_pad"))

    reviews = Review.query.filter_by(
        student_id=student_id
    ).order_by(
        Review.id.desc()
    ).all()

    review_html = ""

    for review in reviews:

        review_html += f"""
        <div class="card">

            <h3>
                {review.title}
            </h3>

            <p class="review">
                {review.content or ""}
            </p>

            <a
                class="button danger"
                href="/review-pad/delete/{review.id}">
                Delete
            </a>

        </div>
        """

    content = f"""

    <main class="container">

        <h1>📝 Review Pad</h1>

        <div class="card">

            <h2>Create Review Note</h2>

            <form method="POST">

                <label>Title</label>

                <input
                    name="title"
                    placeholder="Biology - Cell Structure"
                    required
                >

                <label>Notes</label>

                <textarea
                    name="content"
                    placeholder="Write your review notes..."
                    required
                ></textarea>

                <button type="submit">
                    Save Review
                </button>

            </form>

        </div>

        <h2>My Review Notes</h2>

        {review_html or "<p>No review notes yet.</p>"}

    </main>

    """

    return page("Review Pad", content)


# =========================================================
# DELETE REVIEW
# =========================================================

@app.route("/review-pad/delete/<int:review_id>")
def delete_review(review_id):

    if not require_login():
        return redirect(url_for("login"))

    review = db.session.get(
        Review,
        review_id
    )

    if review and review.student_id == session["student_id"]:

        db.session.delete(review)
        db.session.commit()

    return redirect(url_for("review_pad"))


# =========================================================
# ERROR HANDLER
# =========================================================

@app.errorhandler(500)
def internal_error(error):

    return page(
        "Error",
        """
        <main class="container">

            <div class="card">

                <h1>Something went wrong.</h1>

                <p>
                    The Study Sched server encountered an error.
                </p>

                <a class="button" href="/login">
                    Back to Login
                </a>

            </div>

        </main>
        """
    ), 500


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
