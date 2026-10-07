import os
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, jsonify, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# =========================================================
# DATABASE
# =========================================================

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

USE_POSTGRES = DATABASE_URL.startswith("postgresql://")

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def get_db():
        return psycopg2.connect(DATABASE_URL)

    def execute(query, params=(), fetch=False, many=False):
        db = get_db()
        cur = db.cursor(cursor_factory=RealDictCursor)

        query = query.replace("?", "%s")
        # SQLite-style INTEGER PRIMARY KEY does not auto-increment in PostgreSQL.
        query = query.replace("id INTEGER PRIMARY KEY", "id SERIAL PRIMARY KEY")

        if many:
            cur.executemany(query, params)
        else:
            cur.execute(query, params)

        result = None

        if fetch:
            result = cur.fetchall()

        db.commit()
        cur.close()
        db.close()

        return result

else:
    import sqlite3

    DB_FILE = "studysched.db"

    def get_db():
        db = sqlite3.connect(DB_FILE)
        db.row_factory = sqlite3.Row
        return db

    def execute(query, params=(), fetch=False, many=False):
        db = get_db()
        cur = db.cursor()

        if many:
            cur.executemany(query, params)
        else:
            cur.execute(query, params)

        result = None

        if fetch:
            result = cur.fetchall()

        db.commit()
        cur.close()
        db.close()

        return result


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_db():

    execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name VARCHAR(150) NOT NULL,
        is_admin INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        title VARCHAR(200) NOT NULL,
        description TEXT,
        schedule_date VARCHAR(30) NOT NULL,
        schedule_time VARCHAR(20) NOT NULL,
        reminder_minutes INTEGER DEFAULT 10,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        join_code VARCHAR(20) UNIQUE NOT NULL,
        owner_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS group_members (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(group_id, user_id)
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL,
        title VARCHAR(200) NOT NULL,
        description TEXT,
        assigned_to INTEGER,
        deadline VARCHAR(30),
        status VARCHAR(30) DEFAULT 'Pending',
        progress INTEGER DEFAULT 0,
        proof TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Create default admin
    admin = execute(
        "SELECT id FROM users WHERE username = ?",
        (os.environ.get("ADMIN_USERNAME", "admin"),),
        fetch=True
    )

    if not admin:
        execute("""
        INSERT INTO users
        (username, password, full_name, is_admin)
        VALUES (?, ?, ?, ?)
        """, (
            os.environ.get("ADMIN_USERNAME", "admin"),
            generate_password_hash(os.environ.get("ADMIN_PASSWORD", "admin123")),
            "StudySched Administrator",
            1
        ))


init_db()


# =========================================================
# HELPERS
# =========================================================

def current_user():
    if "user_id" not in session:
        return None

    result = execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],),
        fetch=True
    )

    return result[0] if result else None


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):

        user = current_user()

        if not user or not user["is_admin"]:
            return "Unauthorized", 403

        return func(*args, **kwargs)

    return wrapper


def add_activity(group_id, user_id, message):

    execute("""
    INSERT INTO activity
    (group_id, user_id, message)
    VALUES (?, ?, ?)
    """, (group_id, user_id, message))


# =========================================================
# MAIN CSS
# =========================================================

