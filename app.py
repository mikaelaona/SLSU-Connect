from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
app.secret_key = "studysched-secret-key-change-this"

DB = Path("studysched.db")


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        day TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        subject TEXT,
        room TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_id INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        UNIQUE(group_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        assigned_to INTEGER,
        due_date TEXT,
        status TEXT DEFAULT 'Pending',
        evidence TEXT DEFAULT '',
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        note TEXT,
        minutes INTEGER DEFAULT 0,
        created_at TEXT
    );
    """)

    conn.commit()
    conn.close()


# =========================
# USER
# =========================

def current_user():
    if "user_id" not in session:
        return None

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (session["user_id"],)
    ).fetchone()

    conn.close()

    return user


# =========================
# HOME
# =========================

@app.route("/")
def index():

    if current_user():
        return redirect(url_for("dashboard"))

    return render_template("index.html")


# =========================
# REGISTER
# =========================

@app.route("/register", methods=["POST"])
def register():

    name = request.form["name"].strip()
    email = request.form["email"].strip().lower()
    password = request.form["password"]

    conn = get_db()

    try:

        cursor = conn.execute(
            """
            INSERT INTO users(name,email,password)
            VALUES(?,?,?)
            """,
            (
                name,
                email,
                generate_password_hash(password)
            )
        )

        conn.commit()

        session["user_id"] = cursor.lastrowid

        return redirect(url_for("dashboard"))

    except sqlite3.IntegrityError:

        return render_template(
            "index.html",
            error="Email is already registered."
        )

    finally:

        conn.close()


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["POST"])
def login():

    email = request.form["email"].strip().lower()
    password = request.form["password"]

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE email=?",
        (email,)
    ).fetchone()

    conn.close()

    if not user:

        return render_template(
            "index.html",
            error="Invalid email or password."
        )

    if not check_password_hash(user["password"], password):

        return render_template(
            "index.html",
            error="Invalid email or password."
        )

    session["user_id"] = user["id"]

    return redirect(url_for("dashboard"))


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("index"))


# =========================
# DASHBOARD
# =========================

@app.route("/dashboard")
def dashboard():

    user = current_user()

    if not user:
        return redirect(url_for("index"))

    conn = get_db()

    schedules = conn.execute(
        """
        SELECT *
        FROM schedules
        WHERE user_id=?
        ORDER BY day,start_time
        """,
        (user["id"],)
    ).fetchall()

    groups = conn.execute(
        """
        SELECT g.*
        FROM groups g
        JOIN group_members gm
        ON gm.group_id=g.id
        WHERE gm.user_id=?
        """,
        (user["id"],)
    ).fetchall()

    tasks = conn.execute(
        """
        SELECT
            t.*,
            g.name AS group_name,
            u.name AS assignee
        FROM tasks t

        JOIN groups g
        ON g.id=t.group_id

        LEFT JOIN users u
        ON u.id=t.assigned_to

        JOIN group_members gm
        ON gm.group_id=g.id

        WHERE gm.user_id=?

        ORDER BY t.due_date
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        user=user,
        schedules=schedules,
        groups=groups,
        tasks=tasks
    )


# =========================
# ADD SCHEDULE
# =========================

@app.route("/schedule/add", methods=["POST"])
def add_schedule():

    if not current_user():
        return redirect(url_for("index"))

    conn = get_db()

    conn.execute(
        """
        INSERT INTO schedules(
            user_id,
            title,
            day,
            start_time,
            end_time,
            subject,
            room
        )
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            session["user_id"],
            request.form["title"],
            request.form["day"],
            request.form["start_time"],
            request.form.get("end_time", ""),
            request.form.get("subject", ""),
            request.form.get("room", "")
        )
    )

    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))


# =========================
# CREATE GROUP
# =========================

@app.route("/group/create", methods=["POST"])
def create_group():

    user = current_user()

    if not user:
        return redirect(url_for("index"))

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO groups(name,owner_id)
        VALUES(?,?)
        """,
        (
            request.form["name"],
            user["id"]
        )
    )

    group_id = cursor.lastrowid

    conn.execute(
        """
        INSERT INTO group_members(group_id,user_id)
        VALUES(?,?)
        """,
        (
            group_id,
            user["id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))


# =========================
# ADD GROUP MEMBER
# =========================

@app.route("/group/<int:group_id>/add-member", methods=["POST"])
def add_member(group_id):

    if not current_user():
        return redirect(url_for("index"))

    email = request.form["email"].strip().lower()

    conn = get_db()

    user = conn.execute(
        "SELECT id FROM users WHERE email=?",
        (email,)
    ).fetchone()

    if user:

        try:

            conn.execute(
                """
                INSERT INTO group_members(
                    group_id,
                    user_id
                )
                VALUES(?,?)
                """,
                (
                    group_id,
                    user["id"]
                )
            )

            conn.commit()

        except sqlite3.IntegrityError:
            pass

    conn.close()

    return redirect(url_for("dashboard"))


# =========================
# ADD TASK
# =========================

@app.route("/task/add", methods=["POST"])
def add_task():

    if not current_user():
        return redirect(url_for("index"))

    conn = get_db()

    conn.execute(
        """
        INSERT INTO tasks(
            group_id,
            title,
            description,
            assigned_to,
            due_date
        )
        VALUES(?,?,?,?,?)
        """,
        (
            request.form["group_id"],
            request.form["title"],
            request.form.get("description", ""),
            request.form.get("assigned_to") or None,
            request.form.get("due_date", "")
        )
    )

    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))


# =========================
# UPDATE TASK
# =========================

@app.route("/task/<int:task_id>/update", methods=["POST"])
def update_task(task_id):

    if not current_user():
        return redirect(url_for("index"))

    status = request.form.get(
        "status",
        "Pending"
    )

    evidence = request.form.get(
        "evidence",
        ""
    )

    note = request.form.get(
        "note",
        ""
    )

    minutes = int(
        request.form.get(
            "minutes",
            "0"
        ) or 0
    )

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    conn = get_db()

    conn.execute(
        """
        UPDATE tasks
        SET
            status=?,
            evidence=?,
            updated_at=?
        WHERE id=?
        """,
        (
            status,
            evidence,
            now,
            task_id
        )
    )

    conn.execute(
        """
        INSERT INTO activity(
            task_id,
            user_id,
            note,
            minutes,
            created_at
        )
        VALUES(?,?,?,?,?)
        """,
        (
            task_id,
            session["user_id"],
            note,
            minutes,
            now
        )
    )

    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))


# =========================
# REMINDERS API
# =========================

@app.route("/api/reminders")
def reminders():

    user = current_user()

    if not user:
        return jsonify([])

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            title,
            day,
            start_time,
            end_time,
            subject,
            room
        FROM schedules
        WHERE user_id=?
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# =========================
# START
# =========================

init_db()

if __name__ == "__main__":
    app.run(debug=True)
