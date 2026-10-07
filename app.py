import os
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import wraps

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    render_template_string,
    jsonify,
    flash
)

from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)

app.secret_key = (
    os.environ.get("SECRET_KEY")
    or secrets.token_hex(32)
)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

USE_POSTGRES = DATABASE_URL.startswith("postgresql://")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

TIMEZONE = ZoneInfo("Asia/Manila")


# =========================================================
# DATABASE
# =========================================================

if USE_POSTGRES:

    import psycopg2
    from psycopg2.extras import RealDictCursor

    def get_db():
        return psycopg2.connect(DATABASE_URL)

    def execute(query, params=(), fetch=False, many=False):

        db = get_db()
        cur = db.cursor(cursor_factory=RealDictCursor)

        query = query.replace("?", "%s")

        query = query.replace(
            "id INTEGER PRIMARY KEY",
            "id SERIAL PRIMARY KEY"
        )

        try:

            if many:
                cur.executemany(query, params)
            else:
                cur.execute(query, params)

            result = cur.fetchall() if fetch else None

            db.commit()

            return result

        finally:
            cur.close()
            db.close()

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

        try:

            if many:
                cur.executemany(query, params)
            else:
                cur.execute(query, params)

            result = cur.fetchall() if fetch else None

            db.commit()

            return result

        finally:
            cur.close()
            db.close()


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
            is_premium INTEGER DEFAULT 0,
            premium_until TIMESTAMP,
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
            is_deleted INTEGER DEFAULT 0,
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

    execute("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            role VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    admin = execute(
        "SELECT id FROM users WHERE username = ?",
        (ADMIN_USERNAME,),
        fetch=True
    )

    if not admin:

        execute("""
            INSERT INTO users
            (
                username,
                password,
                full_name,
                is_admin,
                is_premium
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            ADMIN_USERNAME,
            generate_password_hash(ADMIN_PASSWORD),
            "StudySched Administrator",
            1,
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


def is_premium_active(user):

    if not user:
        return False

    if not user["is_premium"]:
        return False

    premium_until = user["premium_until"]

    if not premium_until:
        return True

    try:

        if isinstance(premium_until, datetime):

            expiry = premium_until

            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=TIMEZONE)

        else:

            value = str(premium_until)

            expiry = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=TIMEZONE)

        return expiry > datetime.now(TIMEZONE)

    except Exception:
        return True


def premium_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        user = current_user()

        if not user:
            return redirect(url_for("login"))

        if not is_premium_active(user):

            flash(
                "✨ This feature requires Premium access.",
                "info"
            )

            return redirect(url_for("premium"))

        return func(*args, **kwargs)

    return wrapper


def add_activity(group_id, user_id, message):

    execute("""
        INSERT INTO activity
        (group_id, user_id, message)
        VALUES (?, ?, ?)
    """, (
        group_id,
        user_id,
        message
    ))


# =========================================================
# AI
# =========================================================

def ai_response(message, user):

    msg = message.lower()

    responses = {

        "schedule":
            "📅 I can help you organize your study schedule. "
            "Add your subjects, deadlines, and study sessions in the Schedule page.",

        "study":
            "🧠 Try studying for 25–50 minutes followed by a short break. "
            "Start with the most difficult subject while your energy is high.",

        "exam":
            "📖 For exam preparation: review your notes, practice questions, "
            "quiz yourself, and review difficult topics.",

        "group":
            "👥 You can create or join a group using a group code. "
            "Inside the group, members can be assigned tasks and track progress.",

        "task":
            "✅ Break large projects into smaller tasks. "
            "Assign each task, set a deadline, update progress, and provide proof of work.",

        "progress":
            "📊 Keep your task progress updated. "
            "Regular updates make it easier for your group to see who is working on each task.",

        "premium":
            "✨ Premium includes the AI Study Assistant and other advanced StudySched features.",

        "hello":
            f"Hello {user['full_name']}! 👋 "
            "I'm your StudySched AI Assistant.",

        "help":
            "I can help with 📅 schedules, 🧠 study tips, "
            "👥 group projects, ✅ tasks, and 📊 productivity."
    }

    for keyword, reply in responses.items():

        if keyword in msg:
            return reply

    return (
        "I'm here to help! 💬 "
        "Ask me about schedules, studying, group projects, "
        "tasks, or productivity."
    )


# =========================================================
# CSS
# =========================================================

CSS = """
:root {
    --primary: #4f46e5;
    --primary-dark: #3730a3;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --bg: #f8fafc;
    --text: #1e293b;
    --muted: #64748b;
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: "Segoe UI", Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}

nav {
    background: white;
    padding: 14px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 2px 15px rgba(0,0,0,.06);
    position: sticky;
    top: 0;
    z-index: 100;
}

.logo {
    font-size: 22px;
    font-weight: 800;
    color: var(--primary);
}

.navlinks {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}

.navlinks a {
    text-decoration: none;
    color: #475569;
    padding: 9px 14px;
    border-radius: 10px;
}

.navlinks a:hover {
    background: #eef2ff;
    color: var(--primary);
}

.premium-link {
    background: linear-gradient(135deg,#f59e0b,#facc15);
    color: #78350f !important;
    font-weight: 700;
}

.container {
    max-width: 1200px;
    margin: auto;
    padding: 32px 20px;
}

.hero {
    background: linear-gradient(135deg,#4f46e5,#7c3aed);
    color: white;
    padding: 45px;
    border-radius: 24px;
    margin-bottom: 30px;
    box-shadow: 0 20px 50px rgba(79,70,229,.22);
}

.hero h1 {
    font-size: 36px;
    margin-bottom: 10px;
}

.hero p {
    font-size: 17px;
    opacity: .9;
}

.cards {
    display: grid;
    grid-template-columns: repeat(auto-fit,minmax(230px,1fr));
    gap: 22px;
    margin-bottom: 25px;
}

.card {
    background: white;
    padding: 25px;
    border-radius: 18px;
    box-shadow: 0 8px 30px rgba(0,0,0,.06);
    margin-bottom: 20px;
}

.card:hover {
    box-shadow: 0 12px 35px rgba(0,0,0,.09);
}

.stat {
    font-size: 35px;
    font-weight: 800;
    color: var(--primary);
}

h2 {
    margin-bottom: 18px;
}

h3 {
    margin-bottom: 8px;
}

input,
textarea,
select {
    width: 100%;
    padding: 13px 15px;
    margin: 7px 0 15px;
    border: 2px solid #e2e8f0;
    border-radius: 11px;
    font-size: 15px;
}

textarea {
    min-height: 100px;
    resize: vertical;
}

input:focus,
textarea:focus,
select:focus {
    outline: none;
    border-color: var(--primary);
}

button,
.btn {
    border: none;
    padding: 12px 20px;
    border-radius: 10px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
    font-weight: 600;
}

.btn-primary {
    background: var(--primary);
    color: white;
}

.btn-primary:hover {
    background: var(--primary-dark);
}

.btn-green {
    background: var(--success);
    color: white;
}

.btn-red {
    background: var(--danger);
    color: white;
}

.btn-outline {
    background: white;
    border: 2px solid var(--primary);
    color: var(--primary);
}

.btn-warning {
    background: var(--warning);
    color: white;
}

.badge {
    display: inline-block;
    padding: 5px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
}

.badge-pending {
    background: #fef3c7;
    color: #92400e;
}

.badge-progress {
    background: #dbeafe;
    color: #1e40af;
}

.badge-done {
    background: #d1fae5;
    color: #065f46;
}

.premium-badge {
    display: inline-block;
    background: linear-gradient(135deg,#f59e0b,#facc15);
    color: #78350f;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 800;
}

.schedule-item {
    background: white;
    border-left: 4px solid var(--primary);
    padding: 18px;
    margin-bottom: 15px;
    border-radius: 0 14px 14px 0;
}

.schedule-past {
    opacity: .65;
    border-left-color: #94a3b8;
}

.task {
    border: 2px solid #f1f5f9;
    padding: 18px;
    border-radius: 15px;
    margin-bottom: 15px;
}

.progress {
    background: #e2e8f0;
    height: 10px;
    border-radius: 20px;
    overflow: hidden;
    margin: 10px 0;
}

.progress-bar {
    background: var(--success);
    height: 100%;
    border-radius: 20px;
}

.alert {
    padding: 13px 17px;
    border-radius: 10px;
    margin-bottom: 18px;
}

.alert-success {
    background: #dcfce7;
    color: #166534;
}

.alert-danger {
    background: #fee2e2;
    color: #991b1b;
}

.alert-info {
    background: #eef2ff;
    color: #3730a3;
}

.login-box {
    max-width: 430px;
    margin: 70px auto;
}

.small {
    color: var(--muted);
    font-size: 13px;
}

.activity {
    padding: 10px 0;
    border-bottom: 1px solid #e2e8f0;
}

.ai-toggle {
    position: fixed;
    right: 25px;
    bottom: 25px;
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: linear-gradient(135deg,#4f46e5,#7c3aed);
    color: white;
    font-size: 25px;
    z-index: 998;
    box-shadow: 0 5px 25px rgba(79,70,229,.35);
}

.ai-chat {
    position: fixed;
    right: 25px;
    bottom: 25px;
    width: 380px;
    max-width: calc(100% - 30px);
    background: white;
    border-radius: 18px;
    box-shadow: 0 15px 50px rgba(0,0,0,.2);
    overflow: hidden;
    z-index: 999;
}

.ai-header {
    background: linear-gradient(135deg,#4f46e5,#7c3aed);
    color: white;
    padding: 15px;
    display: flex;
    justify-content: space-between;
}

.ai-body {
    padding: 15px;
    height: 330px;
    overflow-y: auto;
}

.ai-bubble {
    padding: 10px 13px;
    border-radius: 15px;
    margin-bottom: 10px;
    max-width: 85%;
}

.ai-bot {
    background: #eef2ff;
    color: #3730a3;
}

.ai-user {
    background: var(--primary);
    color: white;
    margin-left: auto;
}

.ai-input {
    display: flex;
    gap: 7px;
    padding: 10px;
    border-top: 1px solid #e2e8f0;
}

.ai-input input {
    margin: 0;
}

.hidden {
    display: none !important;
}

footer {
    text-align: center;
    padding: 35px;
    color: #94a3b8;
}

@media(max-width:768px) {

    nav {
        flex-direction: column;
        gap: 12px;
    }

    .hero {
        padding: 30px 22px;
    }

    .hero h1 {
        font-size: 28px;
    }

    .navlinks {
        justify-content: center;
    }

    .ai-chat {
        right: 15px;
        bottom: 15px;
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

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

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

<a href="{{ url_for('dashboard') }}">
Dashboard
</a>

<a href="{{ url_for('schedule') }}">
Schedule
</a>

<a href="{{ url_for('groups') }}">
Groups
</a>

<a
href="{{ url_for('premium') }}"
class="premium-link"
>
✨ Premium
</a>

{% if user["is_admin"] %}

<a href="{{ url_for('admin') }}">
Admin
</a>

{% endif %}

<a href="{{ url_for('logout') }}">
Logout
</a>

{% else %}

<a href="{{ url_for('login') }}">
Login
</a>

<a href="{{ url_for('register') }}">
Register
</a>

{% endif %}

</div>

</nav>

<div class="container">

{% with messages = get_flashed_messages(with_categories=true) %}

{% for category, message in messages %}

<div class="alert alert-{{ category }}">
{{ message }}
</div>

{% endfor %}

{% endwith %}

{{ content|safe }}

</div>


{% if user and is_premium_active(user) %}

<button
class="ai-toggle"
id="aiToggle"
onclick="toggleChat()"
>
🤖
</button>


<div
class="ai-chat hidden"
id="aiChatBox"
>

<div class="ai-header">

<strong>
🤖 AI Study Assistant
</strong>

<button
onclick="toggleChat()"
style="
background:none;
border:none;
color:white;
font-size:22px;
"
>
×
</button>

</div>


<div
class="ai-body"
id="aiBody"
>

<div class="ai-bubble ai-bot">

Hi! I'm your StudySched AI Assistant. 👋

<br><br>

Ask me about schedules, studying,
group projects, tasks, or productivity.

</div>

</div>


<form
class="ai-input"
onsubmit="sendAiMsg(event)"
>

<input
id="aiInput"
placeholder="Ask something..."
required
>

<button
class="btn-primary"
type="submit"
>
Send
</button>

</form>

</div>

{% endif %}


<footer>
StudySched © 2026 — Smart Study, Better Results ✨
</footer>


<script>

function toggleChat() {

    const box =
        document.getElementById("aiChatBox");

    const toggle =
        document.getElementById("aiToggle");

    if (!box) return;

    box.classList.toggle("hidden");

    if (toggle) {
        toggle.classList.toggle(
            "hidden",
            !box.classList.contains("hidden")
        );
    }
}


async function sendAiMsg(event) {

    event.preventDefault();

    const input =
        document.getElementById("aiInput");

    const body =
        document.getElementById("aiBody");

    if (!input || !body) return;

    const message =
        input.value.trim();

    if (!message) return;

    body.innerHTML +=
        '<div class="ai-bubble ai-user">' +
        escapeHtml(message) +
        '</div>';

    input.value = "";

    body.innerHTML +=
        '<div class="ai-bubble ai-bot" id="aiLoading">Thinking...</div>';

    body.scrollTop = body.scrollHeight;

    try {

        const response =
            await fetch("/api/ai-chat", {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    message: message
                })

            });

        const data =
            await response.json();

        const loading =
            document.getElementById("aiLoading");

        if (loading) {
            loading.remove();
        }

        body.innerHTML +=
            '<div class="ai-bubble ai-bot">' +
            escapeHtml(data.reply || "Sorry, I could not answer.") +
            '</div>';

    } catch (error) {

        const loading =
            document.getElementById("aiLoading");

        if (loading) {
            loading.remove();
        }

        body.innerHTML +=
            '<div class="ai-bubble ai-bot">' +
            'Sorry, something went wrong.' +
            '</div>';
    }

    body.scrollTop = body.scrollHeight;
}


function escapeHtml(text) {

    const div = document.createElement("div");

    div.textContent = text;

    return div.innerHTML;
}


/* Browser notification permission */

if ("Notification" in window) {

    if (
        Notification.permission === "default"
    ) {

        setTimeout(() => {

            Notification.requestPermission();

        }, 2500);

    }

}


/* Check upcoming schedules */

async function checkUpcoming() {

    try {

        const response =
            await fetch("/api/upcoming");

        if (!response.ok) return;

        const schedules =
            await response.json();

        schedules.forEach(item => {

            const key =
                "studysched_" + item.id;

            if (
                !localStorage.getItem(key)
            ) {

                if (
                    "Notification" in window &&
                    Notification.permission === "granted"
                ) {

                    new Notification(
                        "📚 StudySched Reminder",
                        {
                            body:
                                item.title +
                                " — " +
                                item.schedule_date +
                                " " +
                                item.schedule_time
                        }
                    );

                }

                localStorage.setItem(
                    key,
                    "shown"
                );

            }

        });

    } catch (error) {

        console.log(error);

    }

}

setInterval(
    checkUpcoming,
    30000
);

checkUpcoming();

</script>

</body>

</html>
"""


# =========================================================
# RENDER PAGE
# =========================================================

def render_page(title, content):

    return render_template_string(
        BASE,
        title=title,
        content=content,
        css=CSS,
        user=current_user(),
        is_premium_active=is_premium_active
    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    user = current_user()

    if user:
        return redirect(url_for("dashboard"))

    content = """

<div class="hero">

<h1>
📚 StudySched
</h1>

<p>
Your smart student scheduling and
group-project management system.
</p>

<br>

<a
href="/register"
class="btn"
style="
background:white;
color:#4f46e5;
"
>
Get Started
</a>

<a
href="/login"
class="btn"
style="
border:2px solid white;
color:white;
margin-left:8px;
"
>
Login
</a>

</div>


<div class="cards">

<div class="card">

<div class="stat">
📅
</div>

<h3>
Smart Scheduling
</h3>

<p>
Create schedules and receive
browser reminders.
</p>

</div>


<div class="card">

<div class="stat">
👥
</div>

<h3>
Group Projects
</h3>

<p>
Create groups, assign tasks,
and work together.
</p>

</div>


<div class="card">

<div class="stat">
📊
</div>

<h3>
Progress Tracking
</h3>

<p>
Track task progress and
submit proof of work.
</p>

</div>


<div class="card">

<div class="stat">
🤖
</div>

<h3>
AI Assistant
</h3>

<p>
Get study and productivity
tips with Premium.
</p>

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

        username = request.form.get(
            "username",
            ""
        ).strip()

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not username or not full_name or not password:

            flash(
                "Please complete all fields.",
                "info"
            )

            return redirect(
                url_for("register")
            )

        existing = execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
            fetch=True
        )

        if existing:

            flash(
                "Username already exists.",
                "danger"
            )

            return redirect(
                url_for("register")
            )

        execute("""
            INSERT INTO users
            (
                username,
                password,
                full_name
            )
            VALUES (?, ?, ?)
        """, (
            username,
            generate_password_hash(password),
            full_name
        ))

        flash(
            "Account created successfully! 🎉",
            "success"
        )

        return redirect(
            url_for("login")
        )

    content = """

<div class="login-box">

<div class="card">

<h2>
📚 Create Your Account
</h2>

<form method="POST">

<label>
Full Name
</label>

<input
name="full_name"
required
>

<label>
Username
</label>

<input
name="username"
required
>

<label>
Password
</label>

<input
type="password"
name="password"
required
>

<button
class="btn-primary"
type="submit"
>
Create Account
</button>

</form>

<p style="margin-top:15px;">

Already have an account?

<a href="/login">
Login →
</a>

</p>

</div>

</div>

"""

    return render_page(
        "Register",
        content
    )


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        users = execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
            fetch=True
        )

        if (
            not users
            or not check_password_hash(
                users[0]["password"],
                password
            )
        ):

            flash(
                "Invalid username or password.",
                "danger"
            )

            return redirect(
                url_for("login")
            )

        session.clear()

        session["user_id"] = users[0]["id"]

        return redirect(
            url_for("dashboard")
        )

    content = """

<div class="login-box">

<div class="card">

<h2>
🔐 Welcome Back
</h2>

<form method="POST">

<label>
Username
</label>

<input
name="username"
required
>

<label>
Password
</label>

<input
type="password"
name="password"
required
>

<button
class="btn-primary"
type="submit"
>
Login
</button>

</form>

<p style="margin-top:15px;">

New here?

<a href="/register">
Create account →
</a>

</p>

</div>

</div>

"""

    return render_page(
        "Login",
        content
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("index")
    )


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
        AND is_deleted = 0
        ORDER BY schedule_date, schedule_time
    """, (
        user["id"],
    ), fetch=True)

    groups_list = execute("""
        SELECT g.*
        FROM groups g
        JOIN group_members gm
        ON gm.group_id = g.id
        WHERE gm.user_id = ?
        ORDER BY g.name
    """, (
        user["id"],
    ), fetch=True)

    tasks = execute("""
        SELECT t.*
        FROM tasks t
        JOIN group_members gm
        ON gm.group_id = t.group_id
        WHERE gm.user_id = ?
        AND t.status != 'Completed'
    """, (
        user["id"],
    ), fetch=True)

    premium = is_premium_active(user)

    schedule_html = ""

    for schedule_item in schedules[:5]:

        schedule_html += f"""

<div class="schedule-item">

<h3>
{schedule_item["title"]}
</h3>

<p>
<strong>
{schedule_item["schedule_date"]}
—
{schedule_item["schedule_time"]}
</strong>
</p>

<p>
{schedule_item["description"] or ""}
</p>

<span class="badge badge-pending">

Reminder:
{schedule_item["reminder_minutes"]}
min before

</span>

</div>

"""

    if not schedules:

        schedule_html = """

<p>
No schedules yet.
</p>

<a
href="/schedule"
class="btn btn-primary"
>
+ Add Schedule
</a>

"""

    groups_html = ""

    for group in groups_list:

        groups_html += f"""

<div class="task">

<h3>
{group["name"]}
</h3>

<p>
{group["description"] or ""}
</p>

<p class="small">
Code: {group["join_code"]}
</p>

<a
href="/group/{group["id"]}"
class="btn btn-primary"
>
Open →
</a>

</div>

"""

    if not groups_list:

        groups_html = """

<p>
You are not in any group yet.
</p>

<a
href="/groups"
class="btn btn-outline"
>
Browse Groups
</a>

"""

    premium_badge = ""

    if premium:

        premium_badge = """
<span class="premium-badge">
PREMIUM
</span>
"""

    content = f"""

<div class="hero">

<h1>
Welcome,
{user["full_name"]}! 👋
{premium_badge}
</h1>

<p>
Stay organized, track your progress,
and achieve your study goals.
</p>

</div>


<div class="cards">

<div class="card">

<div class="stat">
{len(schedules)}
</div>

<p>
Schedules
</p>

</div>


<div class="card">

<div class="stat">
{len(groups_list)}
</div>

<p>
Groups
</p>

</div>


<div class="card">

<div class="stat">
{len(tasks)}
</div>

<p>
Active Tasks
</p>

</div>

</div>


<div class="card">

<h2>
📅 Upcoming Schedule
</h2>

{schedule_html}

</div>


<div class="card">

<h2>
👥 My Groups
</h2>

{groups_html}

</div>

"""

    return render_page(
        "Dashboard",
        content
    )


# =========================================================
# SCHEDULE
# =========================================================

def render_schedule_item(
    schedule_item,
    is_past=False
):

    past_class = (
        "schedule-past"
        if is_past
        else ""
    )

    badge_class = (
        "badge-done"
        if is_past
        else "badge-pending"
    )

    return f"""

<div class="schedule-item {past_class}">

<h3>
{schedule_item["title"]}
</h3>

<p>

<strong>
{schedule_item["schedule_date"]}
—
{schedule_item["schedule_time"]}
</strong>

</p>

<p>
{schedule_item["description"] or ""}
</p>

<span class="badge {badge_class}">

Reminder:
{schedule_item["reminder_minutes"]}
min before

</span>

<form
method="POST"
action="/schedule/{schedule_item["id"]}/delete"
style="
display:inline;
margin-left:8px;
"
onsubmit="
return confirm('Delete this schedule?');
"
>

<button
type="submit"
class="btn-red"
style="
padding:6px 12px;
font-size:13px;
"
>
🗑️ Delete
</button>

</form>

</div>

"""


@app.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():

    user = current_user()

    now = datetime.now(TIMEZONE)

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        date = request.form.get(
            "date",
            ""
        )

        time_str = request.form.get(
            "time",
            ""
        )

        try:

            reminder = int(
                request.form.get(
                    "reminder_minutes",
                    10
                )
            )

        except ValueError:

            reminder = 10

        if not title or not date or not time_str:

            flash(
                "Please complete the required fields.",
                "danger"
            )

            return redirect(
                url_for("schedule")
            )

        execute("""
            INSERT INTO schedules
            (
                user_id,
                title,
                description,
                schedule_date,
                schedule_time,
                reminder_minutes
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user["id"],
            title,
            description,
            date,
            time_str,
            reminder
        ))

        flash(
            "✅ Schedule added!",
            "success"
        )

        return redirect(
            url_for("schedule")
        )

    schedules = execute("""
        SELECT *
        FROM schedules
        WHERE user_id = ?
        AND is_deleted = 0
        ORDER BY schedule_date DESC,
                 schedule_time DESC
    """, (
        user["id"],
    ), fetch=True)

    upcoming = []
    past = []

    for item in schedules:

        try:

            dt = datetime.strptime(
                f'{item["schedule_date"]} {item["schedule_time"]}',
                "%Y-%m-%d %H:%M"
            )

            dt = dt.replace(
                tzinfo=TIMEZONE
            )

            if dt >= now:
                upcoming.append(item)
            else:
                past.append(item)

        except Exception:

            upcoming.append(item)

    upcoming_html = "".join(
        render_schedule_item(
            item,
            False
        )
        for item in upcoming
    )

    past_html = "".join(
        render_schedule_item(
            item,
            True
        )
        for item in past
    )

    if not upcoming_html:

        upcoming_html = """
<p>
No upcoming schedules.
</p>
"""

    if not past_html:

        past_html = """
<p>
No past schedules.
</p>
"""

    content = f"""

<div class="card">

<h2>
➕ Add Schedule
</h2>

<form method="POST">

<label>
Title / Subject
</label>

<input
name="title"
placeholder="e.g. Math Review"
required
>

<label>
Description
</label>

<textarea
name="description"
placeholder="Topics to cover..."
></textarea>

<label>
Date
</label>

<input
type="date"
name="date"
required
>

<label>
Time
</label>

<input
type="time"
name="time"
required
>

<label>
Reminder
</label>

<select name="reminder_minutes">

<option value="0">
At time
</option>

<option value="5">
5 minutes before
</option>

<option value="10" selected>
10 minutes before
</option>

<option value="30">
30 minutes before
</option>

<option value="60">
1 hour before
</option>

</select>

<button
class="btn-primary"
type="submit"
>
Add Schedule
</button>

</form>

</div>


<div class="card">

<h2>
🔜 Upcoming ({len(upcoming)})
</h2>

{upcoming_html}

</div>


<div class="card">

<h2>
⏳ Past Schedules ({len(past)})
</h2>

{past_html}

</div>

"""

    return render_page(
        "Schedule",
        content
    )


# =========================================================
# DELETE SCHEDULE
# =========================================================

@app.route(
    "/schedule/<int:sched_id>/delete",
    methods=["POST"]
)
@login_required
def delete_schedule(sched_id):

    user = current_user()

    item = execute("""
        SELECT *
        FROM schedules
        WHERE id = ?
        AND user_id = ?
    """, (
        sched_id,
        user["id"]
    ), fetch=True)

    if not item:

        flash(
            "Schedule not found.",
            "danger"
        )

        return redirect(
            url_for("schedule")
        )

    execute("""
        UPDATE schedules
        SET is_deleted = 1
        WHERE id = ?
        AND user_id = ?
    """, (
        sched_id,
        user["id"]
    ))

    flash(
        "🗑️ Schedule deleted.",
        "success"
    )

    return redirect(
        url_for("schedule")
    )


# =========================================================
# UPCOMING API
# =========================================================

@app.route("/api/upcoming")
@login_required
def upcoming():

    user = current_user()

    schedules = execute("""
        SELECT *
        FROM schedules
        WHERE user_id = ?
        AND is_deleted = 0
    """, (
        user["id"],
    ), fetch=True)

    now = datetime.now(TIMEZONE)

    result = []

    for item in schedules:

        try:

            schedule_dt = datetime.strptime(
                f'{item["schedule_date"]} {item["schedule_time"]}',
                "%Y-%m-%d %H:%M"
            ).replace(
                tzinfo=TIMEZONE
            )

            seconds = (
                schedule_dt - now
            ).total_seconds()

            reminder_seconds = (
                item["reminder_minutes"] * 60
            )

            if (
                0 <= seconds <= reminder_seconds
            ):

                result.append({
                    "id": item["id"],
                    "title": item["title"],
                    "schedule_date": item["schedule_date"],
                    "schedule_time": item["schedule_time"]
                })

        except Exception:
            pass

    return jsonify(result)


# =========================================================
# GROUPS
# =========================================================

@app.route(
    "/groups",
    methods=["GET", "POST"]
)
@login_required
def groups():

    user = current_user()

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        if action == "create":

            name = request.form.get(
                "name",
                ""
            ).strip()

            description = request.form.get(
                "description",
                ""
            ).strip()

            if not name:

                flash(
                    "Group name is required.",
                    "danger"
                )

                return redirect(
                    url_for("groups")
                )

            code = secrets.token_hex(
                4
            ).upper()

            execute("""
                INSERT INTO groups
                (
                    name,
                    description,
                    join_code,
                    owner_id
                )
                VALUES (?, ?, ?, ?)
            """, (
                name,
                description,
                code,
                user["id"]
            ))

            group = execute("""
                SELECT id
                FROM groups
                WHERE join_code = ?
            """, (
                code,
            ), fetch=True)

            group_id = group[0]["id"]

            execute("""
                INSERT INTO group_members
                (
                    group_id,
                    user_id
                )
                VALUES (?, ?)
            """, (
                group_id,
                user["id"]
            ))

            add_activity(
                group_id,
                user["id"],
                "Created the group"
            )

            flash(
                f"✅ Group created! Code: {code}",
                "success"
            )

        elif action == "join":

            code = request.form.get(
                "join_code",
                ""
            ).strip().upper()

            found = execute("""
                SELECT *
                FROM groups
                WHERE join_code = ?
            """, (
                code,
            ), fetch=True)

            if not found:

                flash(
                    "Group code not found.",
                    "danger"
                )

            else:

                group_id = found[0]["id"]

                member = execute("""
                    SELECT 1
                    FROM group_members
                    WHERE group_id = ?
                    AND user_id = ?
                """, (
                    group_id,
                    user["id"]
                ), fetch=True)

                if member:

                    flash(
                        "You are already in this group.",
                        "info"
                    )

                else:

                    execute("""
                        INSERT INTO group_members
                        (
                            group_id,
                            user_id
                        )
                        VALUES (?, ?)
                    """, (
                        group_id,
                        user["id"]
                    ))

                    add_activity(
                        group_id,
                        user["id"],
                        "Joined the group"
                    )

                    flash(
                        "✅ Joined group!",
                        "success"
                    )

        return redirect(
            url_for("groups")
        )

    groups_list = execute("""
        SELECT g.*
        FROM groups g
        JOIN group_members gm
        ON gm.group_id = g.id
        WHERE gm.user_id = ?
        ORDER BY g.name
    """, (
        user["id"],
    ), fetch=True)

    groups_html = ""

    for group in groups_list:

        groups_html += f"""

<div class="task">

<h3>
{group["name"]}
</h3>

<p>
{group["description"] or ""}
</p>

<p class="small">
Join Code:
<strong>
{group["join_code"]}
</strong>
</p>

<a
class="btn btn-primary"
href="/group/{group["id"]}"
>
Open Group →
</a>

</div>

"""

    if not groups_html:

        groups_html = """
<p>
You are not in any group yet.
</p>
"""

    content = f"""

<div class="cards">

<div class="card">

<h2>
➕ Create Group
</h2>

<form method="POST">

<input
type="hidden"
name="action"
value="create"
>

<label>
Group Name
</label>

<input
name="name"
required
>

<label>
Description
</label>

<textarea
name="description"
></textarea>

<button
class="btn-primary"
type="submit"
>
Create Group
</button>

</form>

</div>


<div class="card">

<h2>
🔑 Join Group
</h2>

<form method="POST">

<input
type="hidden"
name="action"
value="join"
>

<label>
Group Code
</label>

<input
name="join_code"
placeholder="A1B2C3D4"
required
>

<button
class="btn-outline"
type="submit"
>
Join Group
</button>

</form>

</div>

</div>


<div class="card">

<h2>
👥 My Groups
</h2>

{groups_html}

</div>

"""

    return render_page(
        "Groups",
        content
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
        SELECT 1
        FROM group_members
        WHERE group_id = ?
        AND user_id = ?
    """, (
        group_id,
        user["id"]
    ), fetch=True)

    if not member:

        return "Access denied", 403

    group_result = execute("""
        SELECT *
        FROM groups
        WHERE id = ?
    """, (
        group_id,
    ), fetch=True)

    if not group_result:

        return "Group not found", 404

    group = group_result[0]

    if request.method == "POST":

        action = request.form.get(
            "action",
            "create_task"
        )

        # ---------------------------------------------
        # CREATE TASK
        # ---------------------------------------------

        if action == "create_task":

            title = request.form.get(
                "title",
                ""
            ).strip()

            description = request.form.get(
                "description",
                ""
            ).strip()

            assigned = request.form.get(
                "assigned_to"
            ) or None

            deadline = request.form.get(
                "deadline",
                ""
            ).strip()

            if not title:

                flash(
                    "Task title is required.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "group_page",
                        group_id=group_id
                    )
                )

            if assigned:

                try:
                    assigned = int(assigned)

                except ValueError:

                    assigned = None

                if assigned:

                    valid_member = execute("""
                        SELECT 1
                        FROM group_members
                        WHERE group_id = ?
                        AND user_id = ?
                    """, (
                        group_id,
                        assigned
                    ), fetch=True)

                    if not valid_member:

                        flash(
                            "Assignee is not a member of this group.",
                            "danger"
                        )

                        return redirect(
                            url_for(
                                "group_page",
                                group_id=group_id
                            )
                        )

            execute("""
                INSERT INTO tasks
                (
                    group_id,
                    title,
                    description,
                    assigned_to,
                    deadline
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                group_id,
                title,
                description,
                assigned,
                deadline
            ))

            add_activity(
                group_id,
                user["id"],
                f"Created task: {title}"
            )

            flash(
                "✅ Task added!",
                "success"
            )

            return redirect(
                url_for(
                    "group_page",
                    group_id=group_id
                )
            )

        # ---------------------------------------------
        # UPDATE TASK
        # ---------------------------------------------

        elif action == "update_task":

            try:

                task_id = int(
                    request.form.get(
                        "task_id"
                    )
                )

                progress = int(
                    request.form.get(
                        "progress",
                        0
                    )
                )

            except (ValueError, TypeError):

                flash(
                    "Invalid task information.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "group_page",
                        group_id=group_id
                    )
                )

            progress = max(
                0,
                min(100, progress)
            )

            proof = request.form.get(
                "proof",
                ""
            ).strip()

            status = request.form.get(
                "status",
                "Pending"
            )

            allowed_statuses = [
                "Pending",
                "In Progress",
                "Completed"
            ]

            if status not in allowed_statuses:
                status = "Pending"

            if progress >= 100:
                status = "Completed"

            elif progress > 0:
                status = "In Progress"

            task = execute("""
                SELECT *
                FROM tasks
                WHERE id = ?
                AND group_id = ?
            """, (
                task_id,
                group_id
            ), fetch=True)

            if not task:

                flash(
                    "Task not found.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "group_page",
                        group_id=group_id
                    )
                )

            execute("""
                UPDATE tasks
                SET
                    status = ?,
                    progress = ?,
                    proof = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                AND group_id = ?
            """, (
                status,
                progress,
                proof,
                task_id,
                group_id
            ))

            add_activity(
                group_id,
                user["id"],
                f"Updated task: {task[0]['title']} — {progress}%"
            )

            flash(
                "✅ Task progress updated!",
                "success"
            )

            return redirect(
                url_for(
                    "group_page",
                    group_id=group_id
                )
            )

        # ---------------------------------------------
        # DELETE TASK
        # ---------------------------------------------

        elif action == "delete_task":

            try:

                task_id = int(
                    request.form.get(
                        "task_id"
                    )
                )

            except (ValueError, TypeError):

                flash(
                    "Invalid task.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "group_page",
                        group_id=group_id
                    )
                )

            task = execute("""
                SELECT *
                FROM tasks
                WHERE id = ?
                AND group_id = ?
            """, (
                task_id,
                group_id
            ), fetch=True)

            if not task:

                flash(
                    "Task not found.",
                    "danger"
                )

            else:

                execute("""
                    DELETE FROM tasks
                    WHERE id = ?
                    AND group_id = ?
                """, (
                    task_id,
                    group_id
                ))

                add_activity(
                    group_id,
                    user["id"],
                    f"Deleted task: {task[0]['title']}"
                )

                flash(
                    "🗑️ Task deleted.",
                    "success"
                )

            return redirect(
                url_for(
                    "group_page",
                    group_id=group_id
                )
            )

    # =====================================================
    # GROUP DATA
    # =====================================================

    members = execute("""
        SELECT u.*
        FROM users u
        JOIN group_members gm
        ON gm.user_id = u.id
        WHERE gm.group_id = ?
        ORDER BY u.full_name
    """, (
        group_id,
    ), fetch=True)

    tasks = execute("""
        SELECT
            t.*,
            u.full_name AS assigned_name
        FROM tasks t
        LEFT JOIN users u
        ON u.id = t.assigned_to
        WHERE t.group_id = ?
        ORDER BY
            CASE
                WHEN t.status = 'Completed' THEN 2
                ELSE 1
            END,
            t.deadline
    """, (
        group_id,
    ), fetch=True)

    activities = execute("""
        SELECT
            a.*,
            u.full_name
        FROM activity a
        JOIN users u
        ON u.id = a.user_id
        WHERE a.group_id = ?
        ORDER BY a.id DESC
        LIMIT 30
    """, (
        group_id,
    ), fetch=True)

    # =====================================================
    # MEMBERS HTML
    # =====================================================

    members_html = ""

    for member_item in members:

        owner_badge = ""

        if member_item["id"] == group["owner_id"]:

            owner_badge = """
<span class="badge badge-progress">
Owner
</span>
"""

        members_html += f"""

<div
style="
padding:10px 0;
border-bottom:1px solid #e2e8f0;
"
>

<strong>
{member_item["full_name"]}
</strong>

<br>

<span class="small">
@{member_item["username"]}
</span>

{owner_badge}

</div>

"""

    # =====================================================
    # TASK HTML
    # =====================================================

    tasks_html = ""

    for task in tasks:

        progress = task["progress"] or 0

        status = task["status"] or "Pending"

        if status == "Completed":

            badge_class = "badge-done"

        elif status == "In Progress":

            badge_class = "badge-progress"

        else:

            badge_class = "badge-pending"

        assigned_name = (
            task["assigned_name"]
            or "Unassigned"
        )

        tasks_html += f"""

<div class="task">

<div
style="
display:flex;
justify-content:space-between;
gap:10px;
flex-wrap:wrap;
"
>

<h3>
{task["title"]}
</h3>

<span class="badge {badge_class}">
{status}
</span>

</div>

<p>
{task["description"] or ""}
</p>

<p class="small">

Assigned to:
<strong>
{assigned_name}
</strong>

<br>

Deadline:
<strong>
{task["deadline"] or "No deadline"}
</strong>

</p>

<div class="progress">

<div
class="progress-bar"
style="width:{progress}%"
></div>

</div>

<p>
<strong>
{progress}%
</strong>
complete
</p>

"""

        if task["proof"]:

            tasks_html += f"""

<div
style="
background:#f8fafc;
padding:12px;
border-radius:10px;
margin:10px 0;
"
>

<strong>
📝 Proof / Work Description
</strong>

<p>
{task["proof"]}
</p>

</div>

"""

        tasks_html += f"""

<form method="POST">

<input
type="hidden"
name="action"
value="update_task"
>

<input
type="hidden"
name="task_id"
value="{task["id"]}"
>

<label>
Progress (%)
</label>

<input
type="number"
name="progress"
min="0"
max="100"
value="{progress}"
required
>

<label>
Status
</label>

<select name="status">

<option
value="Pending"
{"selected" if status == "Pending" else ""}
>
Pending
</option>

<option
value="In Progress"
{"selected" if status == "In Progress" else ""}
>
In Progress
</option>

<option
value="Completed"
{"selected" if status == "Completed" else ""}
>
Completed
</option>

</select>

<label>
Proof / Work Description
</label>

<textarea
name="proof"
placeholder="Describe what you completed..."
>{task["proof"] or ""}</textarea>

<button
class="btn btn-primary"
type="submit"
>
Update Progress
</button>

</form>


<form
method="POST"
style="margin-top:8px;"
onsubmit="
return confirm('Delete this task?');
"
>

<input
type="hidden"
name="action"
value="delete_task"
>

<input
type="hidden"
name="task_id"
value="{task["id"]}"
>

<button
class="btn btn-red"
type="submit"
>
🗑️ Delete Task
</button>

</form>

</div>

"""

    if not tasks_html:

        tasks_html = """

<p>
No tasks have been created yet.
</p>

"""

    # =====================================================
    # ACTIVITY HTML
    # =====================================================

    activity_html = ""

    for item in activities:

        activity_html += f"""

<div class="activity">

<strong>
{item["full_name"]}
</strong>

{item["message"]}

<br>

<span class="small">
{item["created_at"]}
</span>

</div>

"""

    if not activity_html:

        activity_html = """

<p>
No activity yet.
</p>

"""

    # =====================================================
    # CREATE TASK MEMBER OPTIONS
    # =====================================================

    member_options = """
<option value="">
Unassigned
</option>
"""

    for member_item in members:

        member_options += f"""

<option value="{member_item["id"]}">
{member_item["full_name"]}
</option>

"""

    # =====================================================
    # FINAL GROUP PAGE
    # =====================================================

    content = f"""

<div class="hero">

<h1>
👥 {group["name"]}
</h1>

<p>
{group["description"] or "Group project workspace"}
</p>

<br>

<p>
Group Code:
<strong>
{group["join_code"]}
</strong>
</p>

</div>


<div class="cards">

<div class="card">

<h2>
👥 Members
</h2>

{members_html}

</div>


<div class="card">

<h2>
📊 Group Progress
</h2>

<p>

Total Tasks:

<strong>
{len(tasks)}
</strong>

</p>

<p>

Completed:

<strong>
{
    sum(
        1
        for task in tasks
        if task["status"] == "Completed"
    )
}
</strong>

</p>

</div>

</div>


<div class="card">

<h2>
➕ Create Task
</h2>

<form method="POST">

<input
type="hidden"
name="action"
value="create_task"
>

<label>
Task Title
</label>

<input
name="title"
placeholder="e.g. Research Chapter 1"
required
>

<label>
Description
</label>

<textarea
name="description"
placeholder="What needs to be done?"
></textarea>

<label>
Assign To
</label>

<select name="assigned_to">

{member_options}

</select>

<label>
Deadline
</label>

<input
type="datetime-local"
name="deadline"
>

<button
class="btn btn-primary"
type="submit"
>
Create Task
</button>

</form>

</div>


<div class="card">

<h2>
✅ Group Tasks
</h2>

{tasks_html}

</div>


<div class="card">

<h2>
📈 Activity Tracking
</h2>

<p class="small">
Group activity helps members see
updates and progress.
</p>

<br>

{activity_html}

</div>

"""

    return render_page(
        "Group",
        content
    )