CSS = """

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, Helvetica, sans-serif;
    background: #f3f6fb;
    color: #172033;
}

nav {
    background: #172554;
    color: white;
    padding: 15px 25px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 20;
}

.logo {
    font-size: 23px;
    font-weight: bold;
}

.navlinks {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.navlinks a {
    color: white;
    text-decoration: none;
    padding: 8px 12px;
    border-radius: 8px;
}

.navlinks a:hover {
    background: #263b80;
}

.container {
    max-width: 1150px;
    margin: auto;
    padding: 25px;
}

.hero {
    background: linear-gradient(135deg, #172554, #2563eb);
    color: white;
    padding: 35px;
    border-radius: 20px;
    margin-bottom: 25px;
}

.hero h1 {
    margin-top: 0;
}

.cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 18px;
    margin-bottom: 25px;
}

.card {
    background: white;
    padding: 20px;
    border-radius: 16px;
    box-shadow: 0 4px 18px rgba(0,0,0,.06);
    margin-bottom: 18px;
}

.stat {
    font-size: 30px;
    font-weight: bold;
    color: #2563eb;
}

h2, h3 {
    margin-top: 0;
}

input, textarea, select {
    width: 100%;
    padding: 12px;
    margin: 7px 0 15px;
    border: 1px solid #d4dbea;
    border-radius: 9px;
    font-size: 15px;
}

textarea {
    min-height: 100px;
    resize: vertical;
}

button, .btn {
    border: none;
    background: #2563eb;
    color: white;
    padding: 11px 16px;
    border-radius: 9px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
}

button:hover, .btn:hover {
    background: #1d4ed8;
}

.btn-green {
    background: #16a34a;
}

.btn-red {
    background: #dc2626;
}

.btn-gray {
    background: #64748b;
}

.tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
}

.tabs a {
    background: white;
    padding: 10px 15px;
    border-radius: 9px;
    text-decoration: none;
    color: #172033;
}

.tabs a.active {
    background: #2563eb;
    color: white;
}

.schedule-item {
    border-left: 5px solid #2563eb;
    padding: 15px;
    background: white;
    margin-bottom: 12px;
    border-radius: 10px;
}

.task {
    border: 1px solid #e1e6f0;
    padding: 15px;
    margin-bottom: 12px;
    border-radius: 12px;
    background: white;
}

.progress {
    background: #e5e7eb;
    border-radius: 20px;
    height: 12px;
    overflow: hidden;
    margin: 10px 0;
}

.progress-bar {
    background: #2563eb;
    height: 100%;
}

.badge {
    padding: 5px 9px;
    border-radius: 20px;
    font-size: 12px;
    background: #e0e7ff;
    color: #3730a3;
}

.alert {
    padding: 12px;
    background: #dbeafe;
    border-radius: 10px;
    margin-bottom: 15px;
}

.danger {
    background: #fee2e2;
    color: #991b1b;
}

.success {
    background: #dcfce7;
    color: #166534;
}

.login-box {
    max-width: 430px;
    margin: 60px auto;
}

footer {
    text-align: center;
    color: #64748b;
    padding: 30px;
}

.small {
    color: #64748b;
    font-size: 13px;
}

@media(max-width:700px) {

    nav {
        flex-direction: column;
        gap: 12px;
        align-items: flex-start;
    }

    .container {
        padding: 15px;
    }

    .hero {
        padding: 25px;
    }
}

"""


# =========================================================
# BASE TEMPLATE
# =========================================================

BASE = """

<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>{{ title }} - StudySched</title>

<style>
{{ css }}
</style>

</head>

<body>

<nav>

<div class="logo">
📚 StudySched
</div>

<div class="navlinks">

{% if user %}

<a href="{{ url_for('dashboard') }}">Dashboard</a>
<a href="{{ url_for('schedule') }}">Schedule</a>
<a href="{{ url_for('groups') }}">Groups</a>

{% if user['is_admin'] %}
<a href="{{ url_for('admin') }}">Admin</a>
{% endif %}

<a href="{{ url_for('logout') }}">Logout</a>

{% else %}

<a href="{{ url_for('login') }}">Login</a>
<a href="{{ url_for('register') }}">Register</a>

{% endif %}

</div>

</nav>

<div class="container">

{% with messages = get_flashed_messages() %}

{% for message in messages %}

<div class="alert">
{{ message }}
</div>

{% endfor %}

{% endwith %}

{{ content|safe }}

</div>

<footer>
StudySched — Student Schedule & Group Project Manager
</footer>

<script>

let notificationReady = false;

async function enableNotifications() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") {
        const permission = await Notification.requestPermission();
        notificationReady = permission === "granted";
    } else {
        notificationReady = Notification.permission === "granted";
    }

    if ("serviceWorker" in navigator) {
        try {
            await navigator.serviceWorker.register("/sw.js");
        } catch (e) {}
    }
}

function notifyUser(title, message, key) {
    if (!notificationReady) return;
    const storageKey = "studysched_notified_" + key;
    if (localStorage.getItem(storageKey)) return;
    localStorage.setItem(storageKey, "1");

    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
        navigator.serviceWorker.ready.then(reg => {
            reg.showNotification(title, {
                body: message,
                icon: "/icon.svg",
                tag: key
            });
        });
    } else {
        new Notification(title, {body: message, icon: "/icon.svg"});
    }
}

async function checkSchedules() {
    try {
        const response = await fetch("/api/upcoming", {credentials: "same-origin"});
        if (!response.ok) return;
        const schedules = await response.json();
        schedules.forEach(item => {
            notifyUser(
                "📚 StudySched Reminder",
                item.title + " is starting soon!",
                item.id + "_" + item.schedule_date + "_" + item.schedule_time
            );
        });
    } catch(e) {}
}

enableNotifications().then(checkSchedules);
setInterval(checkSchedules, 30000);

</script>

</body>
</html>

"""


