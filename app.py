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
PREMIUM_PRICE = 50.00  # ₱50.00 PHP
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
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method VARCHAR(50),
            transaction_ref VARCHAR(100),
            status VARCHAR(30) DEFAULT 'pending',
            paid_at TIMESTAMP,
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
                "✨ This Premium feature requires a ₱50 one-time payment.",
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
    """, (group_id, user_id, message))
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
            "✨ Premium includes the AI Study Assistant, advanced reminders, and more. "
            "Unlock it now for just ₱50!",
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
    --sidebar-bg: #ffffff;
    --sidebar-border: #e2e8f0;
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
    display: flex;
    min-height: 100vh;
}
/* SIDEBAR LAYOUT */
.sidebar {
    width: 260px;
    background: var(--sidebar-bg);
    border-right: 1px solid var(--sidebar-border);
    padding: 24px 16px;
    position: fixed;
    top: 0;
    left: 0;
    height: 100vh;
    overflow-y: auto;
    z-index: 99;
}
.sidebar-logo {
    font-size: 22px;
    font-weight: 800;
    color: var(--primary);
    margin-bottom: 32px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.sidebar-section {
    margin-bottom: 24px;
}
.sidebar-section-title {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
    margin-bottom: 8px;
    padding: 0 12px;
}
.sidebar-link {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    border-radius: 10px;
    color: #475569;
    text-decoration: none;
    margin-bottom: 4px;
    transition: all 0.2s;
}
.sidebar-link:hover, .sidebar-link.active {
    background: #eef2ff;
    color: var(--primary);
    font-weight: 600;
}
.sidebar-link.premium-link {
    background: linear-gradient(135deg, #fef3c7, #fde68a);
    color: #78350f !important;
    font-weight: 700;
    margin-top: 8px;
}
.sidebar-divider {
    height: 1px;
    background: var(--sidebar-border);
    margin: 16px 0;
}
.main-content {
    flex: 1;
    margin-left: 260px;
    padding: 32px 24px;
    min-height: 100vh;
}
/* Mobile Sidebar Toggle */
.sidebar-toggle {
    display: none;
    position: fixed;
    top: 16px;
    left: 16px;
    z-index: 200;
    background: var(--primary);
    color: white;
    border: none;
    padding: 10px 14px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 18px;
}
/* Rest of styles */
.hero {
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
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
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 22px;
    margin-bottom: 25px;
}
.card {
    background: white;
    padding: 25px;
    border-radius: 18px;
    box-shadow: 0 8px 30px rgba(0,0,0,.06);
    margin-bottom: 20px;
    transition: transform 0.2s, box-shadow 0.2s;
}
.card:hover {
    transform: translateY(-2px);
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
input, textarea, select {
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
input:focus, textarea:focus, select:focus {
    outline: none;
    border-color: var(--primary);
}
button, .btn {
    border: none;
    padding: 12px 20px;
    border-radius: 10px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
    font-weight: 600;
    font-size: 15px;
    transition: background 0.2s;
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
    color: #78350f;
}
.badge {
    display: inline-block;
    padding: 5px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
}
.badge-pending { background: #fef3c7; color: #92400e; }
.badge-progress { background: #dbeafe; color: #1e40af; }
.badge-done { background: #d1fae5; color: #065f46; }
.premium-badge {
    display: inline-block;
    background: linear-gradient(135deg, #f59e0b, #facc15);
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
    transition: width 0.3s ease;
}
.alert {
    padding: 13px 17px;
    border-radius: 10px;
    margin-bottom: 18px;
}
.alert-success { background: #dcfce7; color: #166534; }
.alert-danger { background: #fee2e2; color: #991b1b; }
.alert-info { background: #eef2ff; color: #3730a3; }
.login-box {
    max-width: 430px;
    margin: 40px auto;
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
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
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
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
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
.ai-bot { background: #eef2ff; color: #3730a3; }
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
.ai-input input { margin: 0; }
.hidden { display: none !important; }
footer {
    text-align: center;
    padding: 35px;
    color: #94a3b8;
    margin-top: 40px;
}
.price-tag {
    font-size: 42px;
    font-weight: 800;
    color: var(--warning);
}
.price-note {
    font-size: 14px;
    color: var(--muted);
}
/* RESPONSIVE */
@media(max-width: 768px) {
    .sidebar {
        transform: translateX(-100%);
        transition: transform 0.3s ease;
        z-index: 150;
    }
    .sidebar.open { transform: translateX(0); }
    .main-content { margin-left: 0; padding: 20px 16px; padding-top: 70px; }
    .sidebar-toggle { display: block; }
    .hero { padding: 30px 22px; }
    .hero h1 { font-size: 28px; }
    .ai-chat { right: 15px; bottom: 15px; }
    .price-tag { font-size: 32px; }
}
"""
# =========================================================
# BASE TEMPLATE WITH SIDEBAR
# =========================================================
BASE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }} - StudySched</title>
<style>{{ css }}</style>
</head>
<body>
{% if user %}
<button class="sidebar-toggle" onclick="toggleSidebar()">☰</button>
<aside class="sidebar" id="sidebar">
    <div class="sidebar-logo">📚 StudySched</div>
    
    <div class="sidebar-section-title">MAIN</div>
    <div class="sidebar-section">
        <a href="{{ url_for('dashboard') }}" class="sidebar-link">
            📊 Dashboard
        </a>
        <a href="{{ url_for('schedule') }}" class="sidebar-link">
            📅 Schedule
        </a>
        <a href="{{ url_for('groups') }}" class="sidebar-link">
            👥 Groups
        </a>
    </div>
    
    <div class="sidebar-divider"></div>
    
    <div class="sidebar-section-title">ACCOUNT</div>
    <div class="sidebar-section">
        <a href="{{ url_for('premium') }}" class="sidebar-link premium-link">
            ✨ Premium
        </a>
        {% if user["is_admin"] %}
        <a href="{{ url_for('admin') }}" class="sidebar-link">
            🛠️ Admin
        </a>
        {% endif %}
        <a href="{{ url_for('logout') }}" class="sidebar-link">
            🚪 Logout
        </a>
    </div>