# =========================================================
# PREMIUM
# =========================================================

@app.route(
    "/premium",
    methods=["GET", "POST"]
)
@login_required
def premium():

    user = current_user()

    if request.method == "POST":

        expiry = (
            datetime.now(TIMEZONE)
            + timedelta(days=365)
        )

        execute("""
            UPDATE users
            SET
                is_premium = 1,
                premium_until = ?
            WHERE id = ?
        """, (
            expiry,
            user["id"]
        ))

        flash(
            "✨ Premium activated!",
            "success"
        )

        return redirect(
            url_for("premium")
        )

    active = is_premium_active(user)

    if active:

        content = """

<div class="hero">

<h1>
✨ Premium Active
</h1>

<p>
You have access to StudySched Premium features.
</p>

</div>


<div class="cards">

<div class="card">
<h3>🤖 AI Assistant</h3>
<p>
Get study and productivity assistance.
</p>
</div>

<div class="card">
<h3>📅 Smart Scheduling</h3>
<p>
Organize your study sessions.
</p>
</div>

<div class="card">
<h3>📊 Advanced Progress</h3>
<p>
Track your group-project progress.
</p>
</div>

<div class="card">
<h3>🚀 Premium Access</h3>
<p>
Enjoy advanced StudySched features.
</p>
</div>

</div>

"""

    else:

        content = """

<div class="hero">

<h1>
✨ StudySched Premium
</h1>

<p>
Unlock additional tools for studying
and productivity.
</p>

</div>


<div class="card">

<h2>
Premium Features
</h2>

<ul style="
padding-left:25px;
line-height:2;
">

<li>
🤖 AI Study Assistant
</li>

<li>
📅 Smart scheduling
</li>

<li>
🔔 Browser reminders
</li>

<li>
📊 Advanced group progress
</li>

<li>
🎨 Premium interface
</li>

<li>
🚀 Early feature access
</li>

</ul>

<br>

<form method="POST">

<button
class="btn btn-warning"
type="submit"
>
✨ Activate Premium Demo
</button>

</form>

<p class="small">
Demo activation is free for testing.
</p>

</div>

"""

    return render_page(
        "Premium",
        content
    )


