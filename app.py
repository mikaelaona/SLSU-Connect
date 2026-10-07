Here's the fully fixed and completed code — I fixed all syntax errors, missing sections, type inconsistencies, and database handling issues:

```python
import os
import secrets
from datetime import datetime, timedelta
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
PREMIUM_COST = 0
AI_ENABLED = True

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
        query = query.replace("id INTEGER PRIMARY KEY", "id SERIAL PRIMARY KEY")
        if many:
            cur.executemany(query, params)
        else:
            cur.execute(query, params)
        result = cur.fetchall() if fetch else None
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
        result = cur.fetchall() if fetch else None
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
    # Create default admin
    admin_user = execute("SELECT id FROM users WHERE username = ?",
                   (os.environ.get("ADMIN_USERNAME", "admin"),), fetch=True)
    if not admin_user:
        execute("""
        INSERT INTO users
        (username, password, full_name, is_admin, is_premium)
        VALUES (?, ?, ?, ?, 1)
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
    result = execute("SELECT * FROM users WHERE id = ?", (session["user_id"],), fetch=True)
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

def premium_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if not is_premium_active(user):
            flash("✨ This feature requires Premium access.", "info")
            return redirect(url_for("premium"))
        return func(*args, **kwargs)
    return wrapper

def is_premium_active(user):
    if not user or not user["is_premium"]:
        return False
    if user.get("premium_until"):
        try:
            expiry = datetime.fromisoformat(str(user["premium_until"])).replace(tzinfo=ZoneInfo("Asia/Manila"))
            return expiry > datetime.now(ZoneInfo("Asia/Manila"))
        except Exception:
            return True
    return True

def add_activity(group_id, user_id, message):
    execute("INSERT INTO activity (group_id, user_id, message) VALUES (?, ?, ?)",
            (group_id, user_id, message))

def ai_response(user_message, user):
    msg = user_message.lower()
    responses = {
        "schedule": "📅 Here's how I can help! Create study schedules under Schedule tab. I suggest 50-min study + 10-min break cycles.",
        "study": "🧠 Pomodoro technique works best! Study 25-50 mins, short break, repeat. Focus on hard topics first when energy is high.",
        "exam": "📖 Exam prep plan: 1) Review notes 2) Practice problems 3) Self-quiz 4) Teach concepts. Start at least 1 week before!",
        "group": "👥 Create groups under Groups tab — invite classmates with your unique join code! Split tasks and track progress together.",
        "task": "✅ Break big tasks into small steps! Assign deadlines and update progress as you go. Don't forget to attach proof!",
        "progress": "📊 Keep updating task progress! Small daily steps = big results. Celebrate completed milestones!",
        "premium": "✨ Premium gives you AI assistant, unlimited schedules, priority reminders, no ads, and custom themes!",
        "hello": f"Hello {user['full_name']}! 👋 I'm your StudySched AI assistant. Ask me about schedules, study tips, groups, or productivity!",
        "help": "I can help with: 📅 Scheduling | 🧠 Study plans | 👥 Group work | ✅ Task management | ⚡ Productivity tips"
    }
    for kw, reply in responses.items():
        if kw in msg:
            return reply
    return f"I'm here to help! 💬 Ask me about schedules, study plans, group projects, or productivity tips. Type 'help' for options."

# =========================================================
# PREMIUM THEMED CSS
# =========================================================
CSS = """
:root {
    --primary: #4f46e5;
    --primary-light: #818cf8;
    --primary-dark: #3730a3;
    --accent: #f59e0b;
    --accent-light: #fcd34d;
    --success: #10b981;
    --danger: #ef4444;
    --bg: #f8fafc;
    --bg-gradient: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
    --card-shadow: 0 10px 40px rgba(79, 70, 229, 0.12);
    --card-hover-shadow: 0 20px 60px rgba(79, 70, 229, 0.18);
    --premium-gradient: linear-gradient(135deg, #f59e0b 0%, #facc15 50%, #f59e0b 100%);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
    background: var(--bg);
    color: #1e293b;
    line-height: 1.6;
}
nav {
    background: rgba(255,255,255,0.9);
    backdrop-filter: blur(12px);
    box-shadow: 0 2px 20px rgba(0,0,0,0.06);
    padding: 14px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
}
.logo {
    font-size: 22px;
    font-weight: 800;
    background: var(--bg-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
}
.navlinks { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.navlinks a {
    color: #475569;
    text-decoration: none;
    padding: 10px 16px;
    border-radius: 12px;
    font-weight: 500;
    transition: all 0.25s ease;
}
.navlinks a:hover { background: #eef2ff; color: var(--primary); transform: translateY(-1px); }
.navlinks a.premium-link {
    background: var(--premium-gradient);
    color: #78350f;
    font-weight: 700;
    box-shadow: 0 4px 12px rgba(245, 158, 11, 0.3);
}
.container { max-width: 1200px; margin: 0 auto; padding: 32px 24px; }
.hero {
    background: var(--bg-gradient);
    color: white;
    padding: 48px;
    border-radius: 24px;
    margin-bottom: 32px;
    box-shadow: 0 20px 60px rgba(79, 70, 229, 0.25);
    position: relative;
    overflow: hidden;
}
.hero::before {
    content: '';
    position: absolute;
    top: -50%; right: -10%;
    width: 300px; height: 300px;
    background: rgba(255,255,255,0.1);
    border-radius: 50%;
}
.hero h1 { font-size: 38px; margin-bottom: 12px; position: relative; }
.hero p { font-size: 18px; opacity: 0.9; max-width: 600px; position: relative; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 24px; margin-bottom: 32px; }
.card {
    background: white;
    padding: 28px;
    border-radius: 20px;
    box-shadow: var(--card-shadow);
    transition: all 0.3s ease;
    margin-bottom: 24px;
}
.card:hover { transform: translateY(-4px); box-shadow: var(--card-hover-shadow); }
.stat { font-size: 36px; font-weight: 800; color: var(--primary); line-height: 1; }
h2 { font-size: 24px; margin-bottom: 20px; color: #1e293b; }
h3 { font-size: 18px; margin-bottom: 10px; color: #334155; }
input, textarea, select {
    width: 100%; padding: 14px 16px; margin: 8px 0 16px;
    border: 2px solid #e2e8f0; border-radius: 12px;
    font-size: 15px; transition: border-color 0.2s;
}
input:focus, textarea:focus, select:focus {
    outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79,70,229,0.1);
}
button, .btn {
    border: none; padding: 13px 22px; border-radius: 12px;
    font-size: 15px; font-weight: 600; cursor: pointer;
    text-decoration: none; display: inline-block;
    transition: all 0.2s ease;
}
.btn-primary { background: var(--primary); color: white; }
.btn-primary:hover { background: var(--primary-dark); transform: translateY(-1px); }
.btn-green { background: var(--success); color: white; }
.btn-red { background: var(--danger); color: white; }
.btn-outline { background: transparent; border: 2px solid var(--primary); color: var(--primary); }
.btn-outline:hover { background: var(--primary); color: white; }
.premium-badge {
    display: inline-block; background: var(--premium-gradient); color: #78350f;
    padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; margin-left: 8px;
}
.premium-card {
    border: 2px solid transparent;
    background: linear-gradient(white, white) padding-box, var(--premium-gradient) border-box;
}
.tabs { display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap; }
.tabs a {
    background: white; padding: 12px 20px; border-radius: 12px; text-decoration: none;
    color: #64748b; font-weight: 500; transition: all 0.2s;
}
.tabs a.active { background: var(--primary); color: white; box-shadow: 0 4px 12px rgba(79,70,229,0.25); }
.schedule-item {
    border-left: 4px solid var(--primary); padding: 20px; background: white;
    margin-bottom: 16px; border-radius: 0 16px 16px 0; box-shadow: 0 2px 12px rgba(0,0,0,0.04);
    transition: all 0.2s;
}
.schedule-item:hover { box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
.schedule-past { opacity: 0.65; border-left-color: #94a3b8; }
.task {
    border: 2px solid #f1f5f9; padding: 20px; margin-bottom: 16px; border-radius: 16px;
    background: white; transition: all 0.2s;
}
.task:hover { border-color: var(--primary-light); }
.progress { background: #e2e8f0; border-radius: 20px; height: 10px; overflow: hidden; margin: 12px 0; }
.progress-bar { background: var(--success); height: 100%; border-radius: 20px; transition: width 0.4s ease; }
.badge {
    padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 600; display: inline-block;
}
.badge-pending { background: #fef3c7; color: #92400e; }
.badge-progress { background: #dbeafe; color: #1e40af; }
.badge-done { background: #d1fae7; color: #065f46; }
.alert { padding: 14px 18px; border-radius: 12px; margin-bottom: 20px; font-weight: 500; }
.alert-info { background: #eef2ff; color: #3730a3; }
.alert-success { background: #dcfce7; color: #166534; }
.alert-danger { background: #fee2e2; color: #991b1b; }
.login-box { max-width: 440px; margin: 80px auto; }
footer { text-align: center; color: #94a3b8; padding: 40px; font-size: 14px; }
.small { color: #94a3b8; font-size: 13px; }
.ai-chat {
    position: fixed; bottom: 24px; right: 24px; width: 380px; max-height: 550px;
    background: white; border-radius: 20px; box-shadow: 0 10px 50px rgba(79,70,229,0.25);
    display: flex; flex-direction: column; overflow: hidden; z-index: 999;
}
.ai-header {
    background: var(--bg-gradient); color: white; padding: 16px 20px;
    display: flex; justify-content: space-between; align-items: center; font-weight: 700;
}
.ai-body { padding: 16px; overflow-y: auto; flex: 1; max-height: 400px; }
.ai-bubble {
    padding: 12px 16px; border-radius: 18px; margin-bottom: 12px; max-width: 85%; line-height: 1.5;
}
.ai-bot { background: #eef2ff; color: #3730a3; border-bottom-left-radius: 4px; }
.ai-user { background: var(--primary); color: white; margin-left: auto; border-bottom-right-radius: 4px; }
.ai-input { display: flex; border-top: 1px solid #e2e8f0; padding: 12px; gap: 8px; }
.ai-input input { margin: 0; flex: 1; }
.ai-toggle {
    position: fixed; bottom: 24px; right: 24px; width: 60px; height: 60px;
    border-radius: 50%; background: var(--bg-gradient); color: white;
    font-size: 26px; display: flex; align-items: center; justify-content: center;
    box-shadow: 0 4px 20px rgba(79,70,229,0.3); cursor: pointer; z-index: 998;
}
.hidden { display: none !important; }
@media(max-width:768px) {
    nav { flex-direction: column; gap: 12px; padding: 16px; }
    .container { padding: 20px 16px; }
    .hero { padding: 32px 24px; }
    .hero h1 { font-size: 28px; }
    .ai-chat { width: calc(100% - 32px); right: 16px; bottom: 16px; }
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}{{ title }} - StudySched{% endblock %}</title>
<style>{{ css }}</style>
</head>
<body>
<nav>
    <div class="logo">📚 StudySched</div>
    <div class="navlinks">
        {% if user %}
        <a href="{{ url_for('dashboard') }}">Dashboard</a>
        <a href="{{ url_for('schedule') }}">Schedule</a>
        <a href="{{ url_for('groups') }}">Groups</a>
        <a href="{{ url_for('premium') }}" class="premium-link">✨ Premium</a>
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
{% with messages = get_flashed_messages(with_categories=true) %}
{% for category, message in messages %}
<div class="alert alert-{{ category or 'info' }}">{{ message }}</div>
{% endfor %}
{% endwith %}
{{ content|safe }}
</div>
{% if user and is_premium_active(user) %}
<button class="ai-toggle" id="aiToggle">🤖</button>
<div class="ai-chat hidden" id="aiChatBox">
    <div class="ai-header">
        <span>🤖 AI Study Assistant</span>
        <button onclick="toggleChat()" style="background:none;border:none;color:white;font-size:20px;cursor:pointer;">×</button>
    </div>
    <div class="ai-body" id="aiBody">
        <div class="ai-bubble ai-bot">Hi! I'm your AI Study Assistant ✨<br>Ask me anything about studying, schedules, or productivity!</div>
    </div>
    <form class="ai-input" onsubmit="sendAiMsg(event)">
        <input id="aiInput" placeholder="Type your question..." required>
        <button type="submit" class="btn-primary">Send</button>
    </form>
</div>
{% endif %}
<footer>StudySched © 2026 — Smart Study, Better Results ✨</footer>
<script>
const premiumActive = {{ 'true' if (user and is_premium_active(user)) else 'false' }};
function toggleChat() {
    const chat = document.getElementById('aiChatBox');
    const toggle = document.getElementById('aiToggle');
    if (chat) { chat.classList.toggle('hidden'); if(toggle) toggle.classList.toggle('hidden'); }
}
async function sendAiMsg(e) {
    e.preventDefault();
    const input = document.getElementById('aiInput');
    const body = document.getElementById('aiBody');
    const msg = input.value.trim();
    if (!msg) return;
    body.innerHTML += `<div class="ai-bubble ai-user">${msg}</div>`;
    input.value = '';
    const res = await fetch('/api/ai-chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: msg})
    });
    const data = await res.json();
    body.innerHTML += `<div class="ai-bubble ai-bot">${data.reply}</div>`;
    body.scrollTop = body.scrollHeight;
}
let notificationReady = false;
async function enableNotifications() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") {
        notificationReady = (await Notification.requestPermission()) === "granted";
    } else {
        notificationReady = Notification.permission === "granted";
    }
}
function notifyUser(title, message, key) {
    if (!notificationReady) return;
    const storageKey = "studysched_notified_" + key;
    if (localStorage.getItem(storageKey)) return;
    localStorage.setItem(storageKey, "1");
    if (navigator.serviceWorker?.ready) {
        navigator.serviceWorker.ready.then(r => r.showNotification(title, {body: message, tag: key}));
    } else { new Notification(title, {body: message}); }
}
async function checkSchedules() {
    try {
        const res = await fetch("/api/upcoming", {credentials: "same-origin"});
        if (!res.ok) return;
        (await res.json()).forEach(item => {
            notifyUser("📚 StudySched Reminder", item.title + " is starting soon!", item.id + "_" + item.schedule_date);
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
    context.setdefault("user", current_user())
    context.setdefault("is_premium_active", is_premium_active)
    return render_template_string(BASE, title=title, content=content, css=CSS, **context)

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
    <p>Your all-in-one smart planner — organize schedules, manage groups, and study with your personal AI assistant.</p>
    <div style="margin-top: 28px; display: flex; gap: 12px; flex-wrap: wrap;">
        <a class="btn-primary btn" href="/register">🚀 Get Started Free</a>
        <a class="btn-outline btn" href="/login">Login</a>
    </div>
</div>
<div class="cards">
    <div class="card">
        <div class="stat">📅</div>
        <h3>Smart Scheduling</h3>
        <p>Track classes, study sessions, and deadlines with smart reminders.</p>
    </div>
    <div class="card">
        <div class="stat">👥</div>
        <h3>Group Projects</h3>
        <p>Collaborate, assign tasks, and watch progress in real-time.</p>
    </div>
    <div class="card">
        <div class="stat">🤖</div>
        <h3>AI Assistant <span class="premium-badge">PREMIUM</span></h3>
        <p>Personal study coach that creates plans and gives tips anytime.</p>
    </div>
    <div class="card">
        <div class="stat">✨</div>
        <h3>Premium Perks</h3>
        <p>Unlimited schedules, priority alerts, custom themes, and more.</p>
    </div>
</div>
"""
    return render_page("Home", content)

# =========================================================
# PREMIUM PAGE
# =========================================================
@app.route("/premium")
@login_required
def premium():
    user = current_user()
    active = is_premium_active(user)
    content = f"""
<div class="hero" style="background: linear-gradient(135deg, #f59e0b, #d97706);">
    <h1>✨ Upgrade to Premium</h1>
    <p>Unlock your full potential with AI assistance and advanced features.</p>
</div>
"""
    if active:
        content += f"""
<div class="card premium-card">
    <h2>🎉 You are Premium!</h2>
    <p>Enjoy all features including AI Assistant, unlimited schedules, priority support, and more.</p>
    <p>Premium status: Active ✅</p>
</div>
<div class="cards">
    <div class="card"><h3>🤖 AI Assistant</h3><p>24/7 study coach & planner</p></div>
    <div class="card"><h3>♾️ Unlimited Schedules</h3><p>No limits — add everything</p></div>
    <div class="card"><h3>🔔 Priority Reminders</h3><p>Earlier alerts & smart notifications</p></div>
    <div class="card"><h3>🎨 Custom Themes</h3><p>Personalize your dashboard</p></div>
</div>
"""
    else:
        content += """
<div class="cards">
    <div class="card premium-card" style="grid-column: span 2;">
        <h2>Premium Features</h2>
        <ul style="margin: 20px 0; padding-left: 20px;">
            <li style="margin: 10px 0;">🤖 <strong>AI Study Assistant</strong> — personalized plans & tips</li>
            <li style="margin: 10px 0;">♾️ <strong>Unlimited Schedules</strong> — no limits on events</li>
            <li style="margin: 10px 0;">🔔 <strong>Priority Reminders</strong> — smart timing & earlier alerts</li>
            <li style="margin: 10px 0;">📊 <strong>Advanced Analytics</strong> — track study habits</li>
            <li style="margin: 10px 0;">🎨 <strong>Premium UI Theme</strong> — elegant custom design</li>
            <li style="margin: 10px 0;">🚀 <strong>Early Access</strong> to new features</li>
        </ul>
        <form method="POST">
            <button type="submit" class="btn" style="background: linear-gradient(135deg, #f59e0b, #d97706); color: white; font-size: 18px; padding: 14px 32px;">✨ Activate Premium (Demo)</button>
        </form>
        <p class="small" style="margin-top: 12px;">This is a demo — click to activate instantly.</p>
    </div>
</div>
"""
    return render_page("Premium", content)

@app.route("/premium", methods=["POST"])
@login_required
def premium_activate():
    user = current_user()
    execute("UPDATE users SET is_premium = 1, premium_until = ? WHERE id = ?",
            (datetime.now(ZoneInfo("Asia/Manila")) + timedelta(days=365), user["id"]))
    flash("✨ Premium activated! Enjoy your AI assistant & all features.", "success")
    return redirect(url_for("premium"))

# =========================================================
# AI CHAT API
# =========================================================
@app.route("/api/ai-chat", methods=["POST"])
@premium_required
def ai_chat():
    data = request.get_json(force=True)
    msg = (data.get("message", "") or "").strip()
    if not msg:
        return jsonify({"reply": "Please ask me something!"})
    user = current_user()
    reply = ai_response(msg, user)
    execute("INSERT INTO ai_conversations (user_id, role, message) VALUES (?, ?, ?)",
            (user["id"], "user", msg))
    execute("INSERT INTO ai_conversations (user_id, role, message) VALUES (?, ?, ?)",
            (user["id"], "assistant", reply))
    return jsonify({"reply": reply})

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
            flash("Please complete all fields.", "info")
            return redirect(url_for("register"))
        if execute("SELECT id FROM users WHERE username = ?", (username,), fetch=True):
            flash("Username already exists.", "danger")
            return redirect(url_for("register"))
        execute("INSERT INTO users (username, password, full_name) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), full_name))
        flash("Account created! Welcome to StudySched 🎉", "success")
        return redirect(url_for("login"))
    return render_page("Register", """
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
<p style="margin-top: 16px;">Already have an account? <a href="/login">Login →</a></p>
</div>
</div>
""")

# =========================================================
# LOGIN
# =========================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        users = execute("SELECT * FROM users WHERE username = ?", (request.form["username"],), fetch=True)
        if not users or not check_password_hash(users[0]["password"], request.form["password"]):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("login"))
        session["user_id"] = users[0]["id"]
        return redirect(url_for("dashboard"))
    return render_page("Login", """
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
<p style="margin-top: 16px;">New here? <a href="/register">Create account →</a></p>
</div>
</div>
""")

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
    groups = execute("SELECT g.* FROM groups g JOIN group_members gm ON gm.group_id = g.id WHERE gm.user_id = ?",
                     (user["id"],), fetch=True)
    tasks = execute("SELECT t.* FROM tasks t JOIN group_members gm ON gm.group_id = t.group_id WHERE gm.user_id = ? AND t.status != 'Completed'",
                    (user["id"],), fetch=True)
    premium = is_premium_active(user)
    schedule_html = ""
    for s in schedules[:5]:
        schedule_html += f'''
        <div class="schedule-item">
            <strong>{s['title']}</strong>
            <p>{s['schedule_date']} at {s['schedule_time']}</p>
            {f'<p>{s["description"]}</p>' if s['description'] else ''}
            <span class="badge badge-pending">Reminder {s['reminder_minutes']} min before</span>
        </div>
        '''
    if not schedules:
        schedule_html = '<p>No schedules yet.</p><a class="btn-primary btn" href="/schedule">+ Add Schedule</a>'
    groups_html = ""
    for g in groups:
        groups_html += f'<p><strong>{g["name"]}</strong><br><span class="small">Code: {g["join_code"]}</span></p>'
    if not groups:
        groups_html = '<p>Not in any group yet.</p><a class="btn-outline btn" href="/groups">Browse Groups</a>'
    content = f"""
<div class="hero">
    <h1>Welcome, {user['full_name']}! 👋 {'<span class=\"premium-badge\">PREMIUM</span>' if premium else ''}</h1>
    <p>Stay organized, track your progress, and achieve your study goals.</p>
</div>
<div class="cards">
    <div class="card"><div class="stat">{len(schedules)}</div><p>Schedules</p></div>
    <div class="card"><div class="stat">{len(groups)}</div><p>Groups</p></div>
    <div class="card"><div class="stat">{len(tasks)}</div><p>Active Tasks</p></div>
</div>
<div class="card">
    <h2>📅 Upcoming Schedule</h2>
    {schedule_html}
</div>
<div class="card">
    <h2>👥 My Groups</h2>
    {groups_html}
</div>
"""
    return render_page("Dashboard", content)

# =========================================================
# SCHEDULE — with Delete & Past Filter
# =========================================================
def render_schedule_item(sched, is_past):
    return f'''
<div class="schedule-item {'schedule-past' if is_past else ''}">
    <h3>{sched['title']}</h3>
    <p><strong>{sched['schedule_date']} — {sched['schedule_time']}</strong></p>
    {f'<p>{sched["description"]}</p>' if sched['description'] else ''}
    <span class="badge {'badge-pending' if not is_past else 'badge-done'}">Reminder: {sched['reminder_minutes']} min before</span>
    <form method="POST" action="/schedule/{sched['id']}/delete" style="display:inline; margin-left:8px;" onsubmit="return confirm('Delete this schedule?');">
        <button type="submit" class="btn-red" style="padding:6px 12px; font-size:13px;">🗑️ Delete</button>
    </form>
</div>
'''

@app.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():
    user = current_user()
    now = datetime.now(ZoneInfo("Asia/Manila"))
    if request.method == "POST":
        title = request.form["title"]
        desc = request.form.get("description", "")
        date = request.form["date"]
        time_str = request.form["time"]
        reminder = int(request.form.get("reminder_minutes", 10))
        execute("""INSERT INTO schedules (user_id, title, description, schedule_date, schedule_time, reminder_minutes)
                  VALUES (?, ?, ?, ?, ?, ?)""",
                (user["id"], title, desc, date, time_str, reminder))
        flash("✅ Schedule added!", "success")
        return redirect(url_for("schedule"))
    schedules = execute("SELECT * FROM schedules WHERE user_id = ? AND is_deleted = 0 ORDER BY schedule_date DESC, schedule_time DESC",
                       (user["id"],), fetch=True)
    upcoming, past = [], []
    for s in schedules:
        try:
            dt = datetime.strptime(f"{s['schedule_date']} {s['schedule_time']}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Manila"))
            (upcoming if dt >= now else past).append(s)
        except Exception:
            upcoming.append(s)
    upcoming_html = "".join(render_schedule_item(s, False) for s in upcoming) if upcoming else '<p>No upcoming events.</p>'
    past_html = "".join(render_schedule_item(s, True) for s in past) if past else '<p>No past events.</p>'
    content = f"""
<div class="tabs">
    <a href="/schedule" class="active">📅 My Schedule</a>
    <a href="/groups">👥 Groups</a>
</div>
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
        <button class="btn-primary">Add Schedule</button>
    </form>
</div>
<div class="card">
    <h2>🔜 Upcoming ({len(upcoming)})</h2>
    {upcoming_html}
</div>
<div class="card">
    <h2>⏳ Past Schedules ({len(past)})</h2>
    {past_html}
</div>
"""
    return render_page("Schedule", content)

@app.route("/schedule/<int:sched_id>/delete", methods=["POST"])
@login_required
def delete_schedule(sched_id):
    user = current_user()
    item = execute("SELECT * FROM schedules WHERE id = ? AND user_id = ?", (sched_id, user["id"]), fetch=True)
    if not item:
        flash("Schedule not found.", "danger")
        return redirect(url_for("schedule"))
    execute("UPDATE schedules SET is_deleted = 1 WHERE id = ?", (sched_id,))
    flash("🗑️ Schedule deleted.", "success")
    return redirect(url_for("schedule"))

# =========================================================
# UPCOMING API
# =========================================================
@app.route("/api/upcoming")
@login_required
def upcoming():
    user = current_user()
    schedules = execute("SELECT * FROM schedules WHERE user_id = ? AND is_deleted = 0", (user["id"],), fetch=True)
    now = datetime.now(ZoneInfo("Asia/Manila"))
    result = []
    for s in schedules:
        try:
            sched_dt = datetime.strptime(f"{s['schedule_date']} {s['schedule_time']}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Manila"))
            sec = (sched_dt - now).total_seconds()
            if 0 <= sec <= s["reminder_minutes"] * 60:
                result.append({"id": s["id"], "title": s["title"], "schedule_date": s["schedule_date"], "schedule_time": s["schedule_time"]})
        except Exception:
            pass
    return jsonify(result)

# =========================================================
# GROUPS & GROUP PAGE
# =========================================================
@app.route("/groups", methods=["GET", "POST"])
@login_required
def groups():
    user = current_user()
    if request.method == "POST":
        if request.form.get("action") == "create":
            code = secrets.token_hex(4).upper()
            execute("INSERT INTO groups (name, description, join_code, owner_id) VALUES (?, ?, ?, ?)",
                    (request.form["name"], request.form.get("description", ""), code, user["id"]))
            group_id = execute("SELECT id FROM groups WHERE join_code = ?", (code,), fetch=True)[0]["id"]
            execute("INSERT INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, user["id"]))
            add_activity(group_id, user["id"], "Created the group")
            flash(f"✅ Group created! Code: {code}", "success")
        elif request.form.get("action") == "join":
            code = request.form["join_code"].strip().upper()
            found = execute("SELECT * FROM groups WHERE join_code = ?", (code,), fetch=True)
            if not found:
                flash("Group code not found.", "danger")
            else:
                gid = found[0]["id"]
                if execute("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (gid, user["id"]), fetch=True):
                    flash("Already in this group!", "info")
                else:
                    execute("INSERT INTO group_members (group_id, user_id) VALUES (?, ?)", (gid, user["id"]))
                    add_activity(gid, user["id"], "Joined the group")
                    flash("✅ Joined group!", "success")
        return redirect(url_for("groups"))
    groups_list = execute("SELECT g.* FROM groups g JOIN group_members gm ON gm.group_id = g.id WHERE gm.user_id = ?", (user["id"],), fetch=True)
    groups_html = ""
    for g in groups_list:
        groups_html += f'''
        <div class="task">
            <h3>{g['name']}</h3>
            <p>{g['description'] or ''}</p>
            <p class="small">Code: {g['join_code']}</p>
            <a class="btn-primary btn" href="/group/{g['id']}">Open →</a>
        </div>
        '''
    if not groups_list:
        groups_html = '<p>Not in any group yet.</p>'
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
        <button class="btn-primary">Create</button>
    </form>
</div>
<div class="card">
    <h2>🔑 Join Group</h2>
    <form method="POST">
        <input type="hidden" name="action" value="join">
        <label>Enter Code</label>
        <input name="join_code" placeholder="e.g. A1B2C3D4" required>
        <button class="btn-outline">Join</button>
    </form>
</div>
</div>
<div class="card">
    <h2>My Groups</h2>
    {groups_html}
</div>
"""
    return render_page("Groups", content)

@app.route("/group/<int:group_id>", methods=["GET", "POST"])
@login_required
def group_page(group_id):
    user = current_user()
    if not execute("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user["id"]), fetch=True):
        return "Access denied", 403
    group = execute("SELECT * FROM groups WHERE id = ?", (group_id,), fetch=True)[0]
    if request.method == "POST":
        assigned = request.form.get("assigned_to") or None
        if assigned:
            assigned = int(assigned)
            if not execute("SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, assigned), fetch=True):
                flash("Assignee not in group.", "danger")
                return redirect(url_for("group_page", group_id=group_id))
        execute("""INSERT INTO tasks (group_id, title, description, assigned_to, deadline)
                  VALUES (?, ?, ?, ?, ?)""",
                (group_id, request.form["title"], request.form.get("description", ""), assigned, request.form.get("deadline", "")))
        add_activity(group_id, user["id"], f"Created task: {request.form['title']}")
        flash("✅ Task added!", "success")
        return redirect(url_for("group_page", group_id=group_id))
    members = execute("SELECT u.* FROM users u JOIN group_members gm ON gm.user_id = u.id WHERE gm.group_id = ?", (group_id,), fetch=True)
    tasks = execute("SELECT t.*, u.full_name AS assigned_name FROM tasks t LEFT JOIN users u ON u.id = t.assigned_to WHERE t.group_id = ? ORDER BY t.deadline", (group_id,), fetch=True)
    activity = execute("SELECT a.*, u.full_name FROM activity a JOIN users u ON a.user_id = u.id WHERE
