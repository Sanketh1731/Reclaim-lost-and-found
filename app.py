# app.py
import os
import re
import uuid
import secrets
import sqlite3
import smtplib
from email.message import EmailMessage

from datetime import datetime, timedelta
from difflib import SequenceMatcher
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_from_directory, flash, jsonify
)

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# --------------------
# CONFIG
# --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

STATIC_DIR = os.path.join(BASE_DIR, "Static") if os.path.exists(os.path.join(BASE_DIR, "Static")) else os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "Templates") if os.path.exists(os.path.join(BASE_DIR, "Templates")) else os.path.join(BASE_DIR, "templates")

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR,
    static_url_path="/static"
)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB
app.secret_key = os.environ.get("SECRET_KEY", "reclaim-dev-secret-key-2026")
# notification match threshold (0-100)
MATCH_NOTIFY_THRESHOLD = int(os.environ.get("MATCH_NOTIFY_THRESHOLD", "60"))
# email config (optional)
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587")) if os.environ.get("SMTP_PORT") else None
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/Static/<path:filename>")
def static_uppercase_fallback(filename):
    return send_from_directory(app.static_folder, filename)



# --------------------
# DB HELPERS & AUTO-MIGRATIONS
# --------------------
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            date_joined TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            reputation INTEGER DEFAULT 0,
            reports_count INTEGER DEFAULT 0,
            returned_count INTEGER DEFAULT 0
        )
    """)

    # lost_items table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lost_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            contact TEXT NOT NULL,
            category TEXT NOT NULL,
            date_reported TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            image TEXT,
            user_id INTEGER
        )
    """)

    # found_items table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS found_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            contact TEXT NOT NULL,
            category TEXT NOT NULL,
            date_reported TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            image TEXT,
            user_id INTEGER
        )
    """)

    # notifications table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            is_read INTEGER DEFAULT 0,
            date_created TEXT NOT NULL
        )
    """)

    # password_resets table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # claims table (Ownership Verification & Claims)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            claimant_id INTEGER NOT NULL,
            finder_id INTEGER NOT NULL,
            question TEXT,
            answer TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            date_submitted TEXT NOT NULL,
            date_reviewed TEXT,
            FOREIGN KEY (claimant_id) REFERENCES users(id),
            FOREIGN KEY (finder_id) REFERENCES users(id)
        )
    """)

    # item_flags table (Community Moderation & Reporting)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS item_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            reporter_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            details TEXT,
            date_reported TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            FOREIGN KEY (reporter_id) REFERENCES users(id)
        )
    """)

    # messages table (Direct In-App Chat)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        )
    """)

    # Safe column migrations for existing databases
    # 1. Users table columns
    cur.execute("PRAGMA table_info(users)")
    user_cols = [r[1] for r in cur.fetchall()]
    if "is_admin" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    if "reputation" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN reputation INTEGER DEFAULT 0")
    if "reports_count" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN reports_count INTEGER DEFAULT 0")
    if "returned_count" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN returned_count INTEGER DEFAULT 0")

    # 2. Lost & Found tables columns
    for table in ("lost_items", "found_items"):
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        if "image" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN image TEXT")
        if "user_id" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")
        if "status" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN status TEXT DEFAULT 'Active'")
        if "latitude" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN latitude REAL")
        if "longitude" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN longitude REAL")

    # 3. Found items verification_question column
    cur.execute("PRAGMA table_info(found_items)")
    found_cols = [r[1] for r in cur.fetchall()]
    if "verification_question" not in found_cols:
        cur.execute("ALTER TABLE found_items ADD COLUMN verification_question TEXT")

    conn.commit()
    conn.close()


init_db()


# --------------------
# CONTEXT PROCESSORS & TEMPLATE GLOBALS
# --------------------
@app.context_processor
def inject_globals():
    unread_count = 0
    unread_messages_count = 0
    is_admin = False
    if "user_id" in session:
        try:
            conn = get_db_connection()
            u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            if u and u["is_admin"] == 1:
                is_admin = True
            unread = conn.execute(
                "SELECT COUNT(*) as c FROM notifications WHERE user_id = ? AND is_read = 0",
                (session["user_id"],)
            ).fetchone()
            unread_count = unread["c"] if unread else 0
            
            unread_msgs = conn.execute(
                "SELECT COUNT(*) as c FROM messages WHERE receiver_id = ? AND is_read = 0",
                (session["user_id"],)
            ).fetchone()
            unread_messages_count = unread_msgs["c"] if unread_msgs else 0

            conn.close()
        except Exception:
            pass
    return {
        "current_year": datetime.now().year,
        "unread_notifications_count": unread_count,
        "unread_messages_count": unread_messages_count,
        "is_admin_user": is_admin,
        "now": datetime.now
    }


# --------------------
# FILE HELPERS
# --------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def delete_image_file(filename):
    if not filename:
        return
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# --------------------
# AUTH DECORATORS
# --------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access this page.", "info")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Admin login required.", "warning")
            return redirect(url_for("login", next=request.path))
        conn = get_db_connection()
        user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        conn.close()
        if not user or user["is_admin"] != 1:
            flash("Access denied: Admin privileges required.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


# --------------------
# SMART MATCHING ENGINE
# --------------------
def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def text_similarity(text1, text2):
    text1 = normalize_text(text1)
    text2 = normalize_text(text2)
    if not text1 or not text2:
        return 0.0
    sequence_score = SequenceMatcher(None, text1, text2).ratio()
    words1 = set(text1.split())
    words2 = set(text2.split())
    if words1 and words2:
        inter = words1.intersection(words2)
        union = words1.union(words2)
        word_score = len(inter) / len(union) if union else 0.0
    else:
        word_score = 0.0
    return sequence_score * 0.6 + word_score * 0.4


def calculate_match_components(item1, item2):
    d1 = dict(item1) if not isinstance(item1, dict) else item1
    d2 = dict(item2) if not isinstance(item2, dict) else item2
    n = {}
    n["name"] = round(text_similarity(d1.get("name", ""), d2.get("name", "")) * 100)
    n["description"] = round(text_similarity(d1.get("description", ""), d2.get("description", "")) * 100)
    # Category match: exact match = 100%, otherwise string similarity
    c1 = normalize_text(d1.get("category", ""))
    c2 = normalize_text(d2.get("category", ""))
    if c1 and c2 and c1 == c2:
        n["category"] = 100
    else:
        n["category"] = round(text_similarity(c1, c2) * 100)
    n["location"] = round(text_similarity(d1.get("location", ""), d2.get("location", "")) * 100)

    final = round((n["name"] * 0.35 + n["description"] * 0.25 + n["category"] * 0.25 + n["location"] * 0.15))
    return {"components": n, "score": final}


def find_matches(item, item_type, limit=6):
    conn = get_db_connection()
    if item_type == "lost":
        candidates = conn.execute("SELECT * FROM found_items WHERE status='Active'").fetchall()
    else:
        candidates = conn.execute("SELECT * FROM lost_items WHERE status='Active'").fetchall()
    conn.close()
    matches = []
    for cand in candidates:
        comp = calculate_match_components(item, cand)
        if comp["score"] >= 20:
            matches.append({"item": cand, "score": comp["score"], "components": comp["components"]})
    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:limit]


# --------------------
# NOTIFICATIONS (IN-APP + EMAIL)
# --------------------
def create_notification(user_id, title, message, link=None):
    conn = get_db_connection()
    date_created = datetime.now().strftime("%d %b %Y %H:%M")
    conn.execute("""INSERT INTO notifications (user_id, title, message, link, is_read, date_created)
                    VALUES (?, ?, ?, ?, 0, ?)""", (user_id, title, message, link, date_created))
    conn.commit()
    conn.close()


def send_email_if_configured(to_email, subject, body):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS or not EMAIL_FROM:
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception:
        return False


def notify_matches_on_create(new_item, new_type):
    matches = find_matches(new_item, new_type, limit=8)
    for m in matches:
        if m["score"] >= MATCH_NOTIFY_THRESHOLD:
            owner_id = m["item"]["user_id"]
            if owner_id and owner_id != session.get("user_id"):
                title = "Smart Match Found"
                msg = f"A new {new_type} report closely matches your listing '{m['item']['name']}': {new_item['name']} ({m['score']}% match)."
                link = f"/item/{ 'found' if new_type=='lost' else 'lost' }/{m['item']['id']}"
                create_notification(owner_id, title, msg, link)
                conn = get_db_connection()
                user = conn.execute("SELECT email FROM users WHERE id = ?", (owner_id,)).fetchone()
                conn.close()
                if user:
                    send_email_if_configured(user["email"], title, msg + f"\n\nView details: {link}")


# --------------------
# PASSWORD RESET HELPERS
# --------------------
def generate_reset_token(user_id):
    conn = get_db_connection()
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    created_at = now.isoformat()
    expires_at = (now + timedelta(hours=1)).isoformat()
    conn.execute("""
        INSERT INTO password_resets (user_id, token, created_at, expires_at, used)
        VALUES (?, ?, ?, ?, 0)
    """, (user_id, token, created_at, expires_at))
    conn.commit()
    conn.close()
    return token


def validate_reset_token(token):
    if not token:
        return None
    conn = get_db_connection()
    reset_record = conn.execute(
        "SELECT * FROM password_resets WHERE token = ? AND used = 0",
        (token,)
    ).fetchone()
    if not reset_record:
        conn.close()
        return None
    try:
        expires_at = datetime.fromisoformat(reset_record["expires_at"])
        if datetime.now() > expires_at:
            conn.close()
            return None
    except Exception:
        conn.close()
        return None
    user = conn.execute("SELECT * FROM users WHERE id = ?", (reset_record["user_id"],)).fetchone()
    conn.close()
    return user


def mark_token_used(token):
    conn = get_db_connection()
    conn.execute("UPDATE password_resets SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# --------------------
# PUBLIC ROUTES
# --------------------
@app.route("/")
def index():
    conn = get_db_connection()
    # Active available items for the main grid
    lost_items = conn.execute("SELECT * FROM lost_items WHERE status = 'Active' ORDER BY id DESC LIMIT 50").fetchall()
    found_items = conn.execute("SELECT * FROM found_items WHERE status = 'Active' ORDER BY id DESC LIMIT 50").fetchall()
    
    # Recent reunited / success stories
    reunited_lost = conn.execute("SELECT *, 'lost' as item_type FROM lost_items WHERE status = 'Returned' ORDER BY id DESC LIMIT 8").fetchall()
    reunited_found = conn.execute("SELECT *, 'found' as item_type FROM found_items WHERE status = 'Returned' ORDER BY id DESC LIMIT 8").fetchall()
    reunited_items = list(reunited_lost) + list(reunited_found)
    reunited_items.sort(key=lambda x: x["id"], reverse=True)
    reunited_items = reunited_items[:8]

    # Community stats
    total_recovered = conn.execute("SELECT COUNT(*) as c FROM (SELECT id FROM lost_items WHERE status='Returned' UNION ALL SELECT id FROM found_items WHERE status='Returned')").fetchone()["c"]
    total_active = len(lost_items) + len(found_items)
    total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    conn.close()

    stats = {
        "recovered": total_recovered,
        "active": total_active,
        "active_lost": len(lost_items),
        "active_found": len(found_items),
        "users": total_users,
        "reunited_count": total_recovered
    }
    return render_template(
        "index.html",
        lost_items=lost_items,
        found_items=found_items,
        reunited_items=reunited_items,
        stats=stats,
        current_type="all"
    )



@app.route("/search")
def search():
    q = request.args.get("query", "").strip()
    category = request.args.get("category", "").strip()
    item_type = request.args.get("type", "all").strip()  # all, lost, found
    status = request.args.get("status", "active").strip()    # active, returned, all

    conn = get_db_connection()
    lost_items = []
    found_items = []

    def build_query(table):
        query_sql = f"SELECT * FROM {table} WHERE 1=1"
        params = []
        if q:
            query_sql += " AND (name LIKE ? OR description LIKE ? OR location LIKE ? OR category LIKE ?)"
            pattern = f"%{q}%"
            params.extend([pattern, pattern, pattern, pattern])
        if category and category != "all":
            query_sql += " AND category = ?"
            params.append(category)
        if status and status != "all":
            query_sql += " AND status = ?"
            params.append(status.capitalize())
        query_sql += " ORDER BY id DESC"
        return query_sql, params

    if item_type in ("all", "lost"):
        sql, params = build_query("lost_items")
        lost_items = conn.execute(sql, params).fetchall()

    if item_type in ("all", "found"):
        sql, params = build_query("found_items")
        found_items = conn.execute(sql, params).fetchall()

    total_recovered = conn.execute("SELECT COUNT(*) as c FROM (SELECT id FROM lost_items WHERE status='Returned' UNION ALL SELECT id FROM found_items WHERE status='Returned')").fetchone()["c"]
    total_active = conn.execute("SELECT COUNT(*) as c FROM (SELECT id FROM lost_items WHERE status='Active' UNION ALL SELECT id FROM found_items WHERE status='Active')").fetchone()["c"]
    total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    conn.close()

    stats = {
        "recovered": total_recovered,
        "active": total_active,
        "active_lost": len(lost_items),
        "active_found": len(found_items),
        "users": total_users
    }

    return render_template("index.html", lost_items=lost_items, found_items=found_items, stats=stats, current_query=q, current_category=category, current_type=item_type, current_status=status)


@app.route("/reclaimed")
def reclaimed():
    q = request.args.get("query", "").strip()
    category = request.args.get("category", "").strip()
    item_type = request.args.get("type", "all").strip()  # all, lost, found

    conn = get_db_connection()
    lost_items = []
    found_items = []

    def build_archive_query(table):
        query_sql = f"SELECT * FROM {table} WHERE status = 'Returned'"
        params = []
        if q:
            query_sql += " AND (name LIKE ? OR description LIKE ? OR location LIKE ? OR category LIKE ?)"
            pattern = f"%{q}%"
            params.extend([pattern, pattern, pattern, pattern])
        if category and category != "all":
            query_sql += " AND category = ?"
            params.append(category)
        query_sql += " ORDER BY id DESC"
        return query_sql, params

    if item_type in ("all", "lost"):
        sql, params = build_archive_query("lost_items")
        lost_items = conn.execute(sql, params).fetchall()

    if item_type in ("all", "found"):
        sql, params = build_archive_query("found_items")
        found_items = conn.execute(sql, params).fetchall()

    total_reclaimed = len(lost_items) + len(found_items)
    conn.close()

    return render_template(
        "reclaimed.html",
        lost_items=lost_items,
        found_items=found_items,
        total_reclaimed=total_reclaimed,
        current_query=q,
        current_category=category,
        current_type=item_type
    )


@app.route("/api/search")
def api_search():
    q = request.args.get("query", "").strip()
    category = request.args.get("category", "").strip()
    item_type = request.args.get("type", "all").strip()
    status = request.args.get("status", "active").strip()

    conn = get_db_connection()
    lost_items = []
    found_items = []

    def fetch_items(table, itype):
        query_sql = f"SELECT * FROM {table} WHERE 1=1"
        params = []
        if q:
            query_sql += " AND (name LIKE ? OR description LIKE ? OR location LIKE ? OR category LIKE ?)"
            p = f"%{q}%"
            params.extend([p, p, p, p])
        if category and category != "all":
            query_sql += " AND category = ?"
            params.append(category)
        if status and status != "all":
            query_sql += " AND status = ?"
            params.append(status.capitalize())
        query_sql += " ORDER BY id DESC"
        rows = conn.execute(query_sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["type"] = itype
            result.append(d)
        return result

    if item_type in ("all", "lost"):
        lost_items = fetch_items("lost_items", "lost")
    if item_type in ("all", "found"):
        found_items = fetch_items("found_items", "found")

    conn.close()
    return jsonify({
        "lost": lost_items,
        "found": found_items,
        "total": len(lost_items) + len(found_items)
    })


@app.route("/leaderboard")
def leaderboard():
    conn = get_db_connection()
    top_helpers = conn.execute("""
        SELECT id, name, reputation, reports_count, returned_count, date_joined
        FROM users
        ORDER BY reputation DESC, returned_count DESC, id ASC
        LIMIT 25
    """).fetchall()
    
    total_reclaimed = conn.execute("SELECT COUNT(*) as c FROM (SELECT id FROM lost_items WHERE status='Returned' UNION ALL SELECT id FROM found_items WHERE status='Returned')").fetchone()["c"]
    total_reports = conn.execute("SELECT COUNT(*) as c FROM (SELECT id FROM lost_items UNION ALL SELECT id FROM found_items)").fetchone()["c"]
    total_helpers = conn.execute("SELECT COUNT(*) as c FROM users WHERE reputation > 0").fetchone()["c"]
    
    conn.close()
    return render_template(
        "leaderboard.html",
        top_helpers=top_helpers,
        total_reclaimed=total_reclaimed,
        total_reports=total_reports,
        total_helpers=total_helpers
    )


@app.route("/qr-tags")
def qr_tags():
    return render_template("qr_tags.html")


@app.route("/item/<item_type>/<int:item_id>/flyer")
def item_flyer(item_type, item_id):
    if item_type not in ("lost", "found"):
        flash("Invalid item type for flyer.", "danger")
        return redirect(url_for("index"))
    table = "lost_items" if item_type == "lost" else "found_items"
    conn = get_db_connection()
    item = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    owner = None
    if item and item["user_id"]:
        owner = conn.execute("SELECT name, email, reputation FROM users WHERE id = ?", (item["user_id"],)).fetchone()
    conn.close()
    if not item:
        flash("Report not found.", "warning")
        return redirect(url_for("index"))
    
    item_url = url_for("item_details", item_type=item_type, item_id=item_id, _external=True)
    return render_template("flyer.html", item=item, item_type=item_type, owner=owner, item_url=item_url)


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")



@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# --------------------
# AUTHENTICATION
# --------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name:
            error = "Please enter your full name."
        elif not email or "@" not in email:
            error = "Please provide a valid email address."
        elif len(password) < 6:
            error = "Password must be at least 6 characters long."
        else:
            conn = get_db_connection()
            exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if exists:
                error = "This email is already registered. Please sign in."
                conn.close()
            else:
                pw_hash = generate_password_hash(password)
                date_joined = datetime.now().strftime("%d %b %Y")
                cur = conn.execute(
                    "INSERT INTO users (name, email, password_hash, date_joined, is_admin, reputation, reports_count, returned_count) VALUES (?, ?, ?, ?, 0, 0, 0, 0)",
                    (name, email, pw_hash, date_joined)
                )
                conn.commit()
                user_id = cur.lastrowid
                conn.close()
                session["user_id"] = user_id
                session["user_name"] = name
                session["user_email"] = email
                flash(f"Welcome to ReClaim, {name}! Your account has been created.", "success")
                return redirect(url_for("dashboard"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "Invalid email or password. Please try again."
        else:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]
            flash(f"Welcome back, {user['name']}!", "success")
            next_page = request.args.get("next")
            if next_page and next_page.startswith("/"):
                return redirect(next_page)
            return redirect(url_for("dashboard"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("index"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    error = None
    reset_link = None
    email_sent = False
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            error = "Please enter your email address."
        else:
            conn = get_db_connection()
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            conn.close()
            if not user:
                error = "No account found with this email address. Please check and try again."
            else:
                token = generate_reset_token(user["id"])
                reset_url = url_for("reset_password", token=token, _external=True)
                
                email_subject = "Password Reset Request — ReClaim"
                email_body = (
                    f"Hello {user['name']},\n\n"
                    f"We received a request to reset your password for your ReClaim account.\n"
                    f"Click the link below to set a new password:\n\n"
                    f"{reset_url}\n\n"
                    f"This link is valid for 1 hour.\n"
                    f"If you did not request this password reset, please ignore this email.\n\n"
                    f"— The ReClaim Team"
                )
                sent = send_email_if_configured(user["email"], email_subject, email_body)
                if sent:
                    email_sent = True
                    flash(f"A password reset link has been sent to {user['email']}.", "success")
                else:
                    reset_link = reset_url
                    flash("Password reset link generated! You can use the link below to set your new password.", "success")
    return render_template("forgot_password.html", error=error, reset_link=reset_link, email_sent=email_sent)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    user = validate_reset_token(token)
    if not user:
        return render_template("reset_password.html", invalid_token=True)
    
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(password) < 6:
            error = "Password must be at least 6 characters long."
        elif password != confirm_password:
            error = "Passwords do not match. Please try again."
        else:
            conn = get_db_connection()
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), user["id"])
            )
            conn.commit()
            conn.close()
            mark_token_used(token)
            create_notification(
                user["id"],
                "Password Reset Successful",
                "Your account password was updated successfully. If this wasn't you, contact support immediately.",
                "/profile"
            )
            flash("Your password has been reset successfully! You can now sign in with your new password.", "success")
            return redirect(url_for("login"))
    return render_template("reset_password.html", invalid_token=False, token=token, user_email=user["email"], error=error)



# --------------------
# USER PROFILE & NOTIFICATIONS
# --------------------
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, session["user_id"]))
            conn.commit()
            session["user_name"] = name
            flash("Your profile information has been updated.", "success")
            user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    
    # Recalculate accurate stats
    lost_count = conn.execute("SELECT COUNT(*) as c FROM lost_items WHERE user_id = ?", (session["user_id"],)).fetchone()["c"]
    found_count = conn.execute("SELECT COUNT(*) as c FROM found_items WHERE user_id = ?", (session["user_id"],)).fetchone()["c"]
    returned_count = conn.execute(
        "SELECT COUNT(*) as c FROM (SELECT id FROM lost_items WHERE user_id = ? AND status='Returned' UNION ALL SELECT id FROM found_items WHERE user_id = ? AND status='Returned')",
        (session["user_id"], session["user_id"])
    ).fetchone()["c"]

    stats = {
        "reports": lost_count + found_count,
        "lost_count": lost_count,
        "found_count": found_count,
        "returned": returned_count,
        "reputation": user["reputation"] if user["reputation"] is not None else 0,
        "joined": user["date_joined"]
    }
    conn.close()
    return render_template("profile.html", user=user, stats=stats)


@app.route("/notifications")
@login_required
def notifications():
    conn = get_db_connection()
    notes = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],)
    ).fetchall()
    conn.close()
    return render_template("notifications.html", notes=notes)


@app.route("/notifications/<int:note_id>/read", methods=["POST"])
@login_required
def mark_notification_read(note_id):
    conn = get_db_connection()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (note_id, session["user_id"]))
    conn.commit()
    conn.close()
    flash("Notification marked as read.", "info")
    return redirect(url_for("notifications"))


@app.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications_read():
    conn = get_db_connection()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (session["user_id"],))
    conn.commit()
    conn.close()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("notifications"))


# --------------------
# USER DASHBOARD
# --------------------
@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    conn = get_db_connection()
    lost_items = conn.execute("SELECT * FROM lost_items WHERE user_id = ? ORDER BY id DESC", (uid,)).fetchall()
    found_items = conn.execute("SELECT * FROM found_items WHERE user_id = ? ORDER BY id DESC", (uid,)).fetchall()
    
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    
    active_lost = sum(1 for item in lost_items if item["status"] == "Active")
    active_found = sum(1 for item in found_items if item["status"] == "Active")
    resolved_count = sum(1 for item in lost_items if item["status"] == "Returned") + sum(1 for item in found_items if item["status"] == "Returned")
    
    stats = {
        "active_lost": active_lost,
        "active_found": active_found,
        "resolved": resolved_count,
        "total": len(lost_items) + len(found_items),
        "reputation": user["reputation"] if user and user["reputation"] is not None else 0
    }
    conn.close()
    return render_template("dashboard.html", lost_items=lost_items, found_items=found_items, stats=stats)


# --------------------
# REPORT LOST / FOUND
# --------------------
@app.route("/add-lost", methods=["GET", "POST"])
@login_required
def add_lost():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        contact = request.form.get("contact", "").strip()
        category = request.form.get("category", "").strip()
        image = request.files.get("image")
        
        if not name or not description or not location or not contact or not category:
            flash("Please fill in all required fields.", "danger")
            return render_template("add_lost.html")

        image_filename = None
        if image and image.filename:
            if not allowed_file(image.filename):
                flash("Invalid image format. Allowed formats: PNG, JPG, JPEG, WEBP.", "danger")
                return render_template("add_lost.html")
            orig = secure_filename(image.filename)
            ext = orig.rsplit(".", 1)[1].lower()
            image_filename = f"{uuid.uuid4().hex}.{ext}"
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))

        date_reported = datetime.now().strftime("%d %b %Y")
        lat_val = request.form.get("latitude")
        lng_val = request.form.get("longitude")
        latitude = float(lat_val) if lat_val and lat_val.strip() else None
        longitude = float(lng_val) if lng_val and lng_val.strip() else None

        conn = get_db_connection()
        cur = conn.execute("""INSERT INTO lost_items
            (name, description, location, contact, category, date_reported, status, image, user_id, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, description, location, contact, category, date_reported, "Active", image_filename, session["user_id"], latitude, longitude))
        conn.commit()
        conn.execute("UPDATE users SET reports_count = reports_count + 1 WHERE id = ?", (session["user_id"],))
        conn.commit()
        
        new_item = {"name": name, "description": description, "category": category, "location": location}
        conn.close()

        notify_matches_on_create(new_item, "lost")
        flash("Your lost item report has been published! We'll notify you if any match is found.", "success")
        return redirect(url_for("dashboard"))
    return render_template("add_lost.html")