# =========================================================
# AI CHAT API
# =========================================================

@app.route(
    "/api/ai-chat",
    methods=["POST"]
)
@premium_required
def ai_chat():

    data = request.get_json(
        silent=True
    ) or {}

    message = (
        data.get("message", "")
        or ""
    ).strip()

    if not message:

        return jsonify({
            "reply":
            "Please type a question."
        })

    user = current_user()

    reply = ai_response(
        message,
        user
    )

    execute("""
        INSERT INTO ai_conversations
        (
            user_id,
            role,
            message
        )
        VALUES (?, ?, ?)
    """, (
        user["id"],
        "user",
        message
    ))

    execute("""
        INSERT INTO ai_conversations
        (
            user_id,
            role,
            message
        )
        VALUES (?, ?, ?)
    """, (
        user["id"],
        "assistant",
        reply
    ))

    return jsonify({
        "reply": reply
    })


# =========================================================
# ADMIN
# =========================================================

@app.route("/admin")
@admin_required
def admin():

    users = execute("""
        SELECT *
        FROM users
        ORDER BY id DESC
    """, fetch=True)

    schedules_count = execute("""
        SELECT COUNT(*) AS count
        FROM schedules
        WHERE is_deleted = 0
    """, fetch=True)[0]["count"]

    groups_count = execute("""
        SELECT COUNT(*) AS count
        FROM groups
    """, fetch=True)[0]["count"]

    tasks_count = execute("""
        SELECT COUNT(*) AS count
        FROM tasks
    """, fetch=True)[0]["count"]

    premium_count = execute("""
        SELECT COUNT(*) AS count
        FROM users
        WHERE is_premium = 1
    """, fetch=True)[0]["count"]

    user_html = ""

    for item in users:

        premium_status = (
            "✨ Premium"
            if item["is_premium"]
            else "Free"
        )

        admin_status = (
            "Admin"
            if item["is_admin"]
            else "Student"
        )

        user_html += f"""

<tr>

<td>
{item["id"]}
</td>

<td>
{item["full_name"]}
</td>

<td>
{item["username"]}
</td>

<td>
{admin_status}
</td>

<td>
{premium_status}
</td>

</tr>

"""

    content = f"""

<div class="hero">

<h1>
🛠️ Admin Dashboard
</h1>

<p>
Manage and monitor StudySched.
</p>

</div>


<div class="cards">

<div class="card">

<div class="stat">
{len(users)}
</div>

<p>
Registered Users
</p>

</div>


<div class="card">

<div class="stat">
{schedules_count}
</div>

<p>
Schedules
</p>

</div>


<div class="card">

<div class="stat">
{groups_count}
</div>

<p>
Groups
</p>

</div>


<div class="card">

<div class="stat">
{tasks_count}
</div>

<p>
Tasks
</p>

</div>


<div class="card">

<div class="stat">
{premium_count}
</div>

<p>
Premium Users
</p>

</div>

</div>


<div class="card">

<h2>
👤 Users
</h2>

<div style="overflow-x:auto;">

<table
style="
width:100%;
border-collapse:collapse;
"
>

<thead>

<tr
style="
text-align:left;
border-bottom:2px solid #e2e8f0;
"
>

<th style="padding:10px;">
ID
</th>

<th style="padding:10px;">
Name
</th>

<th style="padding:10px;">
Username
</th>

<th style="padding:10px;">
Role
</th>

<th style="padding:10px;">
Status
</th>

</tr>

</thead>

<tbody>

{user_html}

</tbody>

</table>

</div>

</div>

"""

    return render_page(
        "Admin",
        content
    )


# =========================================================
# SERVICE WORKER
# =========================================================

@app.route("/sw.js")
def service_worker():

    js = """
self.addEventListener(
    "install",
    event => self.skipWaiting()
);

self.addEventListener(
    "activate",
    event => self.clients.claim()
);

self.addEventListener(
    "fetch",
    event => {}
);
"""

    return app.response_class(
        js,
        mimetype="application/javascript"
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "app": "StudySched"
    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False
    )