def render_page(title, content, **context):

    html = render_template_string(
        BASE,
        title=title,
        content=content,
        css=CSS,
        user=current_user(),
        **context
    )

    return html


# =========================================================
# LANDING
# =========================================================

@app.route("/")
def index():

    if current_user():
        return redirect(url_for("dashboard"))

    content = """

<div class="hero">

<h1>📚 StudySched</h1>

<h2>Your smarter student planner.</h2>

<p>
Organize your classes, study schedule and group projects
in one simple system.
</p>

<a class="btn" href="/register">
Get Started
</a>

<a class="btn btn-gray" href="/login">
Login
</a>

</div>

<div class="cards">

<div class="card">
<h3>📅 Smart Schedule</h3>
<p>Keep your classes, study sessions and deadlines organized.</p>
</div>

<div class="card">
<h3>🔔 Reminders</h3>
<p>Receive browser notifications when your schedule is coming up.</p>
</div>

<div class="card">
<h3>👥 Group Projects</h3>
<p>Create groups, assign tasks and monitor project progress.</p>
</div>

<div class="card">
<h3>📊 Progress Tracking</h3>
<p>See which tasks are pending, active or completed.</p>
</div>

</div>

"""

    return render_page("Home", content)


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form["username"].strip()
        full_name = request.form["full_name"].strip()
        password = request.form["password"]

        if not username or not full_name or not password:
            flash("Please complete all fields.")
            return redirect(url_for("register"))

        existing = execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
            fetch=True
        )

        if existing:
            flash("Username already exists.")
            return redirect(url_for("register"))

        execute("""
        INSERT INTO users
        (username, password, full_name)
        VALUES (?, ?, ?)
        """, (
            username,
            generate_password_hash(password),
            full_name
        ))

        flash("Account created. You can now login.")
        return redirect(url_for("login"))

    content = """

<div class="login-box">

<div class="card">

<h2>📚 Create StudySched Account</h2>

<form method="POST">

<label>Full Name</label>
<input name="full_name" required>

<label>Username</label>
<input name="username" required>

<label>Password</label>
<input type="password" name="password" required>

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

    return render_page("Register", content)


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        users = execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
            fetch=True
        )

        if not users:
            flash("Invalid username or password.")
            return redirect(url_for("login"))

        user = users[0]

        if not check_password_hash(user["password"], password):
            flash("Invalid username or password.")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]

        return redirect(url_for("dashboard"))

    content = """

<div class="login-box">

<div class="card">

<h2>🔐 Login</h2>

<form method="POST">

<label>Username</label>
<input name="username" required>

<label>Password</label>
<input type="password" name="password" required>

<button type="submit">
Login
</button>

</form>

<p>
No account?
<a href="/register">Create one</a>
</p>

</div>

