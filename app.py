import os, sqlite3, secrets
from datetime import datetime
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
DATABASE_URL = os.environ.get('DATABASE_URL', '')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

SCHEMA = [
'''CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, full_name TEXT NOT NULL, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
'''CREATE TABLE IF NOT EXISTS schedules (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL, schedule_date TEXT NOT NULL, schedule_time TEXT NOT NULL, description TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
'''CREATE TABLE IF NOT EXISTS groups (id SERIAL PRIMARY KEY, name TEXT NOT NULL, owner_id INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
'''CREATE TABLE IF NOT EXISTS group_members (group_id INTEGER NOT NULL, user_id INTEGER NOT NULL, UNIQUE(group_id,user_id))''',
'''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, group_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT DEFAULT '', assigned_to INTEGER, status TEXT DEFAULT 'Pending', progress INTEGER DEFAULT 0, proof TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
'''CREATE TABLE IF NOT EXISTS activity (id SERIAL PRIMARY KEY, group_id INTEGER NOT NULL, user_id INTEGER NOT NULL, message TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''
]

# SQLite-compatible schema
SQLITE_SCHEMA = [s.replace(' SERIAL PRIMARY KEY',' INTEGER PRIMARY KEY AUTOINCREMENT').replace(' TIMESTAMP DEFAULT CURRENT_TIMESTAMP',' TEXT DEFAULT CURRENT_TIMESTAMP') for s in SCHEMA]

def db():
    if DATABASE_URL and psycopg2:
        return psycopg2.connect(DATABASE_URL, sslmode='require', cursor_factory=RealDictCursor)
    c=sqlite3.connect('studysched.db')
    c.row_factory=sqlite3.Row
    return c

def execute(sql,args=(),fetch=False,one=False):
    pg=bool(DATABASE_URL and psycopg2)
    conn=db(); cur=conn.cursor()
    try:
        if pg: sql=sql.replace('?', '%s')
        cur.execute(sql,args)
        if fetch:
            rows=cur.fetchall() if not one else cur.fetchone()
            return rows
        conn.commit()
        return cur.lastrowid if not pg else None
    finally:
        cur.close(); conn.close()

def init_db():
    conn=db(); cur=conn.cursor()
    try:
        for sql in (SCHEMA if DATABASE_URL and psycopg2 else SQLITE_SCHEMA):
            cur.execute(sql)
        conn.commit()
        # Create default admin account only in users table for easy admin access if needed.
    finally:
        cur.close(); conn.close()

init_db()

def current_user():
    uid=session.get('user_id')
    if not uid:return None
    return execute('SELECT * FROM users WHERE id=?',(uid,),True,True)

def login_required(f):
    @wraps(f)
    def w(*a,**k):
        if not current_user(): return redirect(url_for('login'))
        return f(*a,**k)
    return w

def layout(title,body):
    return render_template_string('''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} - StudySched</title><style>
body{margin:0;background:#0b0f19;color:#f5f7fb;font-family:Arial,sans-serif}.nav{background:#111827;padding:16px 5%;display:flex;gap:18px;align-items:center;flex-wrap:wrap}.nav a{color:#fff;text-decoration:none}.brand{font-size:21px;font-weight:bold;margin-right:auto}.wrap{max-width:1050px;margin:30px auto;padding:0 18px}.card{background:#151c2b;border:1px solid #273247;border-radius:14px;padding:20px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:15px}input,textarea,select{width:100%;box-sizing:border-box;padding:11px;margin:7px 0;background:#0d1422;border:1px solid #334155;color:white;border-radius:8px}button,.btn{background:#2563eb;color:white;border:0;border-radius:8px;padding:10px 15px;text-decoration:none;display:inline-block;cursor:pointer}.danger{background:#dc2626}.muted{color:#94a3b8}.bar{height:9px;background:#273247;border-radius:10px;overflow:hidden}.fill{height:100%;background:#22c55e}.small{font-size:13px}.err{color:#fca5a5}.ok{color:#86efac}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #293449;text-align:left}</style></head><body><div class="nav"><a class="brand" href="{{url_for('dashboard')}}">StudySched</a><a href="{{url_for('dashboard')}}">Dashboard</a>{% if session.get('user_id') %}<a href="{{url_for('schedule')}}">My Schedule</a><a href="{{url_for('groups')}}">Groups</a><a href="{{url_for('logout')}}">Logout</a>{% else %}<a href="{{url_for('login')}}">Login</a><a href="{{url_for('register')}}">Register</a>{% endif %}</div><div class="wrap">{{body|safe}}</div></body></html>''',title=title,body=body)

@app.route('/')
def home():
    return redirect(url_for('dashboard') if current_user() else url_for('login'))

@app.route('/register',methods=['GET','POST'])
def register():
    msg=''
    if request.method=='POST':
        name=request.form.get('full_name','').strip(); username=request.form.get('username','').strip(); password=request.form.get('password','')
        if not name or not username or not password: msg='Please complete all fields.'
        elif execute('SELECT id FROM users WHERE username=?',(username,),True,True): msg='Username already exists.'
        else:
            execute('INSERT INTO users (full_name,username,password_hash) VALUES (?,?,?)',(name,username,generate_password_hash(password)))
            return redirect(url_for('login'))
    return layout('Register',f'''<div class="card"><h1>Create Account</h1><p class="err">{msg}</p><form method="post"><input name="full_name" placeholder="Full name" required><input name="username" placeholder="Username" required><input type="password" name="password" placeholder="Password" required><button>Register</button></form><p>Already have an account? <a href="/login">Login</a></p></div>''')

@app.route('/login',methods=['GET','POST'])
def login():
    msg=''
    if request.method=='POST':
        u=execute('SELECT * FROM users WHERE username=?',(request.form.get('username','').strip(),),True,True)
        if u and check_password_hash(u['password_hash'],request.form.get('password','')):
            session['user_id']=u['id']; return redirect(url_for('dashboard'))
        msg='Invalid username or password.'
    return layout('Login',f'''<div class="card"><h1>StudySched Login</h1><p class="err">{msg}</p><form method="post"><input name="username" placeholder="Username" required><input type="password" name="password" placeholder="Password" required><button>Login</button></form><p>No account? <a href="/register">Register</a></p><p class="small muted">Admin panel: use /admin with ADMIN_USERNAME and ADMIN_PASSWORD.</p></div>''')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    u=current_user(); schedules=execute('SELECT * FROM schedules WHERE user_id=? ORDER BY schedule_date,schedule_time',(u['id'],),True)
    gs=execute('SELECT g.* FROM groups g JOIN group_members m ON g.id=m.group_id WHERE m.user_id=? ORDER BY g.id DESC',(u['id'],),True)
    return layout('Dashboard',f'''<h1>Welcome, {u['full_name']}</h1><div class="grid"><div class="card"><h2>{len(schedules)}</h2><p class="muted">Scheduled activities</p><a class="btn" href="/schedule">Manage Schedule</a></div><div class="card"><h2>{len(gs)}</h2><p class="muted">Groups</p><a class="btn" href="/groups">Open Groups</a></div></div><div class="card"><h2>Upcoming</h2>{''.join(f"<p><b>{s['title']}</b> — {s['schedule_date']} {s['schedule_time']}</p>" for s in schedules[:5]) or '<p class="muted">No schedules yet.</p>'}</div>''')

@app.route('/schedule',methods=['GET','POST'])
@login_required
def schedule():
    u=current_user()
    if request.method=='POST':
        execute('INSERT INTO schedules (user_id,title,schedule_date,schedule_time,description) VALUES (?,?,?,?,?)',(u['id'],request.form['title'],request.form['schedule_date'],request.form['schedule_time'],request.form.get('description','')))
        return redirect(url_for('schedule'))
    rows=execute('SELECT * FROM schedules WHERE user_id=? ORDER BY schedule_date,schedule_time',(u['id'],),True)
    html='''<div class="card"><h1>My Schedule</h1><form method="post"><input name="title" placeholder="Activity title" required><input type="date" name="schedule_date" required><input type="time" name="schedule_time" required><textarea name="description" placeholder="Description"></textarea><button>Add Schedule</button></form></div><div class="card"><h2>Activities</h2>'''
    for s in rows: html+=f'''<div class="card"><b>{s['title']}</b><p>{s['schedule_date']} at {s['schedule_time']}</p><p class="muted">{s['description'] or ''}</p><form method="post" action="/schedule/delete/{s['id']}"><button class="danger">Delete</button></form></div>'''
    html+='</div>'; return layout('My Schedule',html)

@app.route('/schedule/delete/<int:sid>',methods=['POST'])
@login_required
def delete_schedule(sid):
    execute('DELETE FROM schedules WHERE id=? AND user_id=?',(sid,current_user()['id'])); return redirect(url_for('schedule'))

@app.route('/groups',methods=['GET','POST'])
@login_required
def groups():
    u=current_user()
    if request.method=='POST':
        name=request.form.get('name','').strip()
        if name:
            gid=execute('INSERT INTO groups (name,owner_id) VALUES (?,?)',(name,u['id']))
            # SQLite lastrowid; PostgreSQL fallback
            if not gid:
                g=execute('SELECT id FROM groups WHERE owner_id=? ORDER BY id DESC',(u['id'],),True,True); gid=g['id']
            execute('INSERT INTO group_members (group_id,user_id) VALUES (?,?)',(gid,u['id']))
        return redirect(url_for('groups'))
    gs=execute('SELECT g.*, (SELECT COUNT(*) FROM group_members m WHERE m.group_id=g.id) members FROM groups g JOIN group_members gm ON g.id=gm.group_id WHERE gm.user_id=?',(u['id'],),True)
    html='<div class="card"><h1>Groups</h1><form method="post"><input name="name" placeholder="Group name" required><button>Create Group</button></form></div><div class="grid">'
    for g in gs: html+=f'<div class="card"><h2>{g["name"]}</h2><p>{g["members"]} member(s)</p><a class="btn" href="/group/{g["id"]}">Open Group</a></div>'
    html+='</div>'; return layout('Groups',html)

@app.route('/group/<int:gid>',methods=['GET','POST'])
@login_required
def group_page(gid):
    u=current_user(); member=execute('SELECT * FROM group_members WHERE group_id=? AND user_id=?',(gid,u['id']),True,True)
    if not member:return 'Access denied',403
    g=execute('SELECT * FROM groups WHERE id=?',(gid,),True,True)
    if request.method=='POST':
        title=request.form.get('title','').strip(); desc=request.form.get('description','').strip(); assigned=request.form.get('assigned_to') or None
        execute('INSERT INTO tasks (group_id,title,description,assigned_to) VALUES (?,?,?,?)',(gid,title,desc,assigned))
        execute('INSERT INTO activity (group_id,user_id,message) VALUES (?,?,?)',(gid,u['id'],f'Created task: {title}'))
        return redirect(url_for('group_page',gid=gid))
    members=execute('SELECT u.* FROM users u JOIN group_members m ON u.id=m.user_id WHERE m.group_id=?',(gid,),True)
    tasks=execute('SELECT t.*,u.full_name FROM tasks t LEFT JOIN users u ON t.assigned_to=u.id WHERE t.group_id=? ORDER BY t.id DESC',(gid,),True)
    total=len(tasks); done=sum(1 for t in tasks if t['status']=='Completed'); percent=round(done/total*100) if total else 0
    opts=''.join(f'<option value="{m["id"]}">{m["full_name"]}</option>' for m in members)
    html=f'''<div class="card"><h1>{g['name']}</h1><p>Group progress: {percent}%</p><div class="bar"><div class="fill" style="width:{percent}%"></div></div><h2>Add Task</h2><form method="post"><input name="title" placeholder="Task title" required><textarea name="description" placeholder="Description"></textarea><select name="assigned_to"><option value="">Unassigned</option>{opts}</select><button>Add Task</button></form></div>'''
    for t in tasks:
        html+=f'''<div class="card"><h3>{t['title']}</h3><p>{t['description'] or ''}</p><p>Assigned to: {t['full_name'] or 'Unassigned'}</p><p>Status: <b>{t['status']}</b> — {t['progress']}%</p><div class="bar"><div class="fill" style="width:{t['progress']}%"></div></div><form method="post" action="/task/{t['id']}"><select name="status"><option {'selected' if t['status']=='Pending' else ''}>Pending</option><option {'selected' if t['status']=='In Progress' else ''}>In Progress</option><option {'selected' if t['status']=='Completed' else ''}>Completed</option></select><input type="number" name="progress" min="0" max="100" value="{t['progress']}"><textarea name="proof" placeholder="What did you work on? / proof description"></textarea><button>Update Progress</button></form></div>'''
    return layout(g['name'],html)

@app.route('/task/<int:task_id>',methods=['POST'])
@login_required
def update_task(task_id):
    u=current_user(); t=execute('SELECT t.* FROM tasks t JOIN group_members m ON t.group_id=m.group_id WHERE t.id=? AND m.user_id=?',(task_id,u['id']),True,True)
    if not t:return 'Task not found',404
    status=request.form.get('status','Pending'); progress=max(0,min(100,int(request.form.get('progress',0) or 0))); proof=request.form.get('proof','').strip()
    if progress==100:status='Completed'
    execute('UPDATE tasks SET status=?,progress=?,proof=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,progress,proof,task_id))
    execute('INSERT INTO activity (group_id,user_id,message) VALUES (?,?,?)',(t['group_id'],u['id'],f'Updated task: {t["title"]} ({progress}%)'))
    return redirect(url_for('group_page',gid=t['group_id']))

@app.route('/api/upcoming')
@login_required
def upcoming():
    u=current_user(); rows=execute('SELECT id,title,schedule_date,schedule_time FROM schedules WHERE user_id=? ORDER BY schedule_date,schedule_time LIMIT 20',(u['id'],),True)
    return jsonify([dict(x) for x in rows])

@app.route('/admin',methods=['GET','POST'])
def admin():
    if not (session.get('admin') or (request.form.get('username')==ADMIN_USERNAME and request.form.get('password')==ADMIN_PASSWORD)):
        if request.method=='POST': return layout('Admin Login','<div class="card"><p class="err">Invalid admin credentials.</p><a href="/admin">Try again</a></div>')
        return layout('Admin Login','<div class="card"><h1>Admin Login</h1><form method="post"><input name="username" placeholder="Admin username"><input type="password" name="password" placeholder="Admin password"><button>Login</button></form></div>')
    session['admin']=True
    users=execute('SELECT id,full_name,username,created_at FROM users ORDER BY id DESC',fetch=True)
    groups=execute('SELECT g.id,g.name,u.full_name owner FROM groups g JOIN users u ON g.owner_id=u.id ORDER BY g.id DESC',fetch=True)
    tasks=execute('SELECT t.id,t.title,t.status,t.progress,g.name group_name FROM tasks t JOIN groups g ON t.group_id=g.id ORDER BY t.id DESC',fetch=True)
    html='<h1>Admin Panel</h1><div class="card"><h2>Users</h2><table><tr><th>ID</th><th>Name</th><th>Username</th></tr>'+''.join(f'<tr><td>{x["id"]}</td><td>{x["full_name"]}</td><td>{x["username"]}</td></tr>' for x in users)+'</table></div><div class="card"><h2>Groups</h2>'+''.join(f'<p><b>{x["name"]}</b> — owner: {x["owner"]}</p>' for x in groups)+'</div><div class="card"><h2>Tasks</h2>'+''.join(f'<p>{x["group_name"]}: <b>{x["title"]}</b> — {x["status"]} ({x["progress"]}%)</p>' for x in tasks)+'</div>'
    return layout('Admin',html)

@app.route('/health')
def health(): return jsonify(status='ok')

@app.route('/sw.js')
def sw():
    return app.response_class("self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));",mimetype='application/javascript')

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
