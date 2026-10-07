from flask import Flask, render_template, request, jsonify, session
import firebase_admin
from firebase_admin import credentials, db
import os
from dotenv import load_dotenv
import uuid

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": os.getenv("FIREBASE_PROJECT_ID"),
        "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
        "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n"),
        "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
        "client_id": os.getenv("FIREBASE_CLIENT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
    })
    firebase_admin.initialize_app(cred, {
        "databaseURL": os.getenv("FIREBASE_DATABASE_URL")
    })

ref = db.reference()

# Helper: Generate group code
def gen_group_code():
    return f"JGE-{uuid.uuid4().hex[:4].upper()}"

# Serve main page
@app.route("/")
def index():
    return render_template("index.html")

# --- Auth Endpoints ---
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json
    users_ref = ref.child("users")
    
    snapshot = users_ref.order_by_child("email").equal_to(data["email"]).get()
    if snapshot:
        return jsonify({"error": "Email already registered"}), 400
    
    user_id = str(uuid.uuid4())
    new_user = {
        "id": user_id,
        "name": data["name"],
        "email": data["email"],
        "password": data["password"],
        "schedule": [],
        "deadlines": [],
        "joinedGroupCodes": [],
        "reviewers": []
    }
    
    users_ref.child(user_id).set(new_user)
    session["user_id"] = user_id
    return jsonify({"user": new_user})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    users_ref = ref.child("users")
    snapshot = users_ref.order_by_child("email").equal_to(data["email"]).get()
    
    if not snapshot:
        return jsonify({"error": "User not found"}), 404
    
    for uid, user in snapshot.items():
        if user["password"] == data["password"]:
            session["user_id"] = uid
            return jsonify({"user": user})
    
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/me", methods=["GET"])
def get_me():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    user = ref.child("users").child(session["user_id"]).get()
    return jsonify(dict(user)) if user else jsonify({"error": "Not found"}), 404

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

# --- Schedule ---
@app.route("/api/schedule", methods=["GET", "POST", "DELETE"])
def schedule():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    uref = ref.child("users").child(session["user_id"])
    
    if request.method == "GET":
        sched = uref.child("schedule").get() or []
        return jsonify(list(sched) if isinstance(sched, list) else [])
    
    if request.method == "POST":
        data = request.json
        sched = uref.child("schedule").get() or []
        sched.append(data)
        uref.child("schedule").set(sched)
        return jsonify(data)
    
    if request.method == "DELETE":
        idx = request.json["index"]
        sched = uref.child("schedule").get() or []
        if 0 <= idx < len(sched):
            sched.pop(idx)
            uref.child("schedule").set(sched)
        return jsonify({"ok": True})

# --- Deadlines ---
@app.route("/api/deadlines", methods=["GET", "POST", "DELETE"])
def deadlines():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    uref = ref.child("users").child(session["user_id"])
    
    if request.method == "GET":
        dls = uref.child("deadlines").get() or []
        return jsonify(list(dls) if isinstance(dls, list) else [])
    
    if request.method == "POST":
        data = request.json
        dls = uref.child("deadlines").get() or []
        dls.append(data)
        uref.child("deadlines").set(dls)
        return jsonify(data)
    
    if request.method == "DELETE":
        idx = request.json["index"]
        dls = uref.child("deadlines").get() or []
        if 0 <= idx < len(dls):
            dls.pop(idx)
            uref.child("deadlines").set(dls)
        return jsonify({"ok": True})

# --- Reviewers ---
@app.route("/api/reviewers", methods=["GET", "POST", "DELETE"])
def reviewers():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    uref = ref.child("users").child(session["user_id"])
    
    if request.method == "GET":
        rv = uref.child("reviewers").get() or []
        return jsonify(list(rv) if isinstance(rv, list) else [])
    
    if request.method == "POST":
        data = request.json
        rv = uref.child("reviewers").get() or []
        rv.append(data)
        uref.child("reviewers").set(rv)
        return jsonify(data)
    
    if request.method == "DELETE":
        idx = request.json["index"]
        rv = uref.child("reviewers").get() or []
        if 0 <= idx < len(rv):
            rv.pop(idx)
            uref.child("reviewers").set(rv)
        return jsonify({"ok": True})