</aside>
{% endif %}

<main class="main-content">
{% with messages = get_flashed_messages(with_categories=true) %}
{% for category, message in messages %}
<div class="alert alert-{{ category }}">{{ message }}</div>
{% endfor %}
{% endwith %}

{% if not user %}
<nav style="display:flex;justify-content:flex-end;gap:12px;margin-bottom:24px;">
    <a href="{{ url_for('login') }}" class="btn btn-outline">Login</a>
    <a href="{{ url_for('register') }}" class="btn btn-primary">Register</a>
</nav>
{% endif %}

{{ content|safe }}

<footer>StudySched © 2026 — Smart Study, Better Results ✨</footer>
</main>

{% if user and is_premium_active(user) %}
<button class="ai-toggle" id="aiToggle" onclick="toggleChat()">🤖</button>
<div class="ai-chat hidden" id="aiChatBox">
    <div class="ai-header">
        <strong>🤖 AI Study Assistant</strong>
        <button onclick="toggleChat()" style="background:none;border:none;color:white;font-size:22px;">×</button>
    </div>
    <div class="ai-body" id="aiBody">
        <div class="ai-bubble ai-bot">
            Hi! I'm your StudySched AI Assistant. 👋<br><br>
            Ask me about schedules, studying, group projects, tasks, or productivity.
        </div>
    </div>
    <form class="ai-input" onsubmit="sendAiMsg(event)">
        <input id="aiInput" placeholder="Ask something..." required>
        <button class="btn-primary" type="submit">Send</button>
    </form>
</div>
{% endif %}