</div>

"""

    return render_page("Login", content)


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("index"))


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = current_user()

    schedules = execute("""
    SELECT *
    FROM schedules
    WHERE user_id = ?
    ORDER BY schedule_date, schedule_time
    """, (user["id"],), fetch=True)

    groups = execute("""
    SELECT g.*
    FROM groups g
    JOIN group_members gm
    ON gm.group_id = g.id
    WHERE gm.user_id = ?
    """, (user["id"],), fetch=True)

    tasks = execute("""
    SELECT t.*
    FROM tasks t
    JOIN group_members gm
    ON gm.group_id = t.group_id
    WHERE gm.user_id = ?
    AND t.status != 'Completed'
    """, (user["id"],), fetch=True)

    content = """

<div class="hero">

<h1>Welcome, {{ user["full_name"] }} 👋</h1>

<p>
Stay organized, keep track of your studies,
and work better with your groupmates.
</p>

</div>

<div class="cards">

<div class="card">
<div class="stat">{{ schedules|length }}</div>
<p>Schedules</p>
</div>

<div class="card">
<div class="stat">{{ groups|length }}</div>
<p>Groups</p>
</div>

<div class="card">
<div class="stat">{{ tasks|length }}</div>
<p>Active Tasks</p>
</div>

</div>

<div class="card">

<h2>📅 Upcoming Schedule</h2>

{% if schedules %}

{% for item in schedules[:5] %}

<div class="schedule-item">

<strong>{{ item["title"] }}</strong>

<p>
{{ item["schedule_date"] }}
at
{{ item["schedule_time"] }}
</p>

{% if item["description"] %}
<p>{{ item["description"] }}</p>
{% endif %}

<span class="badge">
Reminder {{ item["reminder_minutes"] }} min before
</span>

</div>

{% endfor %}

{% else %}

<p>No schedules yet.</p>

<a class="btn" href="/schedule">
Add Schedule
</a>

{% endif %}

</div>

<div class="card">

<h2>👥 My Groups</h2>

{% if groups %}

{% for group in groups %}

<p>
<strong>{{ group["name"] }}</strong>
<br>
<span class="small">
Join Code: {{ group["join_code"] }}
</span>
</p>

{% endfor %}

{% else %}

<p>You are not part of a group yet.</p>

<a class="btn" href="/groups">
Manage Groups
</a>

{% endif %}

</div>

"""

    return render_page(
        "Dashboard",
        render_template_string(
            content,
            user=user,
            schedules=schedules,
            groups=groups,
            tasks=tasks
        )
    )


# =========================================================
# SCHEDULE
# =========================================================

@app.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():

    user = current_user()

    if request.method == "POST":

        title = request.form["title"]
        description = request.form.get("description", "")
        date = request.form["date"]
        time = request.form["time"]

        reminder = int(
            request.form.get("reminder_minutes", 10)
        )

        execute("""
        INSERT INTO schedules
        (user_id, title, description, schedule_date,
         schedule_time, reminder_minutes)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user["id"],
            title,
            description,
            date,
            time,
            reminder
        ))

        flash("Schedule added successfully.")

        return redirect(url_for("schedule"))

    schedules = execute("""
    SELECT *
    FROM schedules
    WHERE user_id = ?
    ORDER BY schedule_date, schedule_time
    """, (user["id"],), fetch=True)

    content = """

<div class="tabs">

<a class="active" href="/schedule">
📅 My Schedule
</a>

<a href="/groups">
👥 Groups
</a>

</div>

<div class="card">

<h2>➕ Add Schedule</h2>

<form method="POST">

<label>Subject / Activity</label>
<input name="title"
placeholder="Example: Database Study"
required>

<label>Description</label>
<textarea name="description"
placeholder="What will you study?"></textarea>

<label>Date</label>
<input type="date" name="date" required>

<label>Time</label>
<input type="time" name="time" required>

<label>Reminder</label>

<select name="reminder_minutes">

<option value="0">At schedule time</option>
<option value="5">5 minutes before</option>
<option value="10" selected>10 minutes before</option>
<option value="15">15 minutes before</option>
<option value="30">30 minutes before</option>
<option value="60">1 hour before</option>

</select>

<button type="submit">
Add Schedule
</button>

</form>

</div>

<div class="card">

<h2>📅 My Schedules</h2>

{% if schedules %}

{% for item in schedules %}

<div class="schedule-item">

<h3>{{ item["title"] }}</h3>

<p>
<strong>
{{ item["schedule_date"] }}
—
{{ item["schedule_time"] }}
</strong>
</p>

<p>
{{ item["description"] }}
</p>

<span class="badge">
Reminder: {{ item["reminder_minutes"] }} minutes before
</span>

</div>

{% endfor %}

{% else %}

<p>No schedule added yet.</p>

{% endif %}

</div>

"""

    return render_page(
        "Schedule",
        render_template_string(
            content,
            schedules=schedules
        )
    )