# --- Groups ---
@app.route("/api/groups/create", methods=["POST"])
def create_group():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = ref.child("users").child(session["user_id"]).get()
    data = request.json
    code = gen_group_code()
    
    group = {
        "code": code,
        "name": data["name"],
        "members": [{"name": user["name"], "email": user["email"]}],
        "tasks": [],
        "logs": [f"Group created by {user['name']}"]
    }
    
    ref.child("groups").child(code).set(group)
    
    codes = user.get("joinedGroupCodes", [])
    codes.append(code)
    ref.child("users").child(session["user_id"]).child("joinedGroupCodes").set(codes)
    
    return jsonify({"code": code, "name": data["name"]})

@app.route("/api/groups/join", methods=["POST"])
def join_group():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = ref.child("users").child(session["user_id"]).get()
    code = request.json["code"].upper()
    
    gref = ref.child("groups").child(code)
    group = gref.get()
    if not group:
        return jsonify({"error": "Group not found"}), 404
    
    members = group.get("members", [])
    if not any(m["email"] == user["email"] for m in members):
        members.append({"name": user["name"], "email": user["email"]})
        logs = group.get("logs", [])
        logs.insert(0, f"{user['name']} joined the workspace.")
        gref.update({"members": members, "logs": logs})
    
    codes = user.get("joinedGroupCodes", [])
    if code not in codes:
        codes.append(code)
        ref.child("users").child(session["user_id"]).child("joinedGroupCodes").set(codes)
    
    return jsonify({"ok": True})

@app.route("/api/groups/joined", methods=["GET"])
def joined_groups():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = ref.child("users").child(session["user_id"]).get()
    codes = user.get("joinedGroupCodes", [])
    result = []
    for code in codes:
        g = ref.child("groups").child(code).get()
        if g:
            result.append({"code": code, "name": g.get("name", "Unnamed")})
    return jsonify(result)

@app.route("/api/groups/<code>", methods=["GET"])
def get_group(code):
    group = ref.child("groups").child(code).get()
    if not group:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(group))

@app.route("/api/groups/<code>/tasks", methods=["POST"])
def add_task(code):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = ref.child("users").child(session["user_id"]).get()
    data = request.json
    
    gref = ref.child("groups").child(code)
    group = gref.get()
    tasks = group.get("tasks", [])
    logs = group.get("logs", [])
    
    tasks.append({
        "task": data["task"],
        "assignee": data["assignee"],
        "status": data["status"]
    })
    logs.insert(0, f"{user['name']} added task: {data['task']}")
    
    gref.update({"tasks": tasks, "logs": logs})
    return jsonify({"ok": True})

@app.route("/api/groups/<code>/tasks/<int:idx>/status", methods=["PATCH"])
def update_task_status(code, idx):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = ref.child("users").child(session["user_id"]).get()
    new_status = request.json["status"]
    
    gref = ref.child("groups").child(code)
    group = gref.get()
    tasks = group.get("tasks", [])
    logs = group.get("logs", [])
    
    if 0 <= idx < len(tasks):
        tasks[idx]["status"] = new_status
        logs.insert(0, f"{user['name']} changed '{tasks[idx]['task']}' to {new_status}")
        gref.update({"tasks": tasks, "logs": logs})
    
    return jsonify({"ok": True})

@app.route("/api/groups/<code>/tasks/<int:idx>", methods=["DELETE"])
def delete_task(code, idx):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = ref.child("users").child(session["user_id"]).get()
    
    gref = ref.child("groups").child(code)
    group = gref.get()
    tasks = group.get("tasks", [])
    logs = group.get("logs", [])
    
    if 0 <= idx < len(tasks):
        removed = tasks.pop(idx)
        logs.insert(0, f"{user['name']} deleted task: {removed['task']}")
        gref.update({"tasks": tasks, "logs": logs})
    
    return jsonify({"ok": True})

@app.route("/api/groups/<code>/leave", methods=["POST"])
def leave_group(code):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_ref = ref.child("users").child(session["user_id"])
    user = user_ref.get()
    codes = user.get("joinedGroupCodes", [])
    if code in codes:
        codes.remove(code)
        user_ref.child("joinedGroupCodes").set(codes)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