<script>
function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
}
function toggleChat() {
    const box = document.getElementById("aiChatBox");
    const toggle = document.getElementById("aiToggle");
    if (!box) return;
    box.classList.toggle("hidden");
    if (toggle) toggle.classList.toggle("hidden", !box.classList.contains("hidden"));
}
async function sendAiMsg(event) {
    event.preventDefault();
    const input = document.getElementById("aiInput");
    const body = document.getElementById("aiBody");
    if (!input || !body) return;
    const message = input.value.trim();
    if (!message) return;
    body.innerHTML += '<div class="ai-bubble ai-user">' + escapeHtml(message) + '</div>';
    input.value = "";
    body.innerHTML += '<div class="ai-bubble ai-bot" id="aiLoading">Thinking...</div>';
    body.scrollTop = body.scrollHeight;
    try {
        const response = await fetch("/api/ai-chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: message })
        });
        const data = await response.json();
        document.getElementById("aiLoading")?.remove();
        body.innerHTML += '<div class="ai-bubble ai-bot">' + escapeHtml(data.reply || "Sorry, I could not answer.") + '</div>';
    } catch (error) {
        document.getElementById("aiLoading")?.remove();
        body.innerHTML += '<div class="ai-bubble ai-bot">Sorry, something went wrong.</div>';
    }
    body.scrollTop = body.scrollHeight;
}
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}
if ("Notification" in window && Notification.permission === "default") {
    setTimeout(() => Notification.requestPermission(), 2500);
}
async function checkUpcoming() {
    try {
        const res = await fetch("/api/upcoming");
        if (!res.ok) return;
        (await res.json()).forEach(item => {
            const key = "studysched_" + item.id;
            if (!localStorage.getItem(key) && "Notification" in window && Notification.permission === "granted") {
                new Notification("📚 StudySched Reminder", {
                    body: item.title + " — " + item.schedule_date + " " + item.schedule_time
                });
                localStorage.setItem(key, "shown");
            }
        });
    } catch (e) {}
}
setInterval(checkUpcoming, 30000);
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
    content = f"""
<div class="hero">
<h1>📚 StudySched</h1>
<p>Your smart student scheduling and group-project management system.</p>
<br>
<a href="/register" class="btn" style="background:white;color:#4f46e5;">Get Started</a>
<a href="/login" class="btn" style="border:2px solid white;color:white;margin-left:8px;">Login</a>
</div>
<div class="cards">
<div class="card">
<div class="stat">📅</div>
<h3>Smart Scheduling</h3>
<p>Create schedules and receive browser reminders.</p>
</div>
<div class="card">
<div class="stat">👥</div>
<h3>Group Projects</h3>
<p>Create groups, assign tasks, and work together.</p>
</div>
<div class="card">
<div class="stat">📊</div>
<h3>Progress Tracking</h3>
<p>Track task progress and submit proof of work.</p>
</div>
<div class="card">
<div class="stat">🤖</div>
<h3>AI Assistant</h3>
<p>Get study tips with Premium — ₱{PREMIUM_PRICE}</p>
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
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        if not username or not full_name or not password:
            flash("Please complete all fields.", "info")
            return redirect(url_for("register"))
        if execute("SELECT id FROM users WHERE username = ?", (username,), fetch=True):
            flash("Username already exists.", "danger")
            return redirect(url_for("register"))
        execute("""INSERT INTO users (username, password, full_name) VALUES (?, ?, ?)""",
               (username, generate_password_hash(password), full_name))
        flash("Account created successfully! 🎉", "success")
        return redirect(url_for("login"))
    content = """
<div class="login-box">
<div class="card">
<h2>📚 Create Your Account</h2>
<form method="POST">
<label>Full Name</label>
<input name="full_name" required>
<label>Username</label>
<input name="username" required>
<label>Password</label>
<input type="password" name="password" required>
<button class="btn-primary" type="submit">Create Account</button>
</form>
<p style="margin-top:15px;">Already have an account? <a href="/login">Login →</a></p>
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
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = execute("SELECT * FROM users WHERE username = ?", (username,), fetch=True)
        if not users or not check_password_hash(users[0]["password"], password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("login"))
        session.clear()
        session["user_id"] = users[0]["id"]
        return redirect(url_for("dashboard"))
    content = """
<div class="login-box">
<div class="card">
<h2>🔐 Welcome Back</h2>
<form method="POST">
<label>Username</label>
<input name="username" required>
<label>Password</label>
<input type="password" name="password" required>
<button class="btn-primary" type="submit">Login</button>
</form>
<p style="margin-top:15px;">New here? <a href="/register">Create account →</a></p>
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
    schedules = execute("SELECT * FROM schedules WHERE user_id = ? AND is_deleted = 0 ORDER BY schedule_date, schedule_time",
                       (user["id"],), fetch=True)
    groups_list = execute("SELECT g.* FROM groups g JOIN group_members gm ON gm.group_id = g.id WHERE gm.user_id = ? ORDER BY g.name",
                          (user["id"],), fetch=True)
    tasks = execute("SELECT t.* FROM tasks t JOIN group_members gm ON gm.group_id = t.group_id WHERE gm.user_id = ? AND t.status != 'Completed'",
                    (user["id"],), fetch=True)
    premium = is_premium_active(user)
    
    schedule_html = ""
    for s in schedules[:5]:
        schedule_html += f"""
