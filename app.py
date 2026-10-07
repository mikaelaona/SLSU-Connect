from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import secrets
import string
import os

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key"
)

DATABASE = "study_sched.db"


# =========================
# DATABASE
# =========================

def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    db = get_db()

    db.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            subject TEXT,
            date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_date TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            FOREIGN KEY(student_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            owner_id INTEGER NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            UNIQUE(group_id, student_id),
            FOREIGN KEY(group_id) REFERENCES groups(id),
            FOREIGN KEY(student_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS group_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_date TEXT,
            completed INTEGER DEFAULT 0,
            FOREIGN KEY(group_id) REFERENCES groups(id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id)
        );
    """)

    db.commit()
    db.close()


# =========================
# LOGIN CHECK
# =========================

def login_required():
    return "student_id" in session


# =========================
# HOME
# =========================

@app.route("/")
def home():
    if login_required():
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# =========================
# REGISTER
# =========================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or not password:
            flash("Please complete all fields.")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.")
            return redirect(url_for("register"))

        db = get_db()

        existing = db.execute(
            "SELECT id FROM students WHERE email = ?",
            (email,)
        ).fetchone()

        if existing:
            db.close()
            flash("An account with that email already exists.")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        cursor = db.execute(
            """
            INSERT INTO students
            (name, email, password)
            VALUES (?, ?, ?)
            """,
            (name, email, hashed_password)
        )

        db.commit()

        student_id = cursor.lastrowid

        db.close()

        session["student_id"] = student_id
        session["student_name"] = name

        return redirect(url_for("dashboard"))

    return render_template("register.html")


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        db = get_db()

        student = db.execute(
            "SELECT * FROM students WHERE email = ?",
            (email,)
        ).fetchone()

        db.close()

        if not student:
            flash("Invalid email or password.")
            return redirect(url_for("login"))

        if not check_password_hash(student["password"], password):
            flash("Invalid email or password.")
            return redirect(url_for("login"))

        session["student_id"] = student["id"]
        session["student_name"] = student["name"]

        return redirect(url_for("dashboard"))

    return render_template("login.html")


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================
# DASHBOARD
# =========================

@app.route("/dashboard")
def dashboard():

    if not login_required():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    db = get_db()

    schedules = db.execute(
        """
        SELECT *
        FROM schedules
        WHERE student_id = ?
        ORDER BY date, start_time
        LIMIT 5
        """,
        (student_id,)
    ).fetchall()

    deadlines = db.execute(
        """
        SELECT *
        FROM deadlines
        WHERE student_id = ?
        AND completed = 0
        ORDER BY due_date
        LIMIT 5
        """,
        (student_id,)
    ).fetchall()

    groups = db.execute(
        """
        SELECT groups.*
        FROM groups
        JOIN group_members
        ON groups.id = group_members.group_id
        WHERE group_members.student_id = ?
        """,
        (student_id,)
    ).fetchall()

    db.close()

    return render_template(
        "dashboard.html",
        schedules=schedules,
        deadlines=deadlines,
        groups=groups
    )


# =========================
# SCHEDULE
# =========================

@app.route("/schedule", methods=["GET", "POST"])
def schedule():

    if not login_required():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    db = get_db()

    if request.method == "POST":

        title = request.form["title"]
        subject = request.form["subject"]
        date = request.form["date"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]

        db.execute(
            """
            INSERT INTO schedules
            (student_id, title, subject, date, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                title,
                subject,
                date,
                start_time,
                end_time
            )
        )

        db.commit()

        db.close()

        return redirect(url_for("schedule"))

    schedules = db.execute(
        """
        SELECT *
        FROM schedules
        WHERE student_id = ?
        ORDER BY date, start_time
        """,
        (student_id,)
    ).fetchall()

    db.close()

    return render_template(
        "schedule.html",
        schedules=schedules
    )


@app.route("/schedule/delete/<int:schedule_id>")
def delete_schedule(schedule_id):

    if not login_required():
        return redirect(url_for("login"))

    db = get_db()

    db.execute(
        """
        DELETE FROM schedules
        WHERE id = ?
        AND student_id = ?
        """,
        (
            schedule_id,
            session["student_id"]
        )
    )

    db.commit()
    db.close()

    return redirect(url_for("schedule"))