@app.route("/add-found", methods=["GET", "POST"])
@login_required
def add_found():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        contact = request.form.get("contact", "").strip()
        category = request.form.get("category", "").strip()
        image = request.files.get("image")

        if not name or not description or not location or not contact or not category:
            flash("Please fill in all required fields.", "danger")
            return render_template("add_found.html")

        image_filename = None
        if image and image.filename:
            if not allowed_file(image.filename):
                flash("Invalid image format. Allowed formats: PNG, JPG, JPEG, WEBP.", "danger")
                return render_template("add_found.html")
            orig = secure_filename(image.filename)
            ext = orig.rsplit(".", 1)[1].lower()
            image_filename = f"{uuid.uuid4().hex}.{ext}"
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))

        date_reported = datetime.now().strftime("%d %b %Y")
        verification_question = request.form.get("verification_question", "").strip()
        lat_val = request.form.get("latitude")
        lng_val = request.form.get("longitude")
        latitude = float(lat_val) if lat_val and lat_val.strip() else None
        longitude = float(lng_val) if lng_val and lng_val.strip() else None

        conn = get_db_connection()
        cur = conn.execute("""INSERT INTO found_items
            (name, description, location, contact, category, date_reported, status, image, user_id, verification_question, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, description, location, contact, category, date_reported, "Active", image_filename, session["user_id"], verification_question, latitude, longitude))
        conn.commit()
        conn.execute("UPDATE users SET reports_count = reports_count + 1 WHERE id = ?", (session["user_id"],))
        conn.commit()
        
        new_item = {"name": name, "description": description, "category": category, "location": location}
        conn.close()

        notify_matches_on_create(new_item, "found")
        flash("Thank you for helping out! Your found item report has been published.", "success")
        return redirect(url_for("dashboard"))
    return render_template("add_found.html")


# --------------------
# EDIT & DELETE REPORTS
# --------------------
@app.route("/item/lost/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_lost(item_id):
    conn = get_db_connection()
    item = conn.execute("SELECT * FROM lost_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        flash("Item report not found.", "danger")
        return redirect(url_for("dashboard"))
    if item["user_id"] != session["user_id"]:
        conn.close()
        flash("You are not authorized to edit this report.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        contact = request.form.get("contact", "").strip()
        category = request.form.get("category", "").strip()
        remove_image = request.form.get("remove_image")
        new_image = request.files.get("image")
        image_filename = item["image"]

        lat_val = request.form.get("latitude")
        lng_val = request.form.get("longitude")
        latitude = float(lat_val) if lat_val and lat_val.strip() else item["latitude"]
        longitude = float(lng_val) if lng_val and lng_val.strip() else item["longitude"]

        if remove_image == "on":
            delete_image_file(image_filename)
            image_filename = None
        if new_image and new_image.filename:
            if not allowed_file(new_image.filename):
                conn.close()
                flash("Invalid image format.", "danger")
                return render_template("edit_lost.html", item=item)
            delete_image_file(image_filename)
            orig = secure_filename(new_image.filename)
            ext = orig.rsplit(".", 1)[1].lower()
            image_filename = f"{uuid.uuid4().hex}.{ext}"
            new_image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))

        conn.execute("""UPDATE lost_items SET name=?, description=?, location=?, contact=?, category=?, image=?, latitude=?, longitude=? WHERE id=?""",
                     (name, description, location, contact, category, image_filename, latitude, longitude, item_id))
        conn.commit()
        conn.close()
        flash("Report updated successfully.", "success")
        return redirect(url_for("dashboard"))

    conn.close()
    return render_template("edit_lost.html", item=item)


@app.route("/item/lost/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_lost(item_id):
    conn = get_db_connection()
    item = conn.execute("SELECT * FROM lost_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        flash("Item not found.", "danger")
        return redirect(url_for("dashboard"))
    if item["user_id"] != session["user_id"]:
        conn.close()
        flash("Unauthorized action.", "danger")
        return redirect(url_for("dashboard"))

    delete_image_file(item["image"])
    conn.execute("DELETE FROM lost_items WHERE id = ?", (item_id,))
    conn.execute("UPDATE users SET reports_count = MAX(0, reports_count - 1) WHERE id = ?", (session["user_id"],))
    conn.commit()
    conn.close()
    flash("Report deleted successfully.", "info")
    return redirect(url_for("dashboard"))


@app.route("/item/found/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_found(item_id):
    conn = get_db_connection()
    item = conn.execute("SELECT * FROM found_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        flash("Item report not found.", "danger")
        return redirect(url_for("dashboard"))
    if item["user_id"] != session["user_id"]:
        conn.close()
        flash("You are not authorized to edit this report.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        contact = request.form.get("contact", "").strip()
        category = request.form.get("category", "").strip()
        verification_question = request.form.get("verification_question", "").strip()
        remove_image = request.form.get("remove_image")
        new_image = request.files.get("image")
        image_filename = item["image"]

        lat_val = request.form.get("latitude")
        lng_val = request.form.get("longitude")
        latitude = float(lat_val) if lat_val and lat_val.strip() else item["latitude"]
        longitude = float(lng_val) if lng_val and lng_val.strip() else item["longitude"]

        if remove_image == "on":
            delete_image_file(image_filename)
            image_filename = None
        if new_image and new_image.filename:
            if not allowed_file(new_image.filename):
                conn.close()
                flash("Invalid image format.", "danger")
                return render_template("edit_found.html", item=item)
            delete_image_file(image_filename)
            orig = secure_filename(new_image.filename)
            ext = orig.rsplit(".", 1)[1].lower()
            image_filename = f"{uuid.uuid4().hex}.{ext}"
            new_image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))

        conn.execute("""UPDATE found_items SET name=?, description=?, location=?, contact=?, category=?, image=?, verification_question=?, latitude=?, longitude=? WHERE id=?""",
                     (name, description, location, contact, category, image_filename, verification_question, latitude, longitude, item_id))
        conn.commit()
        conn.close()
        flash("Report updated successfully.", "success")
        return redirect(url_for("dashboard"))

    conn.close()
    return render_template("edit_found.html", item=item)


# --------------------
# MAP EXPLORER API
# --------------------
CAMPUS_PRESETS = {
    "library": (40.7130, -74.0062),
    "cafeteria": (40.7122, -74.0055),
    "student center": (40.7125, -74.0058),
    "lab": (40.7135, -74.0048),
    "engineering": (40.7138, -74.0050),
    "science": (40.7142, -74.0065),
    "gym": (40.7118, -74.0072),
    "sports": (40.7115, -74.0075),
    "auditorium": (40.7129, -74.0070),
    "parking": (40.7110, -74.0060),
    "hostel": (40.7145, -74.0080),
    "dorm": (40.7146, -74.0078)
}

@app.route("/api/map/items")
def api_map_items():
    item_type = request.args.get("type", "all").strip()  # all, lost, found
    category = request.args.get("category", "all").strip()

    conn = get_db_connection()
    lost_items = conn.execute("SELECT * FROM lost_items WHERE status = 'Active' ORDER BY id DESC").fetchall()
    found_items = conn.execute("SELECT * FROM found_items WHERE status = 'Active' ORDER BY id DESC").fetchall()
    conn.close()

    map_items = []

    def get_coords(item, index, itype):
        if "latitude" in item.keys() and item["latitude"] is not None and item["longitude"] is not None:
            return float(item["latitude"]), float(item["longitude"])
        loc_lower = (item["location"] or "").lower()
        for kw, coords in CAMPUS_PRESETS.items():
            if kw in loc_lower:
                jitter_lat = (index % 5 - 2) * 0.00015
                jitter_lng = ((index * 2) % 5 - 2) * 0.00015
                return coords[0] + jitter_lat, coords[1] + jitter_lng
        base_lat = 40.7128 + (0.0004 if itype == "lost" else -0.0004)
        base_lng = -74.0060 + (0.0003 if itype == "lost" else -0.0003)
        jitter_lat = (index % 7 - 3) * 0.00035
        jitter_lng = ((index * 3) % 7 - 3) * 0.00035
        return base_lat + jitter_lat, base_lng + jitter_lng

    if item_type in ("all", "lost"):
        for i, item in enumerate(lost_items):
            if category != "all" and item["category"].lower() != category.lower():
                continue
            lat, lng = get_coords(item, i, "lost")
            map_items.append({
                "id": item["id"],
                "type": "lost",
                "name": item["name"],
                "category": item["category"],
                "location": item["location"],
                "date": item["date_reported"],
                "status": item["status"],
                "image": url_for("uploaded_file", filename=item["image"]) if item["image"] else None,
                "lat": lat,
                "lng": lng,
                "url": url_for("item_details", item_type="lost", item_id=item["id"])
            })

    if item_type in ("all", "found"):
        for i, item in enumerate(found_items):
            if category != "all" and item["category"].lower() != category.lower():
                continue
            lat, lng = get_coords(item, i, "found")
            map_items.append({
                "id": item["id"],
                "type": "found",
                "name": item["name"],
                "category": item["category"],
                "location": item["location"],
                "date": item["date_reported"],
                "status": item["status"],
                "image": url_for("uploaded_file", filename=item["image"]) if item["image"] else None,
                "lat": lat,
                "lng": lng,
                "url": url_for("item_details", item_type="found", item_id=item["id"])
            })

    return jsonify({"items": map_items, "count": len(map_items)})


# --------------------
# DIRECT IN-APP MESSAGING
# --------------------
@app.route("/messages")
@login_required
def messages_inbox():
    uid = session["user_id"]
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT 
            m.*,
            CASE WHEN m.sender_id = ? THEN m.receiver_id ELSE m.sender_id END as other_user_id
        FROM messages m
        WHERE m.sender_id = ? OR m.receiver_id = ?
        ORDER BY m.id DESC
    """, (uid, uid, uid)).fetchall()
    
    threads_dict = {}
    for r in rows:
        key = (r["item_type"], r["item_id"], r["other_user_id"])
        if key not in threads_dict:
            table = "lost_items" if r["item_type"] == "lost" else "found_items"
            item = conn.execute(f"SELECT id, name, category, image, location, status FROM {table} WHERE id = ?", (r["item_id"],)).fetchone()
            other_user = conn.execute("SELECT id, name, email, reputation FROM users WHERE id = ?", (r["other_user_id"],)).fetchone()
            
            unread_c = conn.execute("""
                SELECT COUNT(*) as c FROM messages 
                WHERE item_type = ? AND item_id = ? AND sender_id = ? AND receiver_id = ? AND is_read = 0
            """, (r["item_type"], r["item_id"], r["other_user_id"], uid)).fetchone()["c"]

            if item and other_user:
                threads_dict[key] = {
                    "item": item,
                    "item_type": r["item_type"],
                    "other_user": other_user,
                    "last_message": r["message"],
                    "last_timestamp": r["timestamp"],
                    "last_sender_id": r["sender_id"],
                    "unread_count": unread_c
                }

    conn.close()
    threads = list(threads_dict.values())
    return render_template("messages_inbox.html", threads=threads)