<div class="schedule-item">
<h3>{s['title']}</h3>
<p><strong>{s['schedule_date']} — {s['schedule_time']}</strong></p>
<p>{s['description'] or ''}</p>
<span class="badge badge-pending">Reminder: {s['reminder_minutes']} min before</span>
</div>"""
    if not schedules:
        schedule_html = '<p>No schedules yet.</p><a href="/schedule" class="btn btn-primary">+ Add Schedule</a>'
    
    groups_html = ""
    for g in groups_list:
        groups_html += f"""
<div class="task">
<h3>{g['name']}</h3>
<p>{g['description'] or ''}</p>
<p class="small">Code: {g['join_code']}</p>
<a href="/group/{g['id']}" class="btn btn-primary">Open →</a>
</div>"""
    if not groups_list:
        groups_html = '<p>Not in any group yet.</p><a href="/groups" class="btn btn-outline">Browse Groups</a>'
    
    premium_badge = '<span class="premium-badge">PREMIUM</span>' if premium else ''
    
    content = f"""
<div class="hero">
<h1>Welcome, {user['full_name']}! 👋 {premium_badge}</h1>
<p>Stay organized, track your progress, and achieve your study goals.</p>
</div>
<div class="cards">
<div class="card"><div class="stat">{len(schedules)}</div><p>Schedules</p></div>
<div class="card"><div class="stat">{len(groups_list)}</div><p>Groups</p></div>
<div class="card"><div class="stat">{len(tasks)}</div><p>Active Tasks</p></div>
</div>
<div class="card"><h2>📅 Upcoming Schedule</h2>{schedule_html}</div>
<div class="card"><h2>👥 My Groups</h2>{groups_html}</div>
"""
    return render_page("Dashboard", content)
# =========================================================
# SCHEDULE
# =========================================================
def render_schedule_item(item, is_past=False):
    past_class = "schedule-past" if is_past else ""
    badge_class = "badge-done" if is_past else "badge-pending"
    return f"""