# =========================================================
# UPCOMING API FOR NOTIFICATIONS
# =========================================================

@app.route("/api/upcoming")
@login_required
def upcoming():

    user = current_user()

    schedules = execute("""
    SELECT *
    FROM schedules
    WHERE user_id = ?
    """, (user["id"],), fetch=True)

    now = datetime.now(ZoneInfo("Asia/Manila"))

    result = []

    for item in schedules:

        try:

            schedule_dt = datetime.strptime(
                item["schedule_date"] + " " +
                item["schedule_time"],
                "%Y-%m-%d %H:%M"
            ).replace(tzinfo=ZoneInfo("Asia/Manila"))

            seconds = (
                schedule_dt - now
            ).total_seconds()

            reminder_seconds = (
                item["reminder_minutes"] * 60
            )

            if (
                reminder_seconds >= seconds >= -30
            ):

                result.append({
                    "id": item["id"],
                    "title": item["title"],
                    "schedule_date": item["schedule_date"],
                    "schedule_time": item["schedule_time"]
                })

        except:
            pass

    return jsonify(result)


# =========================================================
# GROUPS
# =========================================================

@app.route("/groups", methods=["GET", "POST"])
@login_required
def groups():

    user = current_user()

    if request.method == "POST":

        action = request.form.get("action")

        if action == "create":

            name = request.form["name"]
            description = request.form.get(
                "description", ""
            )

            join_code = secrets.token_hex(4).upper()

            execute("""
            INSERT INTO groups
            (name, description, join_code, owner_id)
            VALUES (?, ?, ?, ?)
            """, (
                name,
                description,
                join_code,
                user["id"]
            ))

            group = execute("""
            SELECT id FROM groups
            WHERE join_code = ?
            """, (join_code,), fetch=True)

            group_id = group[0]["id"]

            execute("""
            INSERT INTO group_members
            (group_id, user_id)
            VALUES (?, ?)
            """, (
                group_id,
                user["id"]
            ))

            add_activity(
                group_id,
                user["id"],
                "Created the group."
            )

            flash(
                "Group created. Join Code: " +
                join_code
            )

        elif action == "join":

            code = request.form["join_code"].strip().upper()

            found = execute("""
            SELECT *
            FROM groups
            WHERE join_code = ?
            """, (code,), fetch=True)

            if not found:

                flash("Group code not found.")

            else:

                group = found[0]

                existing = execute("""
                SELECT id
                FROM group_members
                WHERE group_id = ?
                AND user_id = ?
                """, (
                    group["id"],
                    user["id"]
                ), fetch=True)

                if existing:

                    flash("You are already in this group.")

                else:

                    execute("""
                    INSERT INTO group_members
                    (group_id, user_id)
                    VALUES (?, ?)
                    """, (
                        group["id"],
                        user["id"]
                    ))

                    add_activity(
                        group["id"],
                        user["id"],
                        "Joined the group."
                    )

                    flash("Joined group successfully.")

        return redirect(url_for("groups"))

    groups = execute("""
    SELECT g.*
    FROM groups g
    JOIN group_members gm
    ON gm.group_id = g.id
    WHERE gm.user_id = ?
    """, (user["id"],), fetch=True)

    content = """

<div class="card">

<h2>👥 Create a Group</h2>

<form method="POST">

<input type="hidden"
name="action"
value="create">

<label>Group Name</label>

<input
name="name"
placeholder="Example: Web System Project"
required>

<label>Description</label>

<textarea
name="description"
placeholder="Describe your project">
</textarea>

<button>
Create Group
</button>

</form>

</div>

<div class="card">

<h2>🔑 Join a Group</h2>

<form method="POST">

<input type="hidden"
name="action"
value="join">

<label>Group Code</label>

<input
name="join_code"
placeholder="Example: A1B2C3D4"
required>

<button>
Join Group
</button>

</form>

</div>

<div class="card">

<h2>👥 My Groups</h2>

{% if groups %}

{% for group in groups %}

<div class="task">

<h3>{{ group["name"] }}</h3>

<p>{{ group["description"] }}</p>

<p>
<strong>Join Code:</strong>
{{ group["join_code"] }}
</p>

<a class="btn"
href="/group/{{ group["id"] }}">
Open Group
</a>

</div>

{% endfor %}

{% else %}

<p>No groups yet.</p>

{% endif %}

</div>

"""

    return render_page(
        "Groups",
        render_template_string(
            content,
            groups=groups
        )
    )