@app.route("/messages/<item_type>/<int:item_id>/<int:other_user_id>")
@login_required
def chat_thread(item_type, item_id, other_user_id):
    uid = session["user_id"]
    if uid == other_user_id:
        flash("You cannot start a chat with yourself.", "warning")
        return redirect(url_for("messages_inbox"))

    if item_type not in ("lost", "found"):
        return redirect(url_for("messages_inbox"))

    table = "lost_items" if item_type == "lost" else "found_items"
    conn = get_db_connection()
    item = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    other_user = conn.execute("SELECT id, name, email, reputation, date_joined FROM users WHERE id = ?", (other_user_id,)).fetchone()
    
    if not item or not other_user:
        conn.close()
        flash("Conversation item or user not found.", "danger")
        return redirect(url_for("messages_inbox"))

    # Mark incoming messages as read
    conn.execute("""
        UPDATE messages SET is_read = 1 
        WHERE item_type = ? AND item_id = ? AND sender_id = ? AND receiver_id = ?
    """, (item_type, item_id, other_user_id, uid))
    conn.commit()

    thread_messages = conn.execute("""
        SELECT * FROM messages 
        WHERE item_type = ? AND item_id = ? AND (
            (sender_id = ? AND receiver_id = ?) OR
            (sender_id = ? AND receiver_id = ?)
        )
        ORDER BY id ASC
    """, (item_type, item_id, uid, other_user_id, other_user_id, uid)).fetchall()

    is_owner = (item["user_id"] == uid)
    conn.close()

    return render_template(
        "chat_thread.html",
        item=item,
        item_type=item_type,
        other_user=other_user,
        messages=thread_messages,
        is_owner=is_owner
    )