<div class="schedule-item {past_class}">
<h3>{item['title']}</h3>
<p><strong>{item['schedule_date']} — {item['schedule_time']}</strong></p>
<p>{item['description'] or ''}</p>
<span class="badge {badge_class}">Reminder: {item['reminder_minutes']} min before</span>
<form method="POST" action="/schedule/{item['id']}/delete" style="display:inline;margin-left:8px;"
onsubmit="return confirm('Delete this schedule?');">
<button type="submit" class="btn-red" style="padding:6px 12px;font-size:13px;">🗑️ Delete</button>
</form>
</div>"""

@app.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():
    user = current_user()
    now = datetime.now(TIMEZONE)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        date = request.form.get("date", "")
        time_str = request.form.get("time", "")
        reminder = max(0, int(request.form.get("reminder_minutes", 10)) or 10)
        if not title or not date or not time_str:
            flash("Please complete required fields.", "danger")
            return redirect(url_for("schedule"))
        execute("""INSERT INTO schedules (user_id, title, description, schedule_date, schedule_time, reminder_minutes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user["id"], title, description, date, time_str, reminder))
        flash("✅ Schedule added!", "success")
        return redirect(url_for("schedule"))
    
    schedules = execute("SELECT * FROM schedules WHERE user_id = ? AND is_deleted = 0 ORDER BY schedule_date DESC, schedule_time DESC",
                        (user["id"],), fetch=True)
    upcoming, past = [], []
    for item in schedules:
        try:
            dt = datetime.strptime(f"{item['schedule_date']} {item['schedule_time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TIMEZONE)
            upcoming.append(item) if dt >= now else past.append(item)
        except:
            upcoming.append(item)
    
    upcoming_html = "".join(render_schedule_item(i, False) for i in upcoming) or "<p>No upcoming schedules.</p>"
    past_html = "".join(render_schedule_item(i, True) for i in past) or "<p>No past schedules.</p>"
    
    content = f"""
<div class="card">
<h2>➕ Add Schedule</h2>
<form method="POST">
<label>Title / Subject</label>
<input name="title" placeholder="e.g. Math Review" required>
<label>Description</label>
<textarea name="description" placeholder="Topics to cover..."></textarea>
<label>Date</label>
<input type="date" name="date" required>
<label>Time</label>
<input type="time" name="time" required>
<label>Reminder</label>
<select name="reminder_minutes">
<option value="0">At time</option>
<option value="5">5 min before</option>
<option value="10" selected>10 min before</option>
<option value="30">30 min before</option>
<option value="60">1 hour before</option>
</select>
<button class="btn-primary" type="submit">Add Schedule</button>
</form>
</div>
<div class="card"><h2>🔜 Upcoming ({len(upcoming)})</h2>{upcoming_html}</div>
<div class="card"><h2>⏳ Past Schedules ({len(past)})</h2>{past_html}</div>
"""
    return render_page("Schedule", content)

@app.route("/schedule/<int:sched_id>/delete", methods=["POST"])
@login_required
def delete_schedule(sched_id):
    user = current_user()
    if not execute("SELECT 1 FROM schedules WHERE id = ? AND user_id = ?", (sched_id, user["id"]), fetch=True):
        flash("Schedule not found.", "danger")
        return redirect(url_for("schedule"))
    execute("UPDATE schedules SET is_deleted = 1 WHERE id = ? AND user_id = ?", (sched_id, user["id"]))
    flash("🗑️ Schedule deleted.", "success")
    return redirect(url_for("schedule"))

@app.route("/api/upcoming")
@login_required
def upcoming():
    user = current_user()
    schedules = execute("SELECT * FROM schedules WHERE user_id = ? AND is_deleted = 0", (user["id"],), fetch=True)
    now = datetime.now(TIMEZONE)
    result = []
    for item in schedules:
        try:
            dt = datetime.strptime(f"{item['schedule_date']} {item['schedule_time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TIMEZONE)
            sec = (dt - now).total_seconds()
            if 0 <= sec <= item["reminder_minutes"] * 60:
                result.append({"id": item["id"], "title": item["title"],
                               "schedule_date": item["schedule_date"], "schedule_time": item["schedule_time"]})
        except: pass
    return jsonify(result)
# =========================================================
# GROUPS
# =========================================================
@app.route("/groups", methods=["GET", "POST"])
@login_required
def groups():
    user = current_user()
    if request.method == "POST":
        if request.form.get("action") == "create":
            name = request.form.get("name", "").strip()
            desc = request.form.get("description", "").strip()
            if not name:
                flash("Group name is required.", "danger")
                return redirect(url_for("groups"))
            code = secrets.token_hex(4).upper()
            execute("""INSERT INTO groups (name, description, join_code, owner_id) VALUES (?, ?, ?, ?)""",
                    (name, desc, code, user["id"]))
            group_id = execute("SELECT id FROM groups WHERE join_code = ?", (code,), fetch=True)[0]["id"]
            execute("INSERT INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, user["id"]))
            add_activity(group_id, user["id"], "Created the group")
            flash(f"✅ Group created! Code: {code}", "success")
        elif request.form.get("action") == "join":
            code = request.form.get("join_code", "").strip().upper()
            found = execute("SELECT * FROM groups WHERE join_code = ?", (code,), fetch=True)
            if not found:
                flash("Group code not found.", "danger")
            else:
                gid = found[0]["id"]
                if execute("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (gid, user["id"]), fetch=True):
                    flash("Already in this group.", "info")
                else:
                    execute("INSERT INTO group_members VALUES (?, ?)", (gid, user["id"]))
                    add_activity(gid, user["id"], "Joined the group")
                    flash("✅ Joined group!", "success")
        return redirect(url_for("groups"))
    
    groups_list = execute("SELECT g.* FROM groups g JOIN group_members gm ON gm.group_id = g.id WHERE gm.user_id = ? ORDER BY g.name",
                          (user["id"],), fetch=True)
    groups_html = ""
    for g in groups_list:
        groups_html += f"""
<div class="task">
<h3>{g['name']}</h3>
<p>{g['description'] or ''}</p>
<p class="small">Join Code: <strong>{g['join_code']}</strong></p>
<a class="btn btn-primary" href="/group/{g['id']}">Open Group →</a>
</div>"""
    
    content = f"""
<div class="cards">
<div class="card">
<h2>➕ Create Group</h2>
<form method="POST">
<input type="hidden" name="action" value="create">
<label>Group Name</label>
<input name="name" required>
<label>Description</label>
<textarea name="description"></textarea>
<button class="btn-primary" type="submit">Create Group</button>
</form>
</div>
<div class="card">
<h2>🔑 Join Group</h2>
<form method="POST">
<input type="hidden" name="action" value="join">
<label>Group Code</label>
<input name="join_code" placeholder="A1B2C3D4" required>
<button class="btn-outline" type="submit">Join Group</button>
</form>
</div>
</div>
<div class="card"><h2>👥 My Groups</h2>{groups_html or '<p>Not in any group yet.</p>'}</div>
"""
    return render_page("Groups", content)
# =========================================================
# GROUP PAGE
# =========================================================
@app.route("/group/<int:group_id>", methods=["GET", "POST"])
@login_required
def group_page(group_id):
    user = current_user()
    if not execute("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user["id"]), fetch=True):
        return "Access denied", 403
    group_result = execute("SELECT * FROM groups WHERE id = ?", (group_id,), fetch=True)
    if not group_result:
        return "Group not found", 404
    group = group_result[0]
    
    if request.method == "POST":
        action = request.form.get("action", "create_task")
        if action == "create_task":
            title = request.form.get("title", "").strip()
            desc = request.form.get("description", "").strip()
            assigned = request.form.get("assigned_to")
            deadline = request.form.get("deadline", "").strip()
            if not title:
                flash("Task title is required.", "danger")
                return redirect(url_for("group_page", group_id=group_id))
            assigned_id = None
            if assigned:
                try:
                    assigned_id = int(assigned)
                    if not execute("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, assigned_id), fetch=True):
                        flash("Assignee is not a member.", "danger")
                        return redirect(url_for("group_page", group_id=group_id))
                except: pass
            execute("""INSERT INTO tasks (group_id, title, description, assigned_to, deadline)
                       VALUES (?, ?, ?, ?, ?)""", (group_id, title, desc, assigned_id, deadline))
            add_activity(group_id, user["id"], f"Created task: {title}")
            flash("✅ Task added!", "success")
            
        elif action == "update_task":
            try:
                tid = int(request.form.get("task_id"))
                progress = max(0, min(100, int(request.form.get("progress", 0))))
            except:
                flash("Invalid task info.", "danger")
                return redirect(url_for("group_page", group_id=group_id))
            proof = request.form.get("proof", "").strip()
            status = request.form.get("status", "Pending")
            if progress >= 100: status = "Completed"
            elif progress > 0: status = "In Progress"
            if not execute("SELECT 1 FROM tasks WHERE id = ? AND group_id = ?", (tid, group_id), fetch=True):
                flash("Task not found.", "danger")
                return redirect(url_for("group_page", group_id=group_id))
            execute("""UPDATE tasks SET status = ?, progress = ?, proof = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND group_id = ?""", (status, progress, proof, tid, group_id))
            add_activity(group_id, user["id"], f"Updated task — {progress}%")
            flash("✅ Task updated!", "success")
            
        elif action == "delete_task":
            try:
                tid = int(request.form.get("task_id"))
            except:
                flash("Invalid task.", "danger")
                return redirect(url_for("group_page", group_id=group_id))
            task = execute("SELECT title FROM tasks WHERE id = ? AND group_id = ?", (tid, group_id), fetch=True)
            if task:
                execute("DELETE FROM tasks WHERE id = ? AND group_id = ?", (tid, group_id))
                add_activity(group_id, user["id"], f"Deleted task: {task[0]['title']}")
                flash("🗑️ Task deleted.", "success")
        return redirect(url_for("group_page", group_id=group_id))
    
    members = execute("SELECT u.* FROM users u JOIN group_members gm ON
