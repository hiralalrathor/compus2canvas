from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse, unquote
from http.cookies import SimpleCookie
from pathlib import Path
import hashlib
import hmac
import html
import json
import mimetypes
import os
import secrets
import sqlite3
import time


BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "college_events.db"
STATIC_DIR = BASE_DIR / "static"
SECRET = os.environ.get("CEMS_SECRET", "change-this-secret-for-production")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def esc(value):
    return html.escape(str(value or ""))


def form_value(data, name, default=""):
    return data.get(name, [default])[0].strip()


def event_dates(row):
    start = row["event_date"]
    end = row["end_date"] if "end_date" in row.keys() and row["end_date"] else start
    if end and end != start:
        return f"{start} to {end}"
    return start


def event_time_range(row):
    return f"{row['start_time']}-{row['end_time']}"


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${digest}"


def verify_password(password, stored):
    salt, digest = stored.split("$", 1)
    check = hashlib.sha256((salt + password).encode()).hexdigest()
    return hmac.compare_digest(check, digest)


def make_session(user_id):
    value = f"{user_id}:{int(time.time())}"
    sig = hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}:{sig}"


def read_session(cookie_header):
    if not cookie_header:
        return None
    cookie = SimpleCookie(cookie_header)
    morsel = cookie.get("cems_session")
    if not morsel:
        return None
    parts = morsel.value.split(":")
    if len(parts) != 3:
        return None
    value = f"{parts[0]}:{parts[1]}"
    expected = hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, parts[2]):
        return None
    return int(parts[0])


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('student','organizer','admin')),
                department TEXT,
                phone TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                image_url TEXT,
                category TEXT NOT NULL,
                target_department TEXT NOT NULL DEFAULT 'All',
                venue TEXT NOT NULL,
                event_date TEXT NOT NULL,
                end_date TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                approval_required INTEGER NOT NULL DEFAULT 0,
                admin_remarks TEXT,
                organizer_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (organizer_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Confirmed',
                registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, event_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registration_id INTEGER NOT NULL UNIQUE,
                ticket_code TEXT NOT NULL UNIQUE,
                issued_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'Valid',
                FOREIGN KEY (registration_id) REFERENCES registrations(id)
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                session_title TEXT NOT NULL,
                speaker TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                venue TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS sponsors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact_email TEXT,
                phone TEXT,
                sponsorship_level TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS event_sponsors (
                event_id INTEGER NOT NULL,
                sponsor_id INTEGER NOT NULL,
                PRIMARY KEY(event_id, sponsor_id),
                FOREIGN KEY (event_id) REFERENCES events(id),
                FOREIGN KEY (sponsor_id) REFERENCES sponsors(id)
            );
            """
        )
        migrate_db(db)
        count = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        if count == 0:
            seed_data(db)
        ensure_default_hackathon(db)


def migrate_db(db):
    event_columns = {row["name"] for row in db.execute("PRAGMA table_info(events)").fetchall()}
    if "end_date" not in event_columns:
        db.execute("ALTER TABLE events ADD COLUMN end_date TEXT")
        db.execute("UPDATE events SET end_date=event_date WHERE end_date IS NULL OR end_date=''")
    if "target_department" not in event_columns:
        db.execute("ALTER TABLE events ADD COLUMN target_department TEXT NOT NULL DEFAULT 'All'")


def seed_data(db):
    users = [
        ("Admin User", "admin@college.edu", "admin123", "admin", "Administration", "9999999999"),
        ("Event Organizer", "organizer@college.edu", "organizer123", "organizer", "Computer Science", "8888888888"),
        ("Student User", "student@college.edu", "student123", "student", "Information Technology", "7777777777"),
    ]
    for name, email, password, role, dept, phone in users:
        db.execute(
            "INSERT INTO users(name,email,password_hash,role,department,phone) VALUES(?,?,?,?,?,?)",
            (name, email, hash_password(password), role, dept, phone),
        )
    events = [
        (
            "TechFest 2026",
            "A full-day makers festival with coding arenas, AI demos, hardware showcases, and lightning talks.",
            "https://images.unsplash.com/photo-1540575467063-178a50c2df87?auto=format&fit=crop&w=1400&q=80",
            "Technical",
            "All",
            "Main Auditorium",
            "2026-08-20",
            "2026-08-20",
            "09:00",
            "17:00",
            120,
            "Approved",
            0,
            2,
        ),
        (
            "Midnight Media Lab",
            "A creative sprint for posters, reels, campus radio, and rapid storytelling.",
            "https://images.unsplash.com/photo-1492684223066-81342ee5ff30?auto=format&fit=crop&w=1400&q=80",
            "Creative",
            "Information Technology",
            "Studio Block",
            "2026-09-04",
            "2026-09-04",
            "18:00",
            "22:00",
            80,
            "Approved",
            1,
            2,
        ),
    ]
    db.executemany(
        """
        INSERT INTO events(title,description,image_url,category,target_department,venue,event_date,end_date,start_time,end_time,capacity,status,approval_required,organizer_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        events,
    )
    db.execute(
        "INSERT INTO schedules(event_id,session_title,speaker,start_time,end_time,venue) VALUES(?,?,?,?,?,?)",
        (1, "Opening Ceremony", "Principal and Student Council", "09:00", "09:45", "Main Auditorium"),
    )
    db.execute(
        "INSERT INTO sponsors(name,contact_email,phone,sponsorship_level,amount) VALUES(?,?,?,?,?)",
        ("CodeLabs Pvt Ltd", "sponsor@codelabs.test", "9000000000", "Gold", 50000),
    )
    db.execute("INSERT INTO event_sponsors(event_id,sponsor_id) VALUES(?,?)", (1, 1))


def ensure_default_hackathon(db):
    exists = db.execute("SELECT id FROM events WHERE title='48 Hour Hackathon'").fetchone()
    if exists:
        return
    organizer = db.execute("SELECT id FROM users WHERE role='organizer' ORDER BY id LIMIT 1").fetchone()
    if not organizer:
        return
    db.execute(
        """
        INSERT INTO events(title,description,image_url,category,venue,event_date,end_date,start_time,end_time,capacity,status,approval_required,organizer_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "48 Hour Hackathon",
            "A two-day build sprint where teams prototype apps, pitch ideas, and ship working demos before the final bell.",
            "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=1400&q=80",
            "Hackathon",
            "Innovation Lab",
            "2026-10-10",
            "2026-10-12",
            "09:00",
            "09:00",
            150,
            "Approved",
            0,
            organizer["id"],
        ),
    )


def layout(title, body, user=None, message=""):
    nav = '<a href="/">Home</a><a href="/events">Events</a>'
    if user:
        nav += '<a href="/dashboard">Dashboard</a>'
        if user["role"] == "admin":
            nav += '<a href="/admin/events">Admin</a>'
        if user["role"] == "organizer":
            nav += '<a href="/organizer/events">Organizer</a>'
        nav += '<a href="/logout">Logout</a>'
    else:
        nav += '<a href="/login">Login</a><a href="/register">Register</a>'
    banner = f'<div class="flash">{esc(message)}</div>' if message else ""
    name = esc(user["name"]) if user else "Guest"
    profile = f'<a class="user-pill" href="/profile">{name}</a>' if user else f'<span class="user-pill">{name}</span>'
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(title)} | Campus Canvas</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <header class="site-header">
        <a class="brand" href="/">
            <span class="brand-mark">CC</span>
            <span><strong>Campus Canvas</strong><small>Events, passes, schedules</small></span>
        </a>
        <nav>{nav}</nav>
        {profile}
    </header>
    <main>{banner}{body}</main>
    {chatbot_widget(user)}
</body>
</html>"""


def chatbot_widget(user):
    if not user or user["role"] != "student":
        return ""
    return """
    <section class="chatbot" data-chatbot>
        <button class="chatbot-launch" type="button" aria-label="Open event assistant">CC</button>
        <div class="chatbot-panel" hidden>
            <div class="chatbot-head">
                <strong>Campus Care</strong>
                <button type="button" aria-label="Close event assistant">x</button>
            </div>
            <div class="chatbot-messages">
                <p class="bot">Hi. Choose an option and I will help you find the right event.</p>
            </div>
            <div class="chatbot-options">
                <button type="button" data-intent="suggest">Suggest event</button>
                <button type="button" data-intent="department">My department events</button>
                <button type="button" data-intent="tickets">My tickets</button>
            </div>
        </div>
    </section>
    <script src="/static/chatbot.js"></script>
    """


class App(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self.route_get()
        except Exception as exc:
            self.error_page(500, str(exc))

    def do_POST(self):
        try:
            self.route_post()
        except Exception as exc:
            self.error_page(500, str(exc))

    def current_user(self):
        user_id = read_session(self.headers.get("Cookie"))
        if not user_id:
            return None
        with get_db() as db:
            return db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def send_html(self, content, status=200, cookie=None):
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, payload, status=200):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def redirect(self, path, cookie=None):
        self.send_response(303)
        self.send_header("Location", path)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def read_form(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return parse_qs(raw)

    def require_user(self, roles=None):
        user = self.current_user()
        if not user:
            self.redirect("/login")
            return None
        if roles and user["role"] not in roles:
            self.error_page(403, "You do not have permission to open this page.")
            return None
        return user

    def route_get(self):
        path = urlparse(self.path).path
        if path.startswith("/static/"):
            return self.static_file(path)
        user = self.current_user()
        routes = {
            "/": lambda: self.home(user),
            "/events": lambda: self.events_page(user),
            "/login": lambda: self.login_page(user),
            "/register": lambda: self.register_page(user),
            "/dashboard": self.dashboard,
            "/profile": self.profile_page,
            "/organizer/events": self.organizer_events,
            "/organizer/participants": self.organizer_participants,
            "/admin/events": self.admin_events,
            "/admin/participants": self.admin_participants,
            "/admin/registrations": self.admin_registrations,
            "/admin/schedules": self.admin_schedules,
            "/admin/sponsors": self.admin_sponsors,
            "/chatbot": self.chatbot_reply,
        }
        if path == "/logout":
            return self.redirect("/", "cems_session=; Path=/; Max-Age=0; HttpOnly")
        if path.startswith("/events/"):
            return self.event_detail(path, user)
        if path.startswith("/ticket/"):
            return self.ticket_page(path)
        if path in routes:
            return routes[path]()
        return self.error_page(404, "Page not found.")

    def route_post(self):
        path = urlparse(self.path).path
        routes = {
            "/login": self.login_action,
            "/register": self.register_action,
            "/events/register": self.register_event,
            "/events/cancel": self.cancel_registration,
            "/organizer/events": self.create_event,
            "/admin/event-status": self.update_event_status,
            "/admin/registration-status": self.update_registration_status,
            "/admin/schedules": self.add_schedule,
            "/admin/sponsors": self.add_sponsor,
            "/admin/link-sponsor": self.link_sponsor,
        }
        if path in routes:
            return routes[path]()
        return self.error_page(404, "Action not found.")

    def static_file(self, path):
        name = unquote(path.replace("/static/", "", 1))
        file_path = (STATIC_DIR / name).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.exists():
            return self.error_page(404, "Static file not found.")
        data = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def home(self, user):
        with get_db() as db:
            total_events = db.execute("SELECT COUNT(*) total FROM events WHERE status='Approved'").fetchone()["total"]
            total_regs = db.execute("SELECT COUNT(*) total FROM registrations WHERE status IN ('Confirmed','Pending')").fetchone()["total"]
            sponsors = db.execute("SELECT COUNT(*) total FROM sponsors").fetchone()["total"]
            featured = db.execute("SELECT * FROM events WHERE status='Approved' ORDER BY event_date LIMIT 3").fetchall()
        cards = "".join(event_card(event) for event in featured)
        body = f"""
        <section class="hero">
            <div class="hero-copy">
                <p class="eyebrow">College event command center</p>
                <h1>Turn every campus moment into a beautifully managed experience.</h1>
                <p>Students discover events, organizers launch proposals, and admins shape approvals, schedules, sponsors, and tickets from one vivid workspace.</p>
                <div class="actions">
                    <a class="button" href="/events">Explore Events</a>
                    <a class="button ghost" href="/login">Enter Dashboard</a>
                </div>
            </div>
            <div class="hero-panel">
                <span><strong>{total_events}</strong> live events</span>
                <span><strong>{total_regs}</strong> registrations</span>
                <span><strong>{sponsors}</strong> partners</span>
            </div>
        </section>
        <section class="section-head"><h2>Featured Experiences</h2><a href="/events">View all</a></section>
        <section class="grid">{cards}</section>
        <section class="feature-strip">
            <article><strong>For students</strong><span>Discover, register, cancel, and print tickets.</span></article>
            <article><strong>For organizers</strong><span>Submit polished proposals with dates, venues, and capacity.</span></article>
            <article><strong>For admins</strong><span>Approve events, manage schedules, and connect sponsors.</span></article>
        </section>
        """
        return self.send_html(layout("Home", body, user))

    def login_page(self, user, message=""):
        if user:
            return self.redirect("/dashboard")
        body = """
        <section class="panel narrow auth-panel">
            <h1>Welcome back</h1>
            <form method="post" action="/login">
                <label>Email <input name="email" type="email" required></label>
                <label>Password <input name="password" type="password" required></label>
                <button type="submit">Login</button>
            </form>
            <p class="muted">Demo: admin@college.edu/admin123, organizer@college.edu/organizer123, student@college.edu/student123</p>
        </section>
        """
        return self.send_html(layout("Login", body, None, message))

    def register_page(self, user, message=""):
        if user:
            return self.redirect("/dashboard")
        body = """
        <section class="panel narrow auth-panel">
            <h1>Create student account</h1>
            <form method="post" action="/register">
                <label>Name <input name="name" required></label>
                <label>Email <input name="email" type="email" required></label>
                <label>Password <input name="password" type="password" required minlength="6"></label>
                <label>Department <input name="department"></label>
                <label>Phone <input name="phone"></label>
                <button type="submit">Register</button>
            </form>
        </section>
        """
        return self.send_html(layout("Register", body, None, message))

    def dashboard(self):
        user = self.require_user()
        if not user:
            return
        if user["role"] == "student":
            with get_db() as db:
                rows = db.execute(
                    """
                    SELECT r.*, e.title, e.event_date, e.end_date, e.venue, t.ticket_code
                    FROM registrations r
                    JOIN events e ON e.id=r.event_id
                    LEFT JOIN tickets t ON t.registration_id=r.id
                    WHERE r.user_id=?
                    ORDER BY r.registered_at DESC
                    """,
                    (user["id"],),
                ).fetchall()
            cards = "".join(
                f"""<article class="mini-card">
                    <h3>{esc(row['title'])}</h3>
                    <p>{esc(event_dates(row))} at {esc(row['venue'])}</p>
                    <span class="badge">{esc(row['status'])}</span>
                    {f'<a class="button small" href="/ticket/{row["id"]}">View Ticket</a>' if row["ticket_code"] else ''}
                </article>"""
                for row in rows
            ) or "<p>No registrations yet.</p>"
            body = f"<section class='section-head'><h1>Student Dashboard</h1><a class='button' href='/events'>Register</a></section><section class='grid'>{cards}</section>"
        elif user["role"] == "organizer":
            body = "<section class='panel'><h1>Organizer Studio</h1><p>Submit and track event proposals.</p><a class='button' href='/organizer/events'>Manage My Events</a></section>"
        else:
            body = """
            <section class="panel"><h1>Admin Control Room</h1>
            <section class="grid four">
                <a class="tile" href="/admin/events">Event Approvals</a>
                <a class="tile" href="/admin/registrations">Registrations</a>
                <a class="tile" href="/admin/participants">Participants</a>
                <a class="tile" href="/admin/schedules">Schedules</a>
                <a class="tile" href="/admin/sponsors">Sponsors</a>
            </section></section>
            """
        return self.send_html(layout("Dashboard", body, user))

    def profile_page(self):
        user = self.require_user()
        if not user:
            return
        with get_db() as db:
            if user["role"] == "student":
                primary = db.execute("SELECT COUNT(*) total FROM registrations WHERE user_id=?", (user["id"],)).fetchone()["total"]
                secondary = db.execute("SELECT COUNT(*) total FROM tickets t JOIN registrations r ON r.id=t.registration_id WHERE r.user_id=? AND t.status='Valid'", (user["id"],)).fetchone()["total"]
                action = '<a class="button" href="/events">Browse Events</a>'
                labels = ("Registrations", "Valid Tickets")
            elif user["role"] == "organizer":
                primary = db.execute("SELECT COUNT(*) total FROM events WHERE organizer_id=?", (user["id"],)).fetchone()["total"]
                secondary = db.execute("SELECT COUNT(*) total FROM events WHERE organizer_id=? AND status='Approved'", (user["id"],)).fetchone()["total"]
                action = '<a class="button" href="/organizer/events">Manage Events</a>'
                labels = ("Submitted Events", "Approved Events")
            else:
                primary = db.execute("SELECT COUNT(*) total FROM events WHERE status='Pending'").fetchone()["total"]
                secondary = db.execute("SELECT COUNT(*) total FROM registrations WHERE status='Pending'").fetchone()["total"]
                action = '<a class="button" href="/admin/events">Review Events</a>'
                labels = ("Pending Events", "Pending Registrations")
        body = f"""
        <section class="profile-hero panel">
            <div class="avatar">{esc(user['name'][:1]).upper()}</div>
            <div>
                <p class="eyebrow">{esc(user['role'])} profile</p>
                <h1>{esc(user['name'])}</h1>
                <p>{esc(user['email'])}</p>
                <p>{esc(user['department'])} {esc(user['phone'])}</p>
                {action}
            </div>
        </section>
        <section class="grid two">
            <article class="mini-card"><strong>{primary}</strong><span>{labels[0]}</span></article>
            <article class="mini-card"><strong>{secondary}</strong><span>{labels[1]}</span></article>
        </section>
        """
        return self.send_html(layout("Profile", body, user))

    def events_page(self, user):
        with get_db() as db:
            events = db.execute(
                """
                SELECT e.*, u.name organizer,
                (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.id AND r.status IN ('Confirmed','Pending')) registrations
                FROM events e JOIN users u ON u.id=e.organizer_id
                WHERE e.status='Approved'
                ORDER BY e.event_date, e.start_time
                """
            ).fetchall()
        cards = "".join(event_card(event) for event in events) or "<p>No approved events available.</p>"
        return self.send_html(layout("Events", f"<section class='section-head'><h1>Campus Events</h1><span>Freshly curated for your crew.</span></section><section class='grid'>{cards}</section>", user))

    def chatbot_reply(self):
        user = self.require_user(["student"])
        if not user:
            return
        intent = parse_qs(urlparse(self.path).query).get("intent", ["suggest"])[0]
        with get_db() as db:
            if intent == "tickets":
                count = db.execute(
                    "SELECT COUNT(*) total FROM tickets t JOIN registrations r ON r.id=t.registration_id WHERE r.user_id=? AND t.status='Valid'",
                    (user["id"],),
                ).fetchone()["total"]
                return self.send_json({"reply": f"You have {count} valid ticket(s). Open your dashboard to view or print them.", "link": "/dashboard"})

            rows = db.execute(
                """
                SELECT e.*,
                (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.id AND r.status IN ('Confirmed','Pending')) registrations
                FROM events e
                WHERE e.status='Approved'
                AND (e.target_department='All' OR e.target_department=?)
                AND (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.id AND r.status IN ('Confirmed','Pending')) < e.capacity
                AND e.id NOT IN (
                    SELECT event_id FROM registrations WHERE user_id=? AND status != 'Cancelled'
                )
                ORDER BY CASE WHEN e.target_department=? THEN 0 ELSE 1 END, e.event_date, e.start_time
                LIMIT 3
                """,
                (user["department"], user["id"], user["department"]),
            ).fetchall()
        if not rows:
            return self.send_json({"reply": "I could not find a fresh matching event right now. Check the Events page for all open events.", "link": "/events"})
        if intent == "department":
            department_events = [row for row in rows if row["target_department"] == user["department"]]
            rows = department_events or rows
        first = rows[0]
        reply = f"I suggest {first['title']} for {event_dates(first)} at {first['venue']}. It matches {first['target_department']} and has seats available."
        return self.send_json({"reply": reply, "link": f"/events/{first['id']}"})

    def event_detail(self, path, user):
        event_id = path.rsplit("/", 1)[-1]
        with get_db() as db:
            event = db.execute("SELECT e.*, u.name organizer FROM events e JOIN users u ON u.id=e.organizer_id WHERE e.id=?", (event_id,)).fetchone()
            if not event or event["status"] != "Approved":
                return self.error_page(404, "Event not found.")
            schedules = db.execute("SELECT * FROM schedules WHERE event_id=? ORDER BY start_time", (event_id,)).fetchall()
            sponsors = db.execute("SELECT s.* FROM sponsors s JOIN event_sponsors es ON es.sponsor_id=s.id WHERE es.event_id=?", (event_id,)).fetchall()
            registrations = db.execute("SELECT COUNT(*) total FROM registrations WHERE event_id=? AND status IN ('Confirmed','Pending')", (event_id,)).fetchone()["total"]
            existing = db.execute("SELECT * FROM registrations WHERE event_id=? AND user_id=?", (event_id, user["id"])).fetchone() if user else None
        left = max(event["capacity"] - registrations, 0)
        schedule_html = "".join(f"<li>{esc(s['start_time'])}-{esc(s['end_time'])}: {esc(s['session_title'])} <span>{esc(s['venue'])}</span></li>" for s in schedules) or "<li>No schedule added yet.</li>"
        sponsor_html = "".join(f"<li>{esc(s['name'])} <span>{esc(s['sponsorship_level'])}</span></li>" for s in sponsors) or "<li>No sponsors linked yet.</li>"
        action = self.registration_action(user, event_id, existing, left)
        body = f"""
        <section class="event-detail">
            <img src="{esc(event['image_url'])}" alt="{esc(event['title'])}">
            <div class="panel">
                <span class="badge">{esc(event['category'])}</span>
                <h1>{esc(event['title'])}</h1>
                <p>{esc(event['description'])}</p>
                <dl>
                    <div><dt>Dates</dt><dd>{esc(event_dates(event))}</dd></div>
                    <div><dt>Time</dt><dd>{esc(event_time_range(event))}</dd></div>
                    <div><dt>Department</dt><dd>{esc(event['target_department'])}</dd></div>
                    <div><dt>Venue</dt><dd>{esc(event['venue'])}</dd></div>
                    <div><dt>Seats</dt><dd>{left} of {event['capacity']}</dd></div>
                </dl>
                {action}
            </div>
        </section>
        <section class="grid two">
            <article class="panel"><h2>Schedule</h2><ul class="timeline">{schedule_html}</ul></article>
            <article class="panel"><h2>Sponsors</h2><ul class="timeline">{sponsor_html}</ul></article>
        </section>
        """
        return self.send_html(layout(event["title"], body, user))

    def registration_action(self, user, event_id, existing, left):
        if user and user["role"] == "student":
            if existing and existing["status"] != "Cancelled":
                return f"""<p>Your status: <span class="badge">{esc(existing['status'])}</span></p>
                <form method="post" action="/events/cancel"><input type="hidden" name="event_id" value="{event_id}"><button class="danger">Cancel Registration</button></form>"""
            if left > 0:
                return f"""<form method="post" action="/events/register"><input type="hidden" name="event_id" value="{event_id}"><button>Apply for Registration</button></form>"""
            return "<p class='badge'>House full</p>"
        if not user:
            return '<a class="button" href="/login">Login to Register</a>'
        return ""

    def organizer_events(self):
        user = self.require_user(["organizer"])
        if not user:
            return
        with get_db() as db:
            rows = db.execute("SELECT * FROM events WHERE organizer_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
        event_rows = "".join(
            f"<tr><td>{esc(r['title'])}</td><td>{esc(event_dates(r))}</td><td>{esc(r['target_department'])}</td><td>{esc(r['venue'])}</td><td><span class='badge'>{esc(r['status'])}</span></td><td>{esc(r['admin_remarks'])}</td><td><a class='button small' href='/organizer/participants?event_id={r['id']}'>Participants</a></td></tr>"
            for r in rows
        )
        body = f"""
        <section class="panel">
            <h1>Submit Event Proposal</h1>
            <form class="wide" method="post" action="/organizer/events">
                <label>Title <input name="title" required></label>
                <label>Category <input name="category" required></label>
                <label>Department <select name="target_department"><option>All</option><option>Computer Science</option><option>Information Technology</option><option>Electronics</option><option>Mechanical</option><option>Civil</option><option>Administration</option></select></label>
                <label>Venue <input name="venue" required></label>
                <label>Image URL <input name="image_url" type="url" placeholder="https://example.com/photo.jpg"></label>
                <label>Start Date <input name="event_date" type="date" required></label>
                <label>End Date <input name="end_date" type="date"></label>
                <label>Start Time <input name="start_time" type="time" required></label>
                <label>End Time <input name="end_time" type="time" required></label>
                <label>Capacity <input name="capacity" type="number" min="1" required></label>
                <label>Need admin approval? <select name="approval_required"><option value="0">No - publish direct</option><option value="1">Yes - send to admin</option></select></label>
                <label class="full">Description <textarea name="description" required></textarea></label>
                <button type="submit">Save Event</button>
            </form>
        </section>
        <section class="panel"><h2>My Events</h2><table><thead><tr><th>Title</th><th>Date</th><th>Department</th><th>Venue</th><th>Status</th><th>Remarks</th><th>People</th></tr></thead><tbody>{event_rows}</tbody></table></section>
        """
        return self.send_html(layout("Organizer Events", body, user))

    def organizer_participants(self):
        user = self.require_user(["organizer"])
        if not user:
            return
        event_id = parse_qs(urlparse(self.path).query).get("event_id", [""])[0]
        with get_db() as db:
            event = db.execute("SELECT * FROM events WHERE id=? AND organizer_id=?", (event_id, user["id"])).fetchone()
            if not event:
                return self.error_page(404, "Event not found.")
            rows = db.execute(
                """
                SELECT u.id student_id, u.name, u.email, u.department, r.status, r.registered_at, t.ticket_code
                FROM registrations r
                JOIN users u ON u.id=r.user_id
                LEFT JOIN tickets t ON t.registration_id=r.id
                WHERE r.event_id=?
                ORDER BY r.registered_at DESC
                """,
                (event_id,),
            ).fetchall()
        table = participant_rows(rows)
        body = f"<section class='panel'><h1>{esc(event['title'])} Participants</h1><p class='muted'>{esc(event_dates(event))} | {esc(event['target_department'])}</p><table><thead>{participant_head()}</thead><tbody>{table}</tbody></table></section>"
        return self.send_html(layout("Participants", body, user))

    def admin_events(self):
        user = self.require_user(["admin"])
        if not user:
            return
        with get_db() as db:
            rows = db.execute("SELECT e.*, u.name organizer FROM events e JOIN users u ON u.id=e.organizer_id WHERE e.status='Pending' ORDER BY e.created_at DESC").fetchall()
        table = "".join(
            f"""<tr><td>{esc(r['title'])}<small>{esc(r['description'])}</small></td><td>{esc(r['organizer'])}</td><td>{esc(event_dates(r))}</td><td>{esc(r['target_department'])}</td><td>{esc(r['capacity'])}</td><td><span class="badge">{esc(r['status'])}</span></td>
            <td><form class="inline" method="post" action="/admin/event-status"><input type="hidden" name="event_id" value="{r['id']}"><input name="remarks" placeholder="Remarks"><button name="status" value="Approved">Approve</button><button class="danger" name="status" value="Rejected">Reject</button></form></td></tr>"""
            for r in rows
        ) or "<tr><td colspan='7'>No events are waiting for approval.</td></tr>"
        return self.send_html(layout("Admin Events", f"<section class='panel'><h1>Pending Event Approvals</h1><p><a class='button small' href='/admin/participants'>View All Participants</a></p><table><thead><tr><th>Event</th><th>Organizer</th><th>Date</th><th>Department</th><th>Capacity</th><th>Status</th><th>Action</th></tr></thead><tbody>{table}</tbody></table></section>", user))

    def admin_participants(self):
        user = self.require_user(["admin"])
        if not user:
            return
        event_id = parse_qs(urlparse(self.path).query).get("event_id", [""])[0]
        with get_db() as db:
            event_filter = ""
            params = []
            event_title = "All Event Participants"
            if event_id:
                event = db.execute("SELECT title FROM events WHERE id=?", (event_id,)).fetchone()
                if event:
                    event_title = f"{event['title']} Participants"
                    event_filter = "WHERE r.event_id=?"
                    params.append(event_id)
            rows = db.execute(
                f"""
                SELECT u.id student_id, u.name, u.email, u.department, r.status, r.registered_at, t.ticket_code, e.title event_title
                FROM registrations r
                JOIN users u ON u.id=r.user_id
                JOIN events e ON e.id=r.event_id
                LEFT JOIN tickets t ON t.registration_id=r.id
                {event_filter}
                ORDER BY e.title, r.registered_at DESC
                """,
                params,
            ).fetchall()
        table = participant_rows(rows, include_event=True)
        body = f"<section class='panel'><h1>{esc(event_title)}</h1><table><thead>{participant_head(include_event=True)}</thead><tbody>{table}</tbody></table></section>"
        return self.send_html(layout("Participants", body, user))

    def admin_registrations(self):
        user = self.require_user(["admin"])
        if not user:
            return
        with get_db() as db:
            rows = db.execute("SELECT r.*, u.name student, u.email, e.title event_title FROM registrations r JOIN users u ON u.id=r.user_id JOIN events e ON e.id=r.event_id ORDER BY r.registered_at DESC").fetchall()
        table = "".join(
            f"""<tr><td>{esc(r['student'])}<small>{esc(r['email'])}</small></td><td>{esc(r['event_title'])}</td><td><span class="badge">{esc(r['status'])}</span></td>
            <td><form class="inline" method="post" action="/admin/registration-status"><input type="hidden" name="registration_id" value="{r['id']}"><button name="status" value="Confirmed">Approve</button><button class="danger" name="status" value="Rejected">Reject</button></form></td></tr>"""
            for r in rows
        )
        return self.send_html(layout("Registrations", f"<section class='panel'><h1>Registration Approvals</h1><table><thead><tr><th>Student</th><th>Event</th><th>Status</th><th>Action</th></tr></thead><tbody>{table}</tbody></table></section>", user))

    def admin_schedules(self):
        user = self.require_user(["admin"])
        if not user:
            return
        with get_db() as db:
            events = db.execute("SELECT id,title FROM events WHERE status='Approved' ORDER BY title").fetchall()
            schedules = db.execute("SELECT s.*, e.title FROM schedules s JOIN events e ON e.id=s.event_id ORDER BY e.title, s.start_time").fetchall()
        options = "".join(f"<option value='{e['id']}'>{esc(e['title'])}</option>" for e in events)
        rows = "".join(f"<tr><td>{esc(s['title'])}</td><td>{esc(s['session_title'])}</td><td>{esc(s['speaker'])}</td><td>{esc(s['start_time'])}-{esc(s['end_time'])}</td><td>{esc(s['venue'])}</td></tr>" for s in schedules)
        body = f"""
        <section class="panel"><h1>Add Schedule Session</h1><form class="wide" method="post" action="/admin/schedules">
            <label>Event <select name="event_id" required>{options}</select></label><label>Session Title <input name="session_title" required></label><label>Speaker/Host <input name="speaker"></label><label>Start Time <input name="start_time" type="time" required></label><label>End Time <input name="end_time" type="time" required></label><label>Venue <input name="venue" required></label><button type="submit">Add Session</button>
        </form></section>
        <section class="panel"><h2>Schedules</h2><table><thead><tr><th>Event</th><th>Session</th><th>Speaker</th><th>Time</th><th>Venue</th></tr></thead><tbody>{rows}</tbody></table></section>
        """
        return self.send_html(layout("Schedules", body, user))

    def admin_sponsors(self):
        user = self.require_user(["admin"])
        if not user:
            return
        with get_db() as db:
            events = db.execute("SELECT id,title FROM events WHERE status='Approved' ORDER BY title").fetchall()
            sponsors = db.execute("SELECT * FROM sponsors ORDER BY name").fetchall()
        event_options = "".join(f"<option value='{e['id']}'>{esc(e['title'])}</option>" for e in events)
        sponsor_options = "".join(f"<option value='{s['id']}'>{esc(s['name'])}</option>" for s in sponsors)
        sponsor_rows = "".join(f"<tr><td>{esc(s['name'])}</td><td>{esc(s['sponsorship_level'])}</td><td>{esc(s['amount'])}</td><td>{esc(s['contact_email'])}</td></tr>" for s in sponsors)
        body = f"""
        <section class="grid two">
            <article class="panel"><h1>Add Sponsor</h1><form method="post" action="/admin/sponsors"><label>Name <input name="name" required></label><label>Email <input name="contact_email" type="email"></label><label>Phone <input name="phone"></label><label>Level <select name="sponsorship_level"><option>Gold</option><option>Silver</option><option>Bronze</option><option>Partner</option></select></label><label>Amount <input name="amount" type="number" min="0" step="100"></label><button type="submit">Add Sponsor</button></form></article>
            <article class="panel"><h1>Link Sponsor</h1><form method="post" action="/admin/link-sponsor"><label>Event <select name="event_id">{event_options}</select></label><label>Sponsor <select name="sponsor_id">{sponsor_options}</select></label><button type="submit">Link Sponsor</button></form></article>
        </section>
        <section class="panel"><h2>Sponsors</h2><table><thead><tr><th>Name</th><th>Level</th><th>Amount</th><th>Email</th></tr></thead><tbody>{sponsor_rows}</tbody></table></section>
        """
        return self.send_html(layout("Sponsors", body, user))

    def ticket_page(self, path):
        user = self.require_user(["student", "admin"])
        if not user:
            return
        reg_id = path.rsplit("/", 1)[-1]
        with get_db() as db:
            row = db.execute(
                """
                SELECT r.*, u.name student, u.email, e.title, e.event_date, e.end_date, e.start_time, e.end_time, e.venue, t.ticket_code, t.status ticket_status
                FROM registrations r JOIN users u ON u.id=r.user_id JOIN events e ON e.id=r.event_id JOIN tickets t ON t.registration_id=r.id
                WHERE r.id=?
                """,
                (reg_id,),
            ).fetchone()
        if not row or (user["role"] == "student" and row["user_id"] != user["id"]):
            return self.error_page(404, "Ticket not found.")
        qr = "".join("<span></span>" for _ in range(64))
        body = f"""<section class="ticket"><div><p class="eyebrow">Digital pass</p><h1>{esc(row['title'])}</h1><p><strong>Student:</strong> {esc(row['student'])}</p><p><strong>Email:</strong> {esc(row['email'])}</p><p><strong>Dates:</strong> {esc(event_dates(row))} {esc(event_time_range(row))}</p><p><strong>Venue:</strong> {esc(row['venue'])}</p><p><strong>Ticket Code:</strong> {esc(row['ticket_code'])}</p><span class="badge">{esc(row['ticket_status'])}</span></div><div class="qr">{qr}</div></section><button onclick="window.print()">Print Ticket</button>"""
        return self.send_html(layout("Ticket", body, user))

    def login_action(self):
        data = self.read_form()
        email = form_value(data, "email").lower()
        password = form_value(data, "password")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            return self.login_page(None, "Invalid email or password.")
        return self.redirect("/dashboard", f"cems_session={make_session(user['id'])}; Path=/; HttpOnly; SameSite=Lax")

    def register_action(self):
        data = self.read_form()
        try:
            with get_db() as db:
                db.execute(
                    "INSERT INTO users(name,email,password_hash,role,department,phone) VALUES(?,?,?,?,?,?)",
                    (form_value(data, "name"), form_value(data, "email").lower(), hash_password(form_value(data, "password")), "student", form_value(data, "department"), form_value(data, "phone")),
                )
            return self.login_page(None, "Account created. Please login.")
        except sqlite3.IntegrityError:
            return self.register_page(None, "Email already exists.")

    def register_event(self):
        user = self.require_user(["student"])
        if not user:
            return
        event_id = form_value(self.read_form(), "event_id")
        with get_db() as db:
            event = db.execute("SELECT * FROM events WHERE id=? AND status='Approved'", (event_id,)).fetchone()
            if not event:
                return self.error_page(404, "Event not found.")
            if event["target_department"] != "All" and event["target_department"] != user["department"]:
                return self.error_page(403, "This event is only open for the selected department.")
            existing = db.execute("SELECT * FROM registrations WHERE event_id=? AND user_id=?", (event_id, user["id"])).fetchone()
            if existing and existing["status"] != "Cancelled":
                return self.redirect("/dashboard")
            taken = db.execute("SELECT COUNT(*) total FROM registrations WHERE event_id=? AND status IN ('Confirmed','Pending')", (event_id,)).fetchone()["total"]
            if taken >= event["capacity"]:
                return self.redirect(f"/events/{event_id}")
            status = "Pending" if event["approval_required"] else "Confirmed"
            if existing:
                db.execute("UPDATE registrations SET status=?, registered_at=CURRENT_TIMESTAMP WHERE id=?", (status, existing["id"]))
                registration_id = existing["id"]
            else:
                cur = db.execute("INSERT INTO registrations(user_id,event_id,status) VALUES(?,?,?)", (user["id"], event_id, status))
                registration_id = cur.lastrowid
            if status == "Confirmed":
                self.issue_ticket(db, registration_id)
        return self.redirect("/dashboard")

    def cancel_registration(self):
        user = self.require_user(["student"])
        if not user:
            return
        event_id = form_value(self.read_form(), "event_id")
        with get_db() as db:
            reg = db.execute("SELECT * FROM registrations WHERE user_id=? AND event_id=?", (user["id"], event_id)).fetchone()
            if reg:
                db.execute("UPDATE registrations SET status='Cancelled' WHERE id=?", (reg["id"],))
                db.execute("UPDATE tickets SET status='Cancelled' WHERE registration_id=?", (reg["id"],))
        return self.redirect(f"/events/{event_id}")

    def create_event(self):
        user = self.require_user(["organizer"])
        if not user:
            return
        data = self.read_form()
        approval_required = int(form_value(data, "approval_required", "0"))
        status = "Pending" if approval_required else "Approved"
        start_date = form_value(data, "event_date")
        end_date = form_value(data, "end_date") or start_date
        with get_db() as db:
            db.execute(
                """
                INSERT INTO events(title,description,image_url,category,target_department,venue,event_date,end_date,start_time,end_time,capacity,status,approval_required,organizer_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    form_value(data, "title"),
                    form_value(data, "description"),
                    form_value(data, "image_url"),
                    form_value(data, "category"),
                    form_value(data, "target_department", "All"),
                    form_value(data, "venue"),
                    start_date,
                    end_date,
                    form_value(data, "start_time"),
                    form_value(data, "end_time"),
                    int(form_value(data, "capacity", "1")),
                    status,
                    approval_required,
                    user["id"],
                ),
            )
        return self.redirect("/organizer/events")

    def update_event_status(self):
        user = self.require_user(["admin"])
        if not user:
            return
        data = self.read_form()
        with get_db() as db:
            db.execute("UPDATE events SET status=?, admin_remarks=? WHERE id=?", (form_value(data, "status"), form_value(data, "remarks"), form_value(data, "event_id")))
        return self.redirect("/admin/events")

    def update_registration_status(self):
        user = self.require_user(["admin"])
        if not user:
            return
        data = self.read_form()
        reg_id = form_value(data, "registration_id")
        status = form_value(data, "status")
        with get_db() as db:
            db.execute("UPDATE registrations SET status=? WHERE id=?", (status, reg_id))
            if status == "Confirmed":
                self.issue_ticket(db, reg_id)
            elif status == "Rejected":
                db.execute("UPDATE tickets SET status='Cancelled' WHERE registration_id=?", (reg_id,))
        return self.redirect("/admin/registrations")

    def add_schedule(self):
        user = self.require_user(["admin"])
        if not user:
            return
        data = self.read_form()
        with get_db() as db:
            db.execute("INSERT INTO schedules(event_id,session_title,speaker,start_time,end_time,venue) VALUES(?,?,?,?,?,?)", (form_value(data, "event_id"), form_value(data, "session_title"), form_value(data, "speaker"), form_value(data, "start_time"), form_value(data, "end_time"), form_value(data, "venue")))
        return self.redirect("/admin/schedules")

    def add_sponsor(self):
        user = self.require_user(["admin"])
        if not user:
            return
        data = self.read_form()
        with get_db() as db:
            db.execute("INSERT INTO sponsors(name,contact_email,phone,sponsorship_level,amount) VALUES(?,?,?,?,?)", (form_value(data, "name"), form_value(data, "contact_email"), form_value(data, "phone"), form_value(data, "sponsorship_level"), float(form_value(data, "amount", "0") or 0)))
        return self.redirect("/admin/sponsors")

    def link_sponsor(self):
        user = self.require_user(["admin"])
        if not user:
            return
        data = self.read_form()
        with get_db() as db:
            db.execute("INSERT OR IGNORE INTO event_sponsors(event_id,sponsor_id) VALUES(?,?)", (form_value(data, "event_id"), form_value(data, "sponsor_id")))
        return self.redirect("/admin/sponsors")

    def issue_ticket(self, db, registration_id):
        existing = db.execute("SELECT id FROM tickets WHERE registration_id=?", (registration_id,)).fetchone()
        if existing:
            db.execute("UPDATE tickets SET status='Valid' WHERE registration_id=?", (registration_id,))
            return
        code = "CC-" + secrets.token_hex(4).upper()
        db.execute("INSERT INTO tickets(registration_id,ticket_code,status) VALUES(?,?,?)", (registration_id, code, "Valid"))

    def error_page(self, status, message):
        self.send_html(layout(f"Error {status}", f"<section class='panel'><h1>Error {status}</h1><p>{esc(message)}</p></section>", self.current_user()), status)


def event_card(event):
    registrations = event["registrations"] if "registrations" in event.keys() else 0
    left = max(event["capacity"] - registrations, 0)
    return f"""
    <article class="event-card">
        <img src="{esc(event['image_url'])}" alt="{esc(event['title'])}">
        <div>
            <span class="badge">{esc(event['category'])}</span>
            <span class="badge soft">{esc(event['target_department'])}</span>
            <h3>{esc(event['title'])}</h3>
            <p>{esc(event['description'])}</p>
            <footer><span>{esc(event_dates(event))} at {esc(event['venue'])}</span><span>{left} seats</span></footer>
            <a class="button small" href="/events/{event['id']}">View Details</a>
        </div>
    </article>
    """


def participant_head(include_event=False):
    event_col = "<th>Event</th>" if include_event else ""
    return f"<tr>{event_col}<th>Student ID</th><th>Name</th><th>Email</th><th>Department</th><th>Status</th><th>Ticket</th><th>Registered</th></tr>"


def participant_rows(rows, include_event=False):
    if not rows:
        colspan = 8 if include_event else 7
        return f"<tr><td colspan='{colspan}'>No participants yet.</td></tr>"
    html_rows = ""
    for row in rows:
        event_col = f"<td>{esc(row['event_title'])}</td>" if include_event else ""
        html_rows += (
            f"<tr>{event_col}<td>{esc(row['student_id'])}</td><td>{esc(row['name'])}</td>"
            f"<td>{esc(row['email'])}</td><td>{esc(row['department'])}</td>"
            f"<td><span class='badge'>{esc(row['status'])}</span></td><td>{esc(row['ticket_code'])}</td>"
            f"<td>{esc(row['registered_at'])}</td></tr>"
        )
    return html_rows


if __name__ == "__main__":
    log_path = BASE_DIR / "server.log"
    try:
        init_db()
        port = int(os.environ.get("PORT", "8000"))
        server = HTTPServer(("0.0.0.0", port), App)
        log_path.write_text(f"Campus Canvas running on http://localhost:{port}\n", encoding="utf-8")
        try:
            print(f"Campus Canvas running on http://localhost:{port}", flush=True)
        except OSError:
            pass
        server.serve_forever()
    except Exception as exc:
        log_path.write_text(f"Startup failed: {exc}\n", encoding="utf-8")
        raise