@app.route("/api/messages/<item_type>/<int:item_id>/<int:other_user_id>/send", methods=["POST"])
@login_required
def api_send_message(item_type, item_id, other_user_id):
    uid = session["user_id"]
    text = request.form.get("message", "").strip()
    if not text:
        return jsonify({"success": False, "error": "Message cannot be empty."}), 400

    table = "lost_items" if item_type == "lost" else "found_items"
    conn = get_db_connection()
    item = conn.execute(f"SELECT name FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        return jsonify({"success": False, "error": "Item not found."}), 404

    timestamp = datetime.now().strftime("%d %b %H:%M")
    cur = conn.execute("""
        INSERT INTO messages (item_id, item_type, sender_id, receiver_id, message, timestamp, is_read)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (item_id, item_type, uid, other_user_id, text, timestamp))
    msg_id = cur.lastrowid
    conn.commit()

    # Create notification for recipient
    sender_name = session.get("user_name", "A community member")
    title = f"💬 New message about {item['name']}"
    body = f"{sender_name}: \"{text[:60]}{'...' if len(text)>60 else ''}\""
    link = f"/messages/{item_type}/{item_id}/{uid}"
    create_notification(other_user_id, title, body, link)
    
    conn.close()
    return jsonify({
        "success": True,
        "message": {
            "id": msg_id,
            "sender_id": uid,
            "message": text,
            "timestamp": timestamp,
            "is_self": True
        }
    })


@app.route("/api/messages/<item_type>/<int:item_id>/<int:other_user_id>/poll")
@login_required
def api_poll_messages(item_type, item_id, other_user_id):
    uid = session["user_id"]
    after_id = request.args.get("after_id", 0, type=int)

    conn = get_db_connection()
    conn.execute("""
        UPDATE messages SET is_read = 1 
        WHERE item_type = ? AND item_id = ? AND sender_id = ? AND receiver_id = ? AND id > ?
    """, (item_type, item_id, other_user_id, uid, after_id))
    conn.commit()

    new_msgs = conn.execute("""
        SELECT * FROM messages 
        WHERE item_type = ? AND item_id = ? AND (
            (sender_id = ? AND receiver_id = ?) OR
            (sender_id = ? AND receiver_id = ?)
        ) AND id > ?
        ORDER BY id ASC
    """, (item_type, item_id, uid, other_user_id, other_user_id, uid, after_id)).fetchall()
    conn.close()

    formatted = []
    for m in new_msgs:
        formatted.append({
            "id": m["id"],
            "sender_id": m["sender_id"],
            "message": m["message"],
            "timestamp": m["timestamp"],
            "is_self": (m["sender_id"] == uid)
        })

    return jsonify({"messages": formatted, "count": len(formatted)})


@app.route("/item/<item_type>/<int:item_id>/chat")
@login_required
def item_start_chat(item_type, item_id):
    table = "lost_items" if item_type == "lost" else "found_items"
    conn = get_db_connection()
    item = conn.execute(f"SELECT user_id FROM {table} WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if not item or not item["user_id"]:
        flash("Unable to start a message thread for this item.", "warning")
        return redirect(url_for("item_details", item_type=item_type, item_id=item_id))
    
    if item["user_id"] == session["user_id"]:
        flash("You are the owner of this report. You can view all incoming messages in your inbox.", "info")
        return redirect(url_for("messages_inbox"))

    return redirect(url_for("chat_thread", item_type=item_type, item_id=item_id, other_user_id=item["user_id"]))


@app.route("/item/found/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_found(item_id):
    conn = get_db_connection()
    item = conn.execute("SELECT * FROM found_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        flash("Item not found.", "danger")
        return redirect(url_for("dashboard"))
    if item["user_id"] != session["user_id"]:
        conn.close()
        flash("Unauthorized action.", "danger")
        return redirect(url_for("dashboard"))

    delete_image_file(item["image"])
    conn.execute("DELETE FROM found_items WHERE id = ?", (item_id,))
    conn.execute("UPDATE users SET reports_count = MAX(0, reports_count - 1) WHERE id = ?", (session["user_id"],))
    conn.commit()
    conn.close()
    flash("Report deleted successfully.", "info")
    return redirect(url_for("dashboard"))


# --------------------
# ITEM DETAILS & MATCHES
# --------------------
@app.route("/item/<item_type>/<int:item_id>")
def item_details(item_type, item_id):
    if item_type not in ("lost", "found"):
        flash("Invalid item type.", "danger")
        return redirect(url_for("index"))
    table = "lost_items" if item_type == "lost" else "found_items"
    conn = get_db_connection()
    item = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    
    if not item:
        conn.close()
        flash("Report not found or has been removed.", "warning")
        return redirect(url_for("index"))
        
    matches = find_matches(item, item_type)
    
    # Get owner info if available
    owner = None
    if item["user_id"]:
        owner = conn.execute("SELECT name, reputation, date_joined FROM users WHERE id = ?", (item["user_id"],)).fetchone()

    uid = session.get("user_id")
    is_owner = (bool(item["user_id"]) and bool(uid) and item["user_id"] == uid)
    
    # User's submitted claim on this item (if any)
    user_claim = None
    if uid and not is_owner:
        user_claim = conn.execute(
            "SELECT * FROM claims WHERE item_id = ? AND item_type = ? AND claimant_id = ? ORDER BY id DESC LIMIT 1",
            (item_id, item_type, uid)
        ).fetchone()

    # If viewer is the finder, get all received claims
    item_claims = []
    if is_owner:
        item_claims = conn.execute("""
            SELECT c.*, u.name as claimant_name, u.email as claimant_email, u.reputation as claimant_reputation
            FROM claims c
            JOIN users u ON c.claimant_id = u.id
            WHERE c.item_id = ? AND c.item_type = ?
            ORDER BY c.id DESC
        """, (item_id, item_type)).fetchall()

    # Determine if contact info is locked behind verification question
    has_question = bool(
        item_type == "found" and 
        "verification_question" in item.keys() and 
        item["verification_question"] and 
        item["verification_question"].strip()
    )
    
    # Is contact locked for the current viewer?
    is_contact_locked = False
    if has_question:
        if not is_owner and not session.get("is_admin_user"):
            if not user_claim or user_claim["status"] != "Approved":
                is_contact_locked = True

    conn.close()
    return render_template(
        "item.html",
        item=item,
        item_type=item_type,
        matches=matches,
        is_owner=is_owner,
        owner=owner,
        user_claim=user_claim,
        item_claims=item_claims,
        has_question=has_question,
        is_contact_locked=is_contact_locked
    )


@app.route("/item/<item_type>/<int:item_id>/claim", methods=["POST"])
@login_required
def submit_claim(item_type, item_id):
    if item_type not in ("lost", "found"):
        return redirect(url_for("index"))
    answer = request.form.get("answer", "").strip()
    if not answer:
        flash("Please provide your answer to submit an ownership claim.", "danger")
        return redirect(url_for("item_details", item_type=item_type, item_id=item_id))
    
    table = "lost_items" if item_type == "lost" else "found_items"
    conn = get_db_connection()
    item = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        flash("Item not found.", "danger")
        return redirect(url_for("index"))
    
    if item["user_id"] == session["user_id"]:
        conn.close()
        flash("You cannot claim your own reported item.", "warning")
        return redirect(url_for("item_details", item_type=item_type, item_id=item_id))

    date_submitted = datetime.now().strftime("%d %b %Y %H:%M")
    question = item["verification_question"] if "verification_question" in item.keys() else ""
    finder_id = item["user_id"] if item["user_id"] else 0

    existing = conn.execute(
        "SELECT * FROM claims WHERE item_id = ? AND item_type = ? AND claimant_id = ?",
        (item_id, item_type, session["user_id"])
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE claims SET answer = ?, status = 'Pending', date_submitted = ? WHERE id = ?
        """, (answer, date_submitted, existing["id"]))
    else:
        conn.execute("""
            INSERT INTO claims (item_id, item_type, claimant_id, finder_id, question, answer, status, date_submitted)
            VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (item_id, item_type, session["user_id"], finder_id, question, answer, date_submitted))
    conn.commit()

    # Notify finder
    if finder_id:
        claimant_name = session.get("user_name", "A community member")
        title = f"New Claim for {item['name']}"
        msg = f"{claimant_name} submitted an ownership verification answer for your found item '{item['name']}'. Please review their answer."
        link = f"/item/{item_type}/{item_id}"
        create_notification(finder_id, title, msg, link)
        finder_user = conn.execute("SELECT email FROM users WHERE id = ?", (finder_id,)).fetchone()
        if finder_user:
            send_email_if_configured(finder_user["email"], title, msg + f"\n\nReview claim here: {link}")

    conn.close()
    flash("✅ Your ownership claim has been submitted to the finder for review!", "success")
    return redirect(url_for("item_details", item_type=item_type, item_id=item_id))


@app.route("/claim/<int:claim_id>/approve", methods=["POST"])
@login_required
def approve_claim(claim_id):
    conn = get_db_connection()
    claim = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if not claim or claim["finder_id"] != session["user_id"]:
        conn.close()
        flash("Unauthorized or invalid claim.", "danger")
        return redirect(url_for("dashboard"))

    table = "lost_items" if claim["item_type"] == "lost" else "found_items"
    item = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (claim["item_id"],)).fetchone()
    item_name = item["name"] if item else "item"

    date_reviewed = datetime.now().strftime("%d %b %Y %H:%M")
    conn.execute("UPDATE claims SET status = 'Approved', date_reviewed = ? WHERE id = ?", (date_reviewed, claim_id))
    conn.commit()

    # Notify claimant
    title = "🎉 Ownership Claim Approved!"
    msg = f"Good news! Your ownership claim for '{item_name}' was verified and approved by the finder. You can now view their direct contact information."
    link = f"/item/{claim['item_type']}/{claim['item_id']}"
    create_notification(claim["claimant_id"], title, msg, link)
    claimant_user = conn.execute("SELECT email FROM users WHERE id = ?", (claim["claimant_id"],)).fetchone()
    if claimant_user:
        send_email_if_configured(claimant_user["email"], title, msg + f"\n\nView details: {link}")

    conn.close()
    flash("🎉 Claim approved! Contact information has been unlocked for the verified claimant.", "success")
    return redirect(url_for("item_details", item_type=claim["item_type"], item_id=claim["item_id"]))


@app.route("/claim/<int:claim_id>/decline", methods=["POST"])
@login_required
def decline_claim(claim_id):
    conn = get_db_connection()
    claim = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if not claim or claim["finder_id"] != session["user_id"]:
        conn.close()
        flash("Unauthorized or invalid claim.", "danger")
        return redirect(url_for("dashboard"))

    table = "lost_items" if claim["item_type"] == "lost" else "found_items"
    item = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (claim["item_id"],)).fetchone()
    item_name = item["name"] if item else "item"

    date_reviewed = datetime.now().strftime("%d %b %Y %H:%M")
    conn.execute("UPDATE claims SET status = 'Declined', date_reviewed = ? WHERE id = ?", (date_reviewed, claim_id))
    conn.commit()

    # Notify claimant
    title = "Ownership Claim Declined"
    msg = f"The finder reviewed your answer for '{item_name}' and was unable to verify ownership at this time."
    link = f"/item/{claim['item_type']}/{claim['item_id']}"
    create_notification(claim["claimant_id"], title, msg, link)

    conn.close()
    flash("Claim has been declined.", "info")
    return redirect(url_for("item_details", item_type=claim["item_type"], item_id=claim["item_id"]))


@app.route("/item/<item_type>/<int:item_id>/flag", methods=["POST"])
@login_required
def flag_item(item_type, item_id):
    if item_type not in ("lost", "found"):
        return redirect(url_for("index"))
    reason = request.form.get("reason", "Suspicious / Spam").strip()
    details = request.form.get("details", "").strip()
    date_reported = datetime.now().strftime("%d %b %Y %H:%M")

    conn = get_db_connection()
    conn.execute("""
        INSERT INTO item_flags (item_id, item_type, reporter_id, reason, details, date_reported, status)
        VALUES (?, ?, ?, ?, ?, ?, 'Open')
    """, (item_id, item_type, session["user_id"], reason, details, date_reported))
    conn.commit()
    conn.close()
    flash("Thank you! This listing has been flagged for moderation review.", "info")
    return redirect(url_for("item_details", item_type=item_type, item_id=item_id))


@app.route("/admin/flag/<int:flag_id>/dismiss", methods=["POST"])
@admin_required
def admin_dismiss_flag(flag_id):
    conn = get_db_connection()
    conn.execute("UPDATE item_flags SET status = 'Dismissed' WHERE id = ?", (flag_id,))
    conn.commit()
    conn.close()
    flash(f"Flag #{flag_id} dismissed.", "info")
    return redirect(url_for("admin_index"))


@app.route("/admin/flag/<int:flag_id>/delete_item", methods=["POST"])
@admin_required
def admin_delete_flagged_item(flag_id):
    conn = get_db_connection()
    flag = conn.execute("SELECT * FROM item_flags WHERE id = ?", (flag_id,)).fetchone()
    if flag:
        table = "lost_items" if flag["item_type"] == "lost" else "found_items"
        r = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (flag["item_id"],)).fetchone()
        if r:
            delete_image_file(r["image"])
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (flag["item_id"],))
        conn.execute("UPDATE item_flags SET status = 'Resolved' WHERE id = ?", (flag_id,))
        conn.commit()
        flash(f"Flag #{flag_id} resolved: Listing #{flag['item_id']} has been deleted.", "success")
    conn.close()
    return redirect(url_for("admin_index"))


@app.route("/item/<item_type>/<int:item_id>/returned", methods=["POST"])
@login_required
def mark_returned(item_type, item_id):
    if item_type not in ("lost", "found"):
        return redirect(url_for("index"))
    table = "lost_items" if item_type == "lost" else "found_items"
    conn = get_db_connection()
    item = conn.execute(f"SELECT user_id, status FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        flash("Report not found.", "danger")
        return redirect(url_for("dashboard"))
    if item["user_id"] != session["user_id"]:
        conn.close()
        flash("Only the report owner can mark it as returned.", "danger")
        return redirect(url_for("item_details", item_type=item_type, item_id=item_id))

    if item["status"] != "Returned":
        conn.execute(f"UPDATE {table} SET status = 'Returned' WHERE id = ?", (item_id,))
        conn.execute("UPDATE users SET returned_count = returned_count + 1, reputation = reputation + 15 WHERE id = ?", (session["user_id"],))
        conn.commit()
        flash("🎉 Great news! The item has been marked as returned and 15 reputation points were awarded!", "success")
    conn.close()
    return redirect(url_for("item_details", item_type=item_type, item_id=item_id))


# --------------------
# ADMIN CONSOLE
# --------------------
@app.route("/admin")
@admin_required
def admin_index():
    conn = get_db_connection()
    total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    total_lost = conn.execute("SELECT COUNT(*) as c FROM lost_items").fetchone()["c"]
    total_found = conn.execute("SELECT COUNT(*) as c FROM found_items").fetchone()["c"]
    total_resolved = conn.execute(
        "SELECT COUNT(*) as c FROM (SELECT id FROM lost_items WHERE status='Returned' UNION ALL SELECT id FROM found_items WHERE status='Returned')"
    ).fetchone()["c"]
    
    recent_lost = conn.execute("SELECT * FROM lost_items ORDER BY id DESC LIMIT 5").fetchall()
    recent_found = conn.execute("SELECT * FROM found_items ORDER BY id DESC LIMIT 5").fetchall()
    recent_users = conn.execute("SELECT * FROM users ORDER BY id DESC LIMIT 5").fetchall()
    open_flags = conn.execute("""
        SELECT f.*, u.name as reporter_name 
        FROM item_flags f 
        JOIN users u ON f.reporter_id = u.id 
        WHERE f.status = 'Open' 
        ORDER BY f.id DESC
    """).fetchall()
    conn.close()

    stats = {
        "users": total_users,
        "lost": total_lost,
        "found": total_found,
        "resolved": total_resolved,
        "flags": len(open_flags)
    }
    return render_template("admin.html", stats=stats, recent_lost=recent_lost, recent_found=recent_found, recent_users=recent_users, open_flags=open_flags)


@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_db_connection()
    users = conn.execute("SELECT id, name, email, is_admin, reputation, reports_count, returned_count, date_joined FROM users ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin_users.html", users=users)


@app.route("/admin/reports")
@admin_required
def admin_reports():
    conn = get_db_connection()
    lost = conn.execute("SELECT * FROM lost_items ORDER BY id DESC").fetchall()
    found = conn.execute("SELECT * FROM found_items ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin_reports.html", lost=lost, found=found)


@app.route("/admin/user/<int:user_id>/toggle_admin", methods=["POST"])
@admin_required
def admin_toggle_admin(user_id):
    conn = get_db_connection()
    u = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if u:
        new_val = 0 if u["is_admin"] == 1 else 1
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_val, user_id))
        conn.commit()
        flash(f"User #{user_id} admin privileges {'granted' if new_val==1 else 'revoked'}.", "info")
    conn.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/report/<type>/<int:report_id>/delete", methods=["POST"])
@admin_required
def admin_delete_report(type, report_id):
    if type not in ("lost", "found"):
        return redirect(url_for("admin_reports"))
    table = "lost_items" if type == "lost" else "found_items"
    conn = get_db_connection()
    r = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (report_id,)).fetchone()
    if r:
        delete_image_file(r["image"])
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (report_id,))
        conn.commit()
        flash(f"{type.capitalize()} report #{report_id} deleted by admin.", "info")
    conn.close()
    return redirect(url_for("admin_reports"))


# --------------------
# ERROR HANDLERS
# --------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template("index.html", error_message="Page not found. Redirected to home."), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template("index.html", error_message="An internal error occurred. Please try again."), 500


# --------------------
# APPLICATION ENTRYPOINT
# --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    app.run(debug=debug_mode, host="0.0.0.0", port=port)