# =========================================================
# GROUP PAGE
# =========================================================

@app.route(
    "/group/<int:group_id>",
    methods=["GET", "POST"]
)
@login_required
def group_page(group_id):

    user = current_user()

    member = execute("""
    SELECT *
    FROM group_members
    WHERE group_id = ?
    AND user_id = ?
    """, (
        group_id,
        user["id"]
    ), fetch=True)

    if not member:
        return "You are not a member of this group.", 403

    group_result = execute("""
    SELECT *
    FROM groups
    WHERE id = ?
    """, (group_id,), fetch=True)

    if not group_result:
        return "Group not found.", 404

    group = group_result[0]

    if request.method == "POST":

        title = request.form["title"]
        description = request.form.get(
            "description", ""
        )
        assigned_to = request.form.get(
            "assigned_to"
        )
        deadline = request.form.get(
            "deadline", ""
        )

        assigned_to = (
            int(assigned_to)
            if assigned_to else None
        )

        if assigned_to is not None:
            valid_assignee = execute("""
            SELECT id FROM group_members
            WHERE group_id = ? AND user_id = ?
            """, (group_id, assigned_to), fetch=True)
            if not valid_assignee:
                flash("That student is not a member of this group.")
                return redirect(url_for("group_page", group_id=group_id))

        execute("""
        INSERT INTO tasks
        (group_id, title, description,
         assigned_to, deadline)
        VALUES (?, ?, ?, ?, ?)
        """, (
            group_id,
            title,
            description,
            assigned_to,
            deadline
        ))

        add_activity(
            group_id,
            user["id"],
            "Created task: " + title
        )

        flash("Task created.")

        return redirect(
            url_for(
                "group_page",
                group_id=group_id
            )
        )

    members = execute("""
    SELECT u.*
    FROM users u
    JOIN group_members gm
    ON gm.user_id = u.id
    WHERE gm.group_id = ?
    """, (group_id,), fetch=True)

    tasks = execute("""
    SELECT
        t.*,
        u.full_name AS assigned_name
    FROM tasks t
    LEFT JOIN users u
    ON u.id = t.assigned_to
    WHERE t.group_id = ?
    ORDER BY t.deadline
    """, (group_id,), fetch=True)

    activity = execute("""
    SELECT
        a.*,
        u.full_name
    FROM activity a
    JOIN users u
    ON u.id = a.user_id
    WHERE a.group_id = ?
    ORDER BY a.created_at DESC
    LIMIT 20
    """, (group_id,), fetch=True)

    total = len(tasks)

    completed = len([
        t for t in tasks
        if t["status"] == "Completed"
    ])

    progress = (
        round((completed / total) * 100)
        if total else 0
    )

    content = """

<div class="hero">

<h1>👥 {{ group["name"] }}</h1>

<p>{{ group["description"] }}</p>

<p>
<strong>Join Code:</strong>
{{ group["join_code"] }}
</p>

</div>

<div class="card">

<h2>📊 Project Progress</h2>

<h1>{{ progress }}%</h1>

<div class="progress">

<div class="progress-bar"
style="width: {{ progress }}%">
</div>

</div>

<p>
{{ completed }} of {{ total }} tasks completed.
</p>

</div>

<div class="card">

<h2>➕ Add Group Task</h2>

<form method="POST">

<label>Task</label>

<input
name="title"
placeholder="Example: Research Chapter 1"
required>

<label>Description</label>

<textarea
name="description"
placeholder="What needs to be done?">
</textarea>

<label>Assign To</label>

<select name="assigned_to">

<option value="">
Unassigned
</option>

{% for member in members %}

<option value="{{ member["id"] }}">
{{ member["full_name"] }}
</option>

{% endfor %}

</select>

<label>Deadline</label>

<input
type="datetime-local"
name="deadline">

<button>
Add Task
</button>

</form>

</div>

<div class="card">

<h2>📋 Project Tasks</h2>

{% if tasks %}

{% for task in tasks %}

<div class="task">

<h3>
{{ task["title"] }}
</h3>

<p>
{{ task["description"] }}
</p>

<p>

<strong>Assigned:</strong>

{% if task["assigned_name"] %}
{{ task["assigned_name"] }}
{% else %}
Not assigned
{% endif %}

</p>

<p>

<strong>Deadline:</strong>

{{ task["deadline"] or "No deadline" }}

</p>

<span class="badge">
{{ task["status"] }}
</span>

<div class="progress">

<div class="progress-bar"
style="width: {{ task["progress"] }}%">
</div>

</div>

<p>
Progress:
{{ task["progress"] }}%
</p>

<a class="btn"
href="/task/{{ task["id"] }}">
Update Task
</a>

</div>

{% endfor %}

{% else %}

<p>No tasks yet.</p>

{% endif %}

</div>

<div class="card">

<h2>👤 Group Members</h2>

{% for member in members %}

<p>
<strong>{{ member["full_name"] }}</strong>
<br>
<span class="small">
@{{ member["username"] }}
</span>
</p>

{% endfor %}

</div>

<div class="card">

<h2>🕒 Recent Activity</h2>

{% for item in activity %}

<p>
<strong>{{ item["full_name"] }}</strong>
{{ item["message"] }}

<br>

<span class="small">
{{ item["created_at"] }}
</span>

</p>

{% endfor %}

</div>

"""

    return render_page(
        group["name"],
        render_template_string(
            content,
            group=group,
            members=members,
            tasks=tasks,
            activity=activity,
            progress=progress,
            completed=completed,
            total=total
        )
    )