# =========================
# DEADLINES
# =========================

@app.route("/deadlines", methods=["GET", "POST"])
def deadlines():

    if not login_required():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    db = get_db()

    if request.method == "POST":

        title = request.form["title"]
        description = request.form["description"]
        due_date = request.form["due_date"]

        db.execute(
            """
            INSERT INTO deadlines
            (student_id, title, description, due_date)
            VALUES (?, ?, ?, ?)
            """,
            (
                student_id,
                title,
                description,
                due_date
            )
        )

        db.commit()

        db.close()

        return redirect(url_for("deadlines"))

    deadlines_list = db.execute(
        """
        SELECT *
        FROM deadlines
        WHERE student_id = ?
        ORDER BY due_date
        """,
        (student_id,)
    ).fetchall()

    db.close()

    return render_template(
        "deadlines.html",
        deadlines=deadlines_list
    )


@app.route("/deadlines/complete/<int:deadline_id>")
def complete_deadline(deadline_id):

    if not login_required():
        return redirect(url_for("login"))

    db = get_db()

    db.execute(
        """
        UPDATE deadlines
        SET completed = CASE
            WHEN completed = 0 THEN 1
            ELSE 0
        END
        WHERE id = ?
        AND student_id = ?
        """,
        (
            deadline_id,
            session["student_id"]
        )
    )

    db.commit()
    db.close()

    return redirect(url_for("deadlines"))


# =========================
# GROUP CODE
# =========================

def generate_group_code():

    characters = string.ascii_uppercase + string.digits

    return "".join(
        secrets.choice(characters)
        for _ in range(8)
    )


# =========================
# GROUPS
# =========================

@app.route("/groups", methods=["GET", "POST"])
def groups():

    if not login_required():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    db = get_db()

    groups_list = db.execute(
        """
        SELECT groups.*
        FROM groups
        JOIN group_members
        ON groups.id = group_members.group_id
        WHERE group_members.student_id = ?
        """,
        (student_id,)
    ).fetchall()

    db.close()

    return render_template(
        "groups.html",
        groups=groups_list
    )


# =========================
# CREATE GROUP
# =========================

@app.route("/groups/create", methods=["POST"])
def create_group():

    if not login_required():
        return redirect(url_for("login"))

    name = request.form["name"]

    db = get_db()

    while True:

        code = generate_group_code()

        existing = db.execute(
            "SELECT id FROM groups WHERE code = ?",
            (code,)
        ).fetchone()

        if not existing:
            break

    cursor = db.execute(
        """
        INSERT INTO groups
        (name, code, owner_id)
        VALUES (?, ?, ?)
        """,
        (
            name,
            code,
            session["student_id"]
        )
    )

    group_id = cursor.lastrowid

    db.execute(
        """
        INSERT INTO group_members
        (group_id, student_id)
        VALUES (?, ?)
        """,
        (
            group_id,
            session["student_id"]
        )
    )

    db.commit()
    db.close()

    flash(f"Group created! Your group code is {code}")

    return redirect(url_for("groups"))


# =========================
# JOIN GROUP
# =========================

@app.route("/groups/join", methods=["POST"])
def join_group():

    if not login_required():
        return redirect(url_for("login"))

    code = request.form["code"].strip().upper()

    db = get_db()

    group = db.execute(
        """
        SELECT *
        FROM groups
        WHERE code = ?
        """,
        (code,)
    ).fetchone()

    if not group:

        db.close()

        flash("Group code not found.")

        return redirect(url_for("groups"))

    try:

        db.execute(
            """
            INSERT INTO group_members
            (group_id, student_id)
            VALUES (?, ?)
            """,
            (
                group["id"],
                session["student_id"]
            )
        )

        db.commit()

    except sqlite3.IntegrityError:

        flash("You are already a member of this group.")

    db.close()

    return redirect(
        url_for(
            "group_page",
            group_id=group["id"]
        )
    )