# =========================================================
# UPDATE TASK
# =========================================================

@app.route(
    "/task/<int:task_id>",
    methods=["GET", "POST"]
)
@login_required
def update_task(task_id):

    user = current_user()

    task_result = execute("""
    SELECT *
    FROM tasks
    WHERE id = ?
    """, (task_id,), fetch=True)

    if not task_result:
        return "Task not found.", 404

    task = task_result[0]

    member = execute("""
    SELECT *
    FROM group_members
    WHERE group_id = ?
    AND user_id = ?
    """, (
        task["group_id"],
        user["id"]
    ), fetch=True)

    if not member:
        return "Unauthorized.", 403

    if request.method == "POST":

        status = request.form["status"]

        progress = int(
            request.form["progress"]
        )

        proof = request.form.get(
            "proof", ""
        )

        if progress < 0:
            progress = 0

        if progress > 100:
            progress = 100

        if progress == 100:
            status = "Completed"

        execute("""
        UPDATE tasks
        SET status = ?,
            progress = ?,
            proof = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (
            status,
            progress,
            proof,
            task_id
        ))

        add_activity(
            task["group_id"],
            user["id"],
            "Updated task progress: " +
            str(progress) + "%"
        )

        flash("Task updated.")

        return redirect(
            url_for(
                "group_page",
                group_id=task["group_id"]
            )
        )

    content = """

<div class="card">

<h2>📝 Update Task</h2>

<h3>{{ task["title"] }}</h3>

<p>
{{ task["description"] }}
</p>

<form method="POST">

<label>Status</label>

<select name="status">

<option
value="Pending"
{% if task["status"] == "Pending" %}
selected
{% endif %}>
Pending
</option>

<option
value="In Progress"
{% if task["status"] == "In Progress" %}
selected
{% endif %}>
In Progress
</option>

<option
value="Completed"
{% if task["status"] == "Completed" %}
selected
{% endif %}>
Completed
</option>

</select>

<label>Progress (%)</label>

<input
type="number"
name="progress"
min="0"
max="100"
value="{{ task["progress"] }}"
required>

<label>Proof / Work Update</label>

<textarea
name="proof"
placeholder="Describe what you completed, such as research, document, code, design, etc.">{{ task["proof"] or "" }}</textarea>

<button>
Save Progress
</button>

</form>

</div>

"""

    return render_page(
        "Update Task",
        render_template_string(
            content,
            task=task
        )
    )


# =========================================================
# ADMIN
# =========================================================

@app.route("/admin")
@admin_required
def admin():

    users = execute(
        "SELECT * FROM users ORDER BY created_at DESC",
        fetch=True
    )

    groups = execute(
        "SELECT * FROM groups ORDER BY created_at DESC",
        fetch=True
    )

    tasks = execute(
        "SELECT * FROM tasks ORDER BY created_at DESC",
        fetch=True
    )

    content = """

<div class="hero">

<h1>🛡️ Admin Dashboard</h1>

<p>
Manage the StudySched system.
</p>

</div>

<div class="cards">

<div class="card">
<div class="stat">{{ users|length }}</div>
<p>Users</p>
</div>

<div class="card">
<div class="stat">{{ groups|length }}</div>
<p>Groups</p>
</div>

<div class="card">
<div class="stat">{{ tasks|length }}</div>
<p>Tasks</p>
</div>

</div>

<div class="card">

<h2>👨‍🎓 Registered Students</h2>

{% for user in users %}

<p>
<strong>{{ user["full_name"] }}</strong>
<br>
@{{ user["username"] }}

{% if user["is_admin"] %}
<span class="badge">ADMIN</span>
{% endif %}

</p>

{% endfor %}

</div>

<div class="card">

<h2>👥 Groups</h2>

{% for group in groups %}

<p>

<strong>
{{ group["name"] }}
</strong>

<br>

Code:
{{ group["join_code"] }}

</p>

{% endfor %}

</div>

"""

    return render_page(
        "Admin",
        render_template_string(
            content,
            users=users,
            groups=groups,
            tasks=tasks
        )
    )


# =========================================================
# SERVICE WORKER
# =========================================================

@app.route("/sw.js")
def service_worker():

    return """

self.addEventListener("install", event => {
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", event => {

    event.notification.close();

    event.waitUntil(
        clients.openWindow("/")
    );

});

""", 200, {
        "Content-Type": "application/javascript"
    }


# =========================================================
# ICON
# =========================================================

@app.route("/icon.svg")
def icon():

    return """

<svg xmlns="http://www.w3.org/2000/svg"
width="128"
height="128">

<rect width="128"
height="128"
rx="25"
fill="#2563eb"/>

<text
x="64"
y="82"
font-size="65"
text-anchor="middle"
fill="white">
📚
</text>

</svg>

""", 200, {
        "Content-Type": "image/svg+xml"
    }


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