# =========================
# GROUP PAGE
# =========================

@app.route("/groups/<int:group_id>")
def group_page(group_id):

    if not login_required():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    db = get_db()

    membership = db.execute(
        """
        SELECT *
        FROM group_members
        WHERE group_id = ?
        AND student_id = ?
        """,
        (
            group_id,
            student_id
        )
    ).fetchone()

    if not membership:

        db.close()

        flash("You are not a member of this group.")

        return redirect(url_for("groups"))

    group = db.execute(
        """
        SELECT *
        FROM groups
        WHERE id = ?
        """,
        (group_id,)
    ).fetchone()

    tasks = db.execute(
        """
        SELECT *
        FROM group_tasks
        WHERE group_id = ?
        ORDER BY due_date
        """,
        (group_id,)
    ).fetchall()

    members = db.execute(
        """
        SELECT students.*
        FROM students
        JOIN group_members
        ON students.id = group_members.student_id
        WHERE group_members.group_id = ?
        """,
        (group_id,)
    ).fetchall()

    db.close()

    return render_template(
        "group.html",
        group=group,
        tasks=tasks,
        members=members
    )


# =========================
# GROUP TASK
# =========================

@app.route(
    "/groups/<int:group_id>/tasks",
    methods=["POST"]
)
def add_group_task(group_id):

    if not login_required():
        return redirect(url_for("login"))

    db = get_db()

    membership = db.execute(
        """
        SELECT *
        FROM group_members
        WHERE group_id = ?
        AND student_id = ?
        """,
        (
            group_id,
            session["student_id"]
        )
    ).fetchone()

    if not membership:

        db.close()

        return "You are not a group member.", 403

    title = request.form["title"]
    description = request.form["description"]
    due_date = request.form["due_date"]

    db.execute(
        """
        INSERT INTO group_tasks
        (group_id, title, description, due_date)
        VALUES (?, ?, ?, ?)
        """,
        (
            group_id,
            title,
            description,
            due_date
        )
    )

    db.commit()
    db.close()

    return redirect(
        url_for(
            "group_page",
            group_id=group_id
        )
    )


# =========================
# COMPLETE GROUP TASK
# =========================

@app.route(
    "/groups/<int:group_id>/tasks/<int:task_id>/complete"
)
def complete_group_task(group_id, task_id):

    if not login_required():
        return redirect(url_for("login"))

    db = get_db()

    db.execute(
        """
        UPDATE group_tasks
        SET completed = CASE
            WHEN completed = 0 THEN 1
            ELSE 0
        END
        WHERE id = ?
        AND group_id = ?
        """,
        (
            task_id,
            group_id
        )
    )

    db.commit()
    db.close()

    return redirect(
        url_for(
            "group_page",
            group_id=group_id
        )
    )


# =========================
# REVIEW PAD
# =========================

@app.route("/review-pad", methods=["GET", "POST"])
def review_pad():

    if not login_required():
        return redirect(url_for("login"))

    student_id = session["student_id"]

    db = get_db()

    if request.method == "POST":

        title = request.form["title"]
        content = request.form["content"]

        db.execute(
            """
            INSERT INTO reviews
            (student_id, title, content)
            VALUES (?, ?, ?)
            """,
            (
                student_id,
                title,
                content
            )
        )

        db.commit()

    reviews = db.execute(
        """
        SELECT *
        FROM reviews
        WHERE student_id = ?
        ORDER BY created_at DESC
        """,
        (student_id,)
    ).fetchall()

    db.close()

    return render_template(
        "review_pad.html",
        reviews=reviews
    )


@app.route("/review-pad/delete/<int:review_id>")
def delete_review(review_id):

    if not login_required():
        return redirect(url_for("login"))

    db = get_db()

    db.execute(
        """
        DELETE FROM reviews
        WHERE id = ?
        AND student_id = ?
        """,
        (
            review_id,
            session["student_id"]
        )
    )

    db.commit()
    db.close()

    return redirect(url_for("review_pad"))


# =========================
# START APP
# =========================

if __name__ == "__main__":

    init_db()

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
