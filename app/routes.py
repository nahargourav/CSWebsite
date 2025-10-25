# Standard library
import os
import sys
import time
import json
import uuid
import re
import logging
from datetime import datetime, timedelta
from collections import OrderedDict
import html as _html
import urllib.parse
# Environment helpers
from dotenv import load_dotenv
import razorpay as rz_module
from ipaddress import ip_address
# Third-party / Flask
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    current_app, session, make_response, jsonify, send_file
)
from user_agents import parse as ua_parse
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from markupsafe import escape, Markup


# R2

import boto3
from botocore.exceptions import ClientError




# OAuth / auth helpers
from flask_dance.contrib.google import make_google_blueprint, google
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Database

from app.db.db_config import get_db

# Postgres compatibility shim for routes.py
# Insert this block in routes.py where mysql.connector was originally imported

import sys
import types
try:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import IntegrityError as PGIntegrityError, DatabaseError as PGDatabaseError
except Exception:
    psycopg2 = None
    psycopg2_extras = None

# Provide a fake mysql.connector module so existing except mysql.connector.Error
# and except mysql.connector.IntegrityError continue to work without changing many lines.
mysql_module = types.ModuleType('mysql')
mysql_connector_module = types.ModuleType('mysql.connector')
# Map common MySQL exception names to psycopg2 ones (or fall back to Exception)
mysql_connector_module.Error = PGDatabaseError if psycopg2 is not None else Exception
mysql_connector_module.IntegrityError = PGIntegrityError if psycopg2 is not None else Exception
mysql_module.connector = mysql_connector_module
sys.modules['mysql'] = mysql_module
sys.modules['mysql.connector'] = mysql_connector_module

# Cursor/connection wrapper to emulate MySQL-style cursor(dictionary=True) and cursor.lastrowid
class _CursorWrapper:
    def __init__(self, cur, parent_conn):
        self._cur = cur
        self._parent_conn = parent_conn
        self._lastrowid = None

    def execute(self, sql, params=None):
        # execute the provided SQL
        result = self._cur.execute(sql, params)
        # If this looks like an INSERT, attempt to capture the last inserted id via PostgreSQL's LASTVAL()
        try:
            sql_str = (sql or '').strip().lower()
            if sql_str.startswith('insert'):
                # use a temporary cursor from the raw connection to fetch LASTVAL()
                tmp = self._parent_conn.cursor()
                try:
                    tmp.execute("SELECT LASTVAL()")
                    row = tmp.fetchone()
                    if row:
                        # row might be a tuple like (123,) or a dict-like if using RealDictCursor
                        if isinstance(row, (list, tuple)):
                            self._lastrowid = row[0]
                        elif isinstance(row, dict):
                            # RealDictCursor might return dict-like; take first value
                            self._lastrowid = next(iter(row.values()))
                        else:
                            self._lastrowid = row
                finally:
                    try:
                        tmp.close()
                    except Exception:
                        pass
        except Exception:
            # don't let this break normal flow
            pass
        return result

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()

    def close(self):
        try:
            return self._cur.close()
        except Exception:
            pass

    @property
    def lastrowid(self):
        return self._lastrowid


class _ConnWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, dictionary=False, *args, **kwargs):
        """
        Accepts:
          - dictionary=True  => use RealDictCursor when no explicit cursor_factory passed
          - cursor_factory=... => pass through to psycopg2 connection
          - arbitrary *args/**kwargs forwarded to underlying .cursor()
        """
        try:
            # Allow callers to pass 'cursor_factory' (psycopg2 style)
            cf = kwargs.pop('cursor_factory', None)

            # If dictionary requested and no explicit cursor_factory supplied, use RealDictCursor
            if dictionary and cf is None:
                cf = psycopg2.extras.RealDictCursor

            if cf is not None:
                # Pass the factory into the raw connection
                cur = self._conn.cursor(cursor_factory=cf)
            else:
                # No factory specified, forward other args/kwargs
                cur = self._conn.cursor(*args, **kwargs)

            return _CursorWrapper(cur, self._conn)
        except Exception:
            # Fallback to a plain cursor wrapper if anything goes wrong
            try:
                return _CursorWrapper(self._conn.cursor(), self._conn)
            except Exception:
                # as a last resort, re-raise so calling code sees the original error
                raise

    def __getattr__(self, name):
        return getattr(self._conn, name)


# Wrap the imported get_db so routes.py continues to call get_db() normally
_original_get_db = globals().get('get_db')
if _original_get_db:
    def get_db():
        conn = _original_get_db()
        try:
            # If psycopg2 connection, wrap for compatibility
            if psycopg2 is not None and hasattr(conn, 'cursor'):
                return _ConnWrapper(conn)
        except Exception:
            pass
        return conn
    # Replace the name in module globals
    globals()['get_db'] = get_db

# End of compatibility shim

# PDF / ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Frame, Image
)
from reportlab.lib.enums import TA_RIGHT, TA_LEFT
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics




# Load environment variables from project .env (if present)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=["profile", "email"],
    redirect_url="/google_callback"
)

main = Blueprint('main', __name__)

def nocache(view):
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
        return response
    no_cache.__name__ = view.__name__
    return no_cache

main.register_blueprint(google_bp, url_prefix="/login")


# r2 setup

# ---------- R2 / S3 client initialization (module-level) ----------
R2_ENDPOINT = os.environ.get("R2_ENDPOINT") or f"https://{os.environ.get('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com"
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.environ.get("R2_BUCKET")
R2_PUBLIC_BASE = os.environ.get("R2_PUBLIC_BASE")  # optional public base like https://pub-xxxx.r2.dev

# create boto3 client (module-level)
s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
)

# ---------- Helpers for R2 operations ----------

def upload_to_r2(file_storage, key):
    """
    Upload a werkzeug FileStorage to R2 and return a public URL.
    key: "products/{product_id}/main/filename.ext"
    """
    key = str(key).lstrip('/')

    try:
        file_storage.stream.seek(0)
    except Exception:
        pass

    content_type = getattr(file_storage, "content_type", None) or "application/octet-stream"
    extra_args = {"ContentType": content_type}

    try:
        s3.upload_fileobj(file_storage.stream, R2_BUCKET, key, ExtraArgs=extra_args)
    except ClientError as e:
        current_app.logger.exception("R2 upload failed for key=%s: %s", key, e)
        raise

    # construct public URL
    if R2_PUBLIC_BASE:
        return R2_PUBLIC_BASE.rstrip('/') + '/' + key
    if R2_ENDPOINT and R2_BUCKET:
        return f"{R2_ENDPOINT.rstrip('/')}/{R2_BUCKET}/{key}"
    return key  # last resort

def delete_from_r2(key):
    """
    Delete an object from R2 by key. Key must be the S3 key (no leading slash).
    Returns True if deleted (or not found), False if failure.
    """
    if not key:
        return True
    key = str(key).lstrip('/')
    try:
        s3.delete_object(Bucket=R2_BUCKET, Key=key)
        return True
    except ClientError as e:
        # If object not found or other error, log and return False
        current_app.logger.exception("R2 delete failed for key=%s: %s", key, e)
        return False

def _r2_key_from_public_url(url):
    """
    Given a public URL stored in DB, try to derive the R2 object key.
    Handles:
      - R2_PUBLIC_BASE + '/' + key
      - R2_ENDPOINT + '/' + BUCKET + '/' + key
      - raw key (already stored)
    Returns key (string) or None.
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()

    # If stored already as a bare key (no scheme)
    if not (url.startswith('http://') or url.startswith('https://')):
        return url.lstrip('/')

    try:
        # If public base is known and URL starts with it
        if R2_PUBLIC_BASE and url.startswith(R2_PUBLIC_BASE.rstrip('/')):
            key = url[len(R2_PUBLIC_BASE.rstrip('/')):].lstrip('/')
            return key

        # If endpoint + bucket form (endpoint may include scheme and host)
        if R2_ENDPOINT and R2_BUCKET:
            prefix = f"{R2_ENDPOINT.rstrip('/')}/{R2_BUCKET}/"
            if url.startswith(prefix):
                key = url[len(prefix):]
                return key

        # Last attempt: remove scheme+host and bucket if present
        # Example: https://.../<bucket>/products/... => extract after /<bucket>/
        # Parse path component
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.lstrip('/')  # e.g. "pub-xxx.r2.dev/products/1/main/..."
        # If bucket appears as first path segment:
        if path.startswith(f"{R2_BUCKET}/"):
            return path[len(R2_BUCKET)+1:]
        # If path contains 'products/' then return from that segment onward
        idx = path.find('products/')
        if idx != -1:
            return path[idx:]
    except Exception as e:
        current_app.logger.debug("Failed to parse R2 key from url=%s : %s", url, e)

    # Could not reliably compute key
    return None


@main.route('/')
def home():
    return render_template("customer/index.html")



@main.route("/google_callback")
def google_callback():
    if not google.authorized:
        return redirect(url_for("main.google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Failed to fetch user info from Google.", "danger")
        return redirect(url_for("main.login"))

    user_info = resp.json()
    email = user_info["email"]
    name = user_info.get("name", "Google User")

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT customer_id, name FROM customers WHERE email = %s", (email,))
        existing = cursor.fetchone()

        if existing:
            # Already registered → log them in
            session.clear()
            session["customer_id"] = existing[0]
            session["name"] = existing[1]
            flash("Logged in with Google!", "success")
            return redirect("/")

        else:
            # First time → redirect to set password page
            session["google_email"] = email
            session["google_name"] = name
            return redirect(url_for("main.set_password"))

    finally:
        cursor.close()
        conn.close()



@main.route("/set-password", methods=["GET", "POST"])
@nocache
def set_password():
    if "google_email" not in session:
        flash("Google verification required before setting password.", "warning")
        return redirect(url_for("main.register"))

    if request.method == "POST":
        password = request.form["password"]
        email = session["google_email"]
        name = session["google_name"]

        conn = get_db()
        cursor = conn.cursor()
        try:
            password_hash = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO customers (name, email, password_hash) VALUES (%s, %s, %s)",
                (name, email, password_hash)
            )
            conn.commit()

            # log them in
            session.clear()
            session["customer_id"] = cursor.lastrowid
            session["name"] = name

            flash("Registration successful! You are now logged in.", "success")
            return redirect("/")
        except Exception as e:
            flash(f"Error creating account: {e}", "danger")
        finally:
            cursor.close()
            conn.close()

    return render_template("customer/set_password.html")


# --------------------login--------------------
@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db()
        cursor = conn.cursor()

        try:
            # Check owners first
            cursor.execute("SELECT owner_id, name, password_hash FROM owners WHERE email = %s", (email,))
            owner = cursor.fetchone()
            if owner and check_password_hash(owner[2], password):
                session.clear()
                session['owner_id'] = owner[0]
                session['owner_name'] = owner[1]
                flash("Owner login successful!", "success")
                return redirect('/owner-index')

            # If not owner, check customers
            cursor.execute("SELECT customer_id, name, password_hash FROM customers WHERE email = %s", (email,))
            user = cursor.fetchone()
            if user and check_password_hash(user[2], password):
                session.clear()
                session['customer_id'] = user[0]
                session['name'] = user[1]
                flash("Login successful!", "success")
                return redirect('/')

            flash("Invalid email or password.", "danger")
            return redirect('/login')
        except mysql.connector.Error as err:
            flash(f"MySQL error: {err}", "danger")
            return redirect('/login')
        finally:
            cursor.close()
            conn.close()

    return render_template("customer/login.html")

@main.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect('/')

# --------------------register--------------------

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        conn = get_db()
        cursor = conn.cursor()

        try:
            password_hash = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO customers (name, email, password_hash) VALUES (%s, %s, %s)",
                (name, email, password_hash)
            )
            conn.commit()
            flash("Registration successful! Please login.", "success")
            return redirect('/login')

        except mysql.connector.IntegrityError:
            flash("Email already registered. Try logging in.", "warning")
        except mysql.connector.Error as err:
            flash(f"Database error: {err}", "danger")
        finally:
            cursor.close()
            conn.close()

    return render_template('customer/register.html')



@main.route('/collections/bestsellers')
def best_sellers():
    """
    Display top 50 most sold product variants (by order_items.quantity).
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Aggregate sold quantities from order_items, join product / variant details.
        # Use scalar subquery to pick a variant image if available, else product image.
        sql = """
        SELECT
          oi.variant_id,
          oi.product_id,
          COALESCE(p.name, '') AS product_name,
          p.category,
          COALESCE(p.short_description, '') AS short_description,
          COALESCE(p.description, '') AS description,
          COALESCE(p.rating_avg, 0.0) AS rating_avg,
          COALESCE(p.reviews_count, 0) AS reviews_count,
          COALESCE(pv.price, 0.00) AS price,
          pv.size,
          pv.color,
          pv.sku AS variant_sku,
          -- pick variant image if present; else pick a product-level image
          (
            SELECT path FROM product_images
            WHERE variant_id = oi.variant_id
            ORDER BY is_primary DESC, position ASC
            LIMIT 1
          ) AS variant_image,
          (
            SELECT path FROM product_images
            WHERE product_id = oi.product_id AND (variant_id IS NULL OR variant_id = 0)
            ORDER BY is_primary DESC, position ASC
            LIMIT 1
          ) AS product_image,
          SUM(oi.quantity)::bigint AS sold_qty
        FROM order_items oi
        LEFT JOIN product_variants pv ON pv.variant_id = oi.variant_id
        LEFT JOIN products p ON p.product_id = oi.product_id
        GROUP BY oi.variant_id, oi.product_id, p.name, p.category, p.short_description, p.description, p.rating_avg, p.reviews_count, pv.price, pv.size, pv.color, pv.sku, pv.variant_id, pv.sku, pv.size, pv.color, pv.price
        ORDER BY sold_qty DESC
        LIMIT 50
        """
        cur.execute(sql)
        rows = cur.fetchall()
        variants = []
        for r in rows:
            # Convert to plain dict and coerce values to safe JSON types
            idx = dict(r)
            # choose the image: variant_image prefer, else product_image, else None
            img = idx.get('variant_image') or idx.get('product_image') or None
            variants.append({
                'variant_id': int(idx.get('variant_id')) if idx.get('variant_id') is not None else None,
                'product_id': int(idx.get('product_id')) if idx.get('product_id') is not None else None,
                'title': idx.get('product_name') or '',
                'category': idx.get('category') or '',
                'short_description': idx.get('short_description') or '',
                'description': idx.get('description') or '',
                'rating_avg': float(idx.get('rating_avg') or 0.0),
                'reviews_count': int(idx.get('reviews_count') or 0),
                'price': float(idx.get('price') or 0.0),
                'size': idx.get('size') or '',
                'color': idx.get('color') or '',
                'variant_sku': idx.get('variant_sku') or '',
                'image': img,
            })

        # pass the list to the template
        return render_template('customer/best_sellers.html', variants=variants)
    except Exception as e:
        current_app.logger.exception("Failed to load best-sellers: %s", e)
        # render page with empty list rather than crash
        return render_template('customer/best_sellers.html', variants=[])
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


@main.route('/help/shipping')
def shipping():
    return render_template("customer/shipping.html")

@main.route('/help/returns')
def returns():
    return render_template("customer/returns.html")

@main.route('/help/faq')
def faq():
    return render_template("customer/faq.html")

@main.route('/contact')
def contact():
    return render_template("customer/contact.html")


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
@main.route('/contact/submit', methods=['POST'])
def contact_submit():
    """
    Accepts both JSON (AJAX) and form-encoded POSTs.
    Returns JSON when X-Requested-With == XMLHttpRequest or when Accept prefers JSON.
    Inserts a row into contact_messages using psycopg2 (parameterized).
    """

    # Accept JSON OR fallback to form-encoded submission
    data = {}
    json_payload = request.get_json(silent=True)
    if json_payload:
        data = json_payload
    else:
        # request.form is ImmutableMultiDict; convert to dict
        data = request.form.to_dict()

    # Normalize and trim
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    phone = (data.get('phone') or '').strip()
    subject = (data.get('subject') or '').strip()
    message = (data.get('message') or '').strip()
    consent_raw = data.get('consent')
    source = (data.get('source') or '').strip()

    # Parse consent (strings like 'on','true','1' or boolean)
    def parse_bool(v):
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        if isinstance(v, str):
            return v.lower() in ('1', 'true', 'on', 'yes')
        return False

    consent = parse_bool(consent_raw)

    # Basic validation
    errors = []
    if not name:
        errors.append("Name is required.")
    if not email:
        errors.append("Email is required.")
    elif not EMAIL_RE.match(email):
        errors.append("Email appears invalid.")
    if not message:
        errors.append("Message is required.")
    if not consent:
        errors.append("Consent is required to process personal data.")

    # length caps
    if len(name) > 256:
        errors.append("Name is too long.")
    if len(email) > 512:
        errors.append("Email is too long.")
    if len(subject) > 120:
        errors.append("Subject is too long.")
    if len(message) > 20000:
        errors.append("Message is too long.")

    # Decide whether to return JSON (AJAX) or not
    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
        or request.is_json
    )

    if errors:
        if wants_json:
            return jsonify(ok=False, errors=errors), 400
        else:
            for err in errors:
                flash(err, 'danger')
            return redirect(url_for('main.contact'))

    # Collect metadata
    ip = None
    try:
        xff = request.headers.get('X-Forwarded-For')
        if xff:
            ip = xff.split(',')[0].strip()
        else:
            ip = request.remote_addr
        # validate IP (if invalid, null it)
        if ip:
            _ = ip_address(ip)
    except Exception:
        ip = None

    user_agent = request.headers.get('User-Agent')
    referer = request.headers.get('Referer')

    # Insert into DB using psycopg2
    insert_sql = """
        INSERT INTO contact_messages
          (name, email, phone, subject, message, consent, source, ip, user_agent, referer, status, created_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created_at;
    """

    created_at = datetime.utcnow()

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            insert_sql,
            (
                name,
                email,
                phone or None,
                subject or None,
                message,
                bool(consent),
                source or None,
                ip,
                user_agent,
                referer,
                'new',
                created_at,
            )
        )
        row = cur.fetchone()
        conn.commit()
    except Exception as exc:
        # Log server-side
        current_app.logger.exception("Failed to save contact message (psycopg2)")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        # return appropriate response
        if wants_json:
            return jsonify(ok=False, message="Failed to save message. Please try again later."), 500
        else:
            flash("We couldn't save your message right now. Please try again later.", 'danger')
            return redirect(url_for('main.contact'))
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # success
    inserted_id = row.get('id') if isinstance(row, dict) else (row[0] if row else None)

    # Optionally: queue email, etc. (deferred recommended).
    if wants_json:
        response = {
            "ok": True,
            "message": "Thanks — we received your message.",
            "id": inserted_id
        }
        return jsonify(response), 201

    flash("Thanks — we received your message. We'll be in touch.", "success")


@main.route('/careers')
def careers():
    """
    Fetch active roles from the DB and render careers page with roles list.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # select relevant fields
        cur.execute("""
            SELECT id, title, dept, location, type, salary, summary, description, is_active, created_at
            FROM roles
            WHERE is_active = TRUE
            ORDER BY created_at DESC
        """)
        roles = cur.fetchall()
        cur.close()
    except Exception as exc:
        current_app.logger.exception("Failed to load roles: %s", exc)
        # In case of DB error, show empty list or an error page; we pass empty list for graceful degrade.
        roles = []
    finally:
        if conn:
            conn.close()

    # Render template and pass roles (list of dicts)
    return render_template("customer/careers.html", roles=roles)

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
MAX_RESUME_SIZE = 2 * 1024 * 1024  # 2MB

@main.route('/careers/apply', methods=['POST'])
def careers_apply():
    """
    Accept application POSTs (AJAX or native form).
    Stores application in DB (psycopg2), uploads resume to R2 using upload_to_r2(),
    stores the R2 key into applications.resume_key.
    Returns JSON when request is XHR (AJAX), otherwise redirects back with a flash.
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json

    # Basic fields
    role_id = request.form.get('role_id') or None
    name = (request.form.get('name') or "").strip()
    email = (request.form.get('email') or "").strip()
    phone = (request.form.get('phone') or "").strip()
    location = (request.form.get('location') or "").strip()
    message = (request.form.get('message') or "").strip()

    # validation
    if not name or not email:
        msg = "Name and email are required."
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, 'error')
        return redirect(url_for('main.careers'))

    resume = request.files.get('resume')

    # If file present, validate extension & size
    resume_key_to_store = None
    resume_filename = None

    try:
        conn = get_db()
        cur = conn.cursor()

        # Insert application first (without resume_key), so we get application id
        cur.execute("""
            INSERT INTO applications (role_id, name, email, phone, location, message, ip_address, user_agent, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            RETURNING id
        """, (
            role_id,
            name,
            email,
            phone,
            location,
            message,
            request.remote_addr,
            request.headers.get('User-Agent')
        ))
        row = cur.fetchone()
        app_id = row[0]

        # If resume uploaded, validate then upload to R2 and update record with key
        if resume and resume.filename:
            filename = secure_filename(resume.filename)
            resume_filename = filename

            # check size if possible
            resume.stream.seek(0, os.SEEK_END)
            size = resume.stream.tell()
            resume.stream.seek(0)

            if size > MAX_RESUME_SIZE:
                conn.rollback()
                msg = "Resume exceeds maximum allowed size of 5MB."
                if is_ajax:
                    return jsonify(success=False, message=msg), 400
                flash(msg, 'error')
                return redirect(url_for('main.careers'))

            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext not in ALLOWED_EXTENSIONS:
                conn.rollback()
                msg = "Resume must be one of: pdf, doc, docx."
                if is_ajax:
                    return jsonify(success=False, message=msg), 400
                flash(msg, 'error')
                return redirect(url_for('main.careers'))

            # Build a deterministic, unique key that includes application id
            unique = uuid.uuid4().hex
            key = f"applications/{app_id}/{unique}_{filename}"

            # Upload to R2 using the helper; it may return public URL, but we will store the key only
            try:
                # Important: upload_to_r2 expects a FileStorage-like object (werkzeug FileStorage)
                upload_to_r2(resume, key)
            except Exception as e:
                current_app.logger.exception("R2 upload failed for application %s: %s", app_id, e)
                conn.rollback()
                msg = "Resume upload failed. Please try again later."
                if is_ajax:
                    return jsonify(success=False, message=msg), 500
                flash(msg, 'error')
                return redirect(url_for('main.careers'))

            resume_key_to_store = key

            # update the application row with resume_key
            cur.execute("""
                UPDATE applications SET resume_key = %s WHERE id = %s
            """, (resume_key_to_store, app_id))

        # commit transaction
        conn.commit()

    except Exception as e:
        current_app.logger.exception("Failed to store application: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        msg = "Unable to submit application right now. Please try again later."
        if is_ajax:
            return jsonify(success=False, message=msg), 500
        flash(msg, 'error')
        return redirect(url_for('main.careers'))

    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

    # Success
    if is_ajax:
        return jsonify(success=True, message="Application received. We'll be in touch shortly.")
    else:
        flash("Thanks — your application was received. We'll be in touch.", "success")

@main.route('/privacy')
def privacy():
    return render_template("customer/privacy.html")



# ---------------------------profile section--------------------------------------------


# ---- Profile page (tabs: profile, addresses, security) ----
@main.route('/profile')
@nocache
def profile():
    if 'customer_id' not in session:
        flash("Please login to view profile.", "warning")
        return redirect(url_for('main.login'))

    customer_id = session['customer_id']
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # fetch customer
    cursor.execute("SELECT customer_id, name, email, phone, is_active, created_at FROM customers WHERE customer_id = %s", (customer_id,))
    customer = cursor.fetchone()

    # fetch addresses
    cursor.execute("SELECT * FROM addresses WHERE customer_id = %s ORDER BY is_default DESC, address_id DESC", (customer_id,))
    addresses = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('customer/profile.html',
                           customer=customer,
                           addresses=addresses)


# ---- Edit profile (name, phone, email) ----

@main.route('/profile/edit', methods=['POST'])
@nocache
def profile_edit():
    if 'customer_id' not in session:
        flash("Please login to edit profile.", "warning")
        return redirect(url_for('main.login'))

    customer_id = session['customer_id']
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    # ignore any email provided by the form (readonly on frontend)
    # email = (request.form.get('email') or '').strip()

    if not name:
        flash("Name is required.", "warning")
        return redirect(url_for('main.profile', _anchor='tab-profile'))

    conn = get_db()
    cursor = conn.cursor()
    try:
        # update only name and phone
        cursor.execute("""
            UPDATE customers
            SET name = %s, phone = %s, updated_at = CURRENT_TIMESTAMP
            WHERE customer_id = %s
        """, (name, phone or None, customer_id))
        conn.commit()

        # update session name for navbar
        session['name'] = name
        session.modified = True

        flash("Profile updated.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Error updating profile")
        flash("Unable to update profile. Try again.", "danger")
    finally:
        cursor.close()
        conn.close()

    # stay on profile tab after redirect
    return redirect(url_for('main.profile', _anchor='tab-profile'))


# ---- Change password (current + new) ----

@main.route('/profile/change-password', methods=['POST'])
@nocache
def profile_change_password():
    if 'customer_id' not in session:
        flash("Please login to change password.", "warning")
        return redirect(url_for('main.login'))

    customer_id = session['customer_id']
    current_pw = request.form.get('current_password') or ''
    new_pw = request.form.get('new_password') or ''
    new_pw_confirm = request.form.get('new_password_confirm') or ''

    # Basic server-side checks (frontend already validates)
    if not (current_pw and new_pw and new_pw_confirm):
        flash("Fill all password fields.", "warning")
        return redirect(url_for('main.profile', _anchor='tab-profile'))
    if new_pw != new_pw_confirm:
        flash("New passwords do not match.", "warning")
        return redirect(url_for('main.profile', _anchor='tab-profile'))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT password_hash FROM customers WHERE customer_id = %s", (customer_id,))
        row = cursor.fetchone()
        if not row:
            flash("Account not found.", "danger")
            return redirect(url_for('main.profile', _anchor='tab-profile'))

        stored_hash = row['password_hash']
        if not check_password_hash(stored_hash, current_pw):
            flash("Current password is incorrect.", "danger")
            return redirect(url_for('main.profile', _anchor='tab-profile'))

        new_hash = generate_password_hash(new_pw)
        cursor.execute("UPDATE customers SET password_hash = %s, updated_at = CURRENT_TIMESTAMP WHERE customer_id = %s", (new_hash, customer_id))
        conn.commit()
        flash("Password changed successfully.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Error changing password")
        flash("Unable to change password. Try again.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('main.profile', _anchor='tab-profile'))

# ---- Add address (POST) ----

@main.route('/address/add', methods=['POST'])
@nocache
def address_add():
    if 'customer_id' not in session:
        flash("Please login to manage addresses.", "warning")
        return redirect(url_for('main.login'))

    customer_id = session['customer_id']
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    line1 = (request.form.get('line1') or '').strip()
    line2 = (request.form.get('line2') or '').strip()
    city = (request.form.get('city') or '').strip()
    state = (request.form.get('state') or '').strip()
    postal = (request.form.get('postal_code') or '').strip()
    country = (request.form.get('country') or 'India').strip()
    is_default = 1 if request.form.get('is_default') else 0

    if not (name and line1 and city and state and postal):
        flash("Please fill required address fields (name, address, city, state, postal code).", "warning")
        return redirect(url_for('main.profile', _anchor='tab-addresses'))


    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO addresses (customer_id, name, phone, line1, line2, city, state, postal_code, country, is_default)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (customer_id, name, phone or None, line1, line2 or None, city, state, postal, country, is_default))
        address_id = cursor.lastrowid
        if is_default:
            cursor.execute("UPDATE addresses SET is_default = 0 WHERE customer_id = %s AND address_id != %s", (customer_id, address_id))
        conn.commit()
        flash("Address added.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Error adding address")
        flash("Unable to add address. Try again.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('main.profile', _anchor='tab-addresses'))

# ---- Edit address (GET for form or POST to save) ----

@main.route('/address/<int:address_id>/edit', methods=['POST'])
@nocache
def address_edit(address_id):
    if 'customer_id' not in session:
        flash("Please login to manage addresses.", "warning")
        return redirect(url_for('main.login'))

    customer_id = session['customer_id']
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    line1 = (request.form.get('line1') or '').strip()
    line2 = (request.form.get('line2') or '').strip()
    city = (request.form.get('city') or '').strip()
    state = (request.form.get('state') or '').strip()
    postal = (request.form.get('postal_code') or '').strip()
    country = (request.form.get('country') or 'India').strip()
    is_default = 1 if request.form.get('is_default') else 0

    if not (name and line1 and city and state and postal):
        flash("Please fill required address fields (name, address, city, state, postal code).", "warning")
        return redirect(url_for('main.profile', _anchor='tab-addresses'))


    conn = get_db()
    cursor = conn.cursor()
    try:
        # ensure ownership
        cursor.execute("SELECT address_id FROM addresses WHERE address_id = %s AND customer_id = %s", (address_id, customer_id))
        if not cursor.fetchone():
            flash("Address not found.", "danger")
            return redirect(url_for('main.profile'))

        cursor.execute("""
            UPDATE addresses
            SET name=%s, phone=%s, line1=%s, line2=%s, city=%s, state=%s, postal_code=%s, country=%s, is_default=%s, updated_at=CURRENT_TIMESTAMP
            WHERE address_id=%s
        """, (name, phone or None, line1, line2 or None, city, state, postal, country, is_default, address_id))

        if is_default:
            cursor.execute("UPDATE addresses SET is_default = 0 WHERE customer_id = %s AND address_id != %s", (customer_id, address_id))

        conn.commit()
        flash("Address updated.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Error editing address")
        flash("Unable to update address. Try again.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('main.profile', _anchor='tab-addresses'))


# ---- Delete address ----

@main.route('/address/<int:address_id>/delete', methods=['POST'])
@nocache
def address_delete(address_id):
    if 'customer_id' not in session:
        flash("Please login to manage addresses.", "warning")
        return redirect(url_for('main.login'))

    customer_id = session['customer_id']
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT address_id, is_default FROM addresses WHERE address_id = %s AND customer_id = %s", (address_id, customer_id))
        row = cursor.fetchone()
        if not row:
            flash("Address not found.", "danger")
            return redirect(url_for('main.profile'))

        # delete
        cursor.execute("DELETE FROM addresses WHERE address_id = %s AND customer_id = %s", (address_id, customer_id))
        conn.commit()

        # if deleted address was default, try to set the most recent address as default
        if row[1] == 1:
            cursor.execute("SELECT address_id FROM addresses WHERE customer_id = %s ORDER BY address_id DESC LIMIT 1", (customer_id,))
            r2 = cursor.fetchone()
            if r2:
                cursor.execute("UPDATE addresses SET is_default = 1 WHERE address_id = %s", (r2[0],))
                conn.commit()

        flash("Address deleted.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Error deleting address")
        flash("Unable to delete address. Try again.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('main.profile', _anchor='tab-addresses'))


# ------------------- Set default address (POST) -------------------
@main.route('/address/<int:address_id>/set-default', methods=['POST'])
@nocache
def address_set_default(address_id):
    if 'customer_id' not in session:
        flash("Please login to manage addresses.", "warning")
        return redirect(url_for('main.login'))

    customer_id = session['customer_id']
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT address_id FROM addresses WHERE address_id = %s AND customer_id = %s", (address_id, customer_id))
        if not cursor.fetchone():
            flash("Address not found.", "danger")
            return redirect(url_for('main.profile'))

        cursor.execute("UPDATE addresses SET is_default = 0 WHERE customer_id = %s", (customer_id,))
        cursor.execute("UPDATE addresses SET is_default = 1 WHERE address_id = %s", (address_id,))
        conn.commit()
        flash("Default address updated.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Error setting default address")
        flash("Unable to set default address. Try again.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('main.profile', _anchor='tab-addresses'))

# -----------------------place order----------------------------

@main.route('/place-order', methods=['GET'])
def place_order():
    q = (request.args.get('q') or '').strip()
    sort = request.args.get('sort') or 'newest'   # default sort
    selected_categories = request.args.getlist('category')  # can be many
    selected_brands = request.args.getlist('brand')
    selected_tags = request.args.getlist('tag')
    selected_colors = request.args.getlist('color')
    selected_sizes = request.args.getlist('size')
    # price range
    min_price = request.args.get('min_price') or None
    max_price = request.args.get('max_price') or None
    # rating threshold (e.g., 4 for 4★ & above)
    rating_min = request.args.get('rating') or None

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Build WHERE clauses (safe parameterized)
    where_clauses = []
    params = []

    # search across name, brand, category, short_description, description (case-insensitive only here)
    if q:
        # Only the search clause is made case-insensitive using LOWER(...)
        where_clauses.append(
            "(LOWER(p.name) LIKE %s OR LOWER(p.brand) LIKE %s OR LOWER(p.category) LIKE %s OR LOWER(p.short_description) LIKE %s OR LOWER(p.description) LIKE %s)"
        )
        like = f"%{q.lower()}%"
        params.extend([like, like, like, like, like])

    if selected_categories:
        placeholders = ",".join(["%s"] * len(selected_categories))
        where_clauses.append(f"p.category IN ({placeholders})")
        params.extend(selected_categories)

    if selected_brands:
        placeholders = ",".join(["%s"] * len(selected_brands))
        where_clauses.append(f"p.brand IN ({placeholders})")
        params.extend(selected_brands)

    # color/size/tag filters via EXISTS subqueries (works in both MySQL and Postgres)
    if selected_colors:
        placeholders = ",".join(["%s"] * len(selected_colors))
        where_clauses.append(
            f"EXISTS (SELECT 1 FROM product_variants pv_c WHERE pv_c.product_id = p.product_id AND pv_c.color IN ({placeholders}))"
        )
        params.extend(selected_colors)

    if selected_sizes:
        placeholders = ",".join(["%s"] * len(selected_sizes))
        where_clauses.append(
            f"EXISTS (SELECT 1 FROM product_variants pv_s WHERE pv_s.product_id = p.product_id AND pv_s.size IN ({placeholders}))"
        )
        params.extend(selected_sizes)

    if selected_tags:
        placeholders = ",".join(["%s"] * len(selected_tags))
        where_clauses.append(
            f"EXISTS (SELECT 1 FROM product_tags pt WHERE pt.product_id = p.product_id AND pt.tag_id IN ({placeholders}))"
        )
        params.extend(selected_tags)

    # combine where
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Derived table for reviews:
    #  - first collapse product_reviews by (product_id, customer_id, order_id) => avg per cluster
    #  - then avg those cluster averages per product and count clusters -> rating_avg, reviews_count
    # We'll LEFT JOIN that derived table so we can aggregate safely in the outer query.
    reviews_subquery = """
        LEFT JOIN (
            SELECT t.product_id,
                   AVG(t.avg_rating) AS avg_of_customer_order_ratings,
                   COUNT(1) AS reviews_count
            FROM (
                SELECT pr.product_id, pr.customer_id, pr.order_id, AVG(pr.rating) AS avg_rating
                FROM product_reviews pr
                GROUP BY pr.product_id, pr.customer_id, pr.order_id
            ) t
            GROUP BY t.product_id
        ) pr ON pr.product_id = p.product_id
    """

    # Main query.
    # Note: to satisfy Postgres' grouping rules we include non-aggregated p.* columns in GROUP BY.
    main_q = f"""
        SELECT
            p.product_id,
            p.name,
            p.brand,
            p.category,
            p.image_path,
            p.is_active,
            p.is_returnable,
            COALESCE(MIN(pv.price), 0) AS min_price,
            COALESCE(MAX(pv.price), 0) AS max_price,
            -- use product-level stock_count as you requested
            COALESCE(p.stock_count, 0) AS total_stock,
            COUNT(DISTINCT pv.variant_id) AS variant_count,
            -- aggregate the joined review columns so Postgres allows them in SELECT while grouping by product fields
            COALESCE(MAX(pr.avg_of_customer_order_ratings), 0) AS rating_avg,
            COALESCE(MAX(pr.reviews_count), 0) AS reviews_count,
            (SELECT COUNT(1) FROM product_images pi WHERE pi.product_id = p.product_id) AS total_images,
            p.created_at
        FROM products p
        LEFT JOIN product_variants pv ON pv.product_id = p.product_id
        {reviews_subquery}
        WHERE {where_sql}
        GROUP BY
            p.product_id, p.name, p.brand, p.category, p.image_path,
            p.is_active, p.is_returnable, p.stock_count, p.created_at
    """

    # HAVING: price and rating filters (operate on the aggregated results)
    having_clauses = []
    having_params = []
    if min_price:
        try:
            min_val = float(min_price)
            having_clauses.append("MIN(pv.price) >= %s")
            having_params.append(min_val)
        except Exception:
            pass
    if max_price:
        try:
            max_val = float(max_price)
            having_clauses.append("MAX(pv.price) <= %s")
            having_params.append(max_val)
        except Exception:
            pass
    if rating_min:
        try:
            rv = float(rating_min)
            # reference the aggregated alias (we used MAX(pr.avg_of_customer_order_ratings) as rating_avg)
            having_clauses.append("COALESCE(MAX(pr.avg_of_customer_order_ratings),0) >= %s")
            having_params.append(rv)
        except Exception:
            pass

    having_sql = (" HAVING " + " AND ".join(having_clauses)) if having_clauses else ""

    # Sorting
    sort_sql = " ORDER BY p.created_at DESC "
    if sort == 'low':
        sort_sql = " ORDER BY min_price ASC "
    elif sort == 'high':
        sort_sql = " ORDER BY min_price DESC "
    elif sort == 'rating':
        sort_sql = " ORDER BY rating_avg DESC "
    elif sort == 'newest':
        sort_sql = " ORDER BY p.created_at DESC "

    final_q = main_q + having_sql + sort_sql

    # Execute product query
    cursor.execute(final_q, params + having_params)
    products = cursor.fetchall() or []

    # Format price_range and stats for each product (template convenience)
    for p in products:
        p['price_range'] = {
            'min': float(p['min_price'] or 0),
            'max': float(p['max_price'] or 0),
            'has_range': (p['min_price'] is not None and p['max_price'] is not None and p['min_price'] != p['max_price'] and p['variant_count'] > 1)
        }
        p['stats'] = {
            'variants': int(p['variant_count'] or 0),
            # use the product stock_count column (already selected as total_stock)
            'total_stock': int(p['total_stock'] or 0),
            'total_images': int(p['total_images'] or 0)
        }
        # normalize path
        if p.get('image_path'):
            p['image_path'] = p['image_path'].replace('\\', '/')

    # --- Fetch dynamic filter values (distinct categories, brands, tags, colors, sizes) ---
    cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category <> '' ORDER BY category ASC")
    categories = [r['category'] for r in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand <> '' ORDER BY brand ASC")
    brands = [r['brand'] for r in cursor.fetchall()]

    cursor.execute("""
        SELECT t.tag_id, t.name FROM tags t
        JOIN product_tags pt ON pt.tag_id = t.tag_id
        GROUP BY t.tag_id, t.name
        ORDER BY t.name ASC
    """)
    tags = cursor.fetchall()

    cursor.execute("SELECT DISTINCT color FROM product_variants WHERE color IS NOT NULL AND color <> '' ORDER BY color ASC")
    colors = [r['color'] for r in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT size FROM product_variants WHERE size IS NOT NULL AND size <> '' ORDER BY size ASC")
    sizes = [r['size'] for r in cursor.fetchall()]

    cursor.execute("SELECT COALESCE(MIN(price),0) AS min_price, COALESCE(MAX(price),0) AS max_price FROM product_variants")
    price_row = cursor.fetchone()
    global_min_price = float(price_row['min_price'] or 0)
    global_max_price = float(price_row['max_price'] or 0)

    cursor.close()
    conn.close()

    # pass current query params so template can keep boxes checked
    context = {
        'products': products,
        'filters': {
            'categories': categories,
            'brands': brands,
            'tags': tags,
            'colors': colors,
            'sizes': sizes,
            'global_min_price': int(global_min_price),
            'global_max_price': int(global_max_price),
        },
        # reflect selected filters back to template (so boxes remain checked)
        'selected': {
            'q': q, 'sort': sort,
            'categories': selected_categories,
            'brands': selected_brands,
            'tags': selected_tags,
            'colors': selected_colors,
            'sizes': selected_sizes,
            'min_price': min_price,
            'max_price': max_price,
            'rating': rating_min
        },
        # include request.args for convenience
        'request_args': request.args
    }
    return render_template('customer/view_products.html', **context)




# ------------------viewing product details----------------------

@main.route('/prod/<int:product_id>')
@nocache
def view_prod_detail(product_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # fetch product
    cursor.execute("SELECT * FROM products WHERE product_id = %s", (product_id,))
    product = cursor.fetchone()
    if not product:
        cursor.close()
        conn.close()
        flash("Product not found", "danger")
        return redirect(url_for('main.view_products'))

    # Normalize a few fields
    if product.get('image_path'):
        product['image_path'] = product['image_path'].replace('\\', '/')
    for fld in ('brand','category','short_description','description','material',
                'fit','care_instructions','pattern','occasion','season','sustainability','weight'):
        product[fld] = product.get(fld) or ''

    # Keep raw DB description (unescaped) for debug panel
    raw_desc = product.get('description') or ''
    product['description_raw'] = raw_desc

    # -----------------------
    # Robust description normalization:
    #   - unescape html entities
    #   - turn <br> variants into newlines
    #   - convert literal "\n" sequences to real newlines
    #   - normalize line endings
    #   - escape everything
    #   - convert newlines to <br/> and mark it safe (Markup)
    # -----------------------
    try:
        s = _html.unescape(raw_desc or '')

        # Replace any <br> (case-insensitive) with newline
        s = re.sub(r'(?i)<\s*br\s*/?\s*>', '\n', s)

        # Convert literal backslash-n sequences to real newline (if DB stored \n as text)
        s = s.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')

        # Normalize CRLF & CR to LF
        s = s.replace('\r\n', '\n').replace('\r', '\n')

        # Strip leading/trailing whitespace and collapse 3+ newlines to 2 for readability
        s = s.strip()
        s = re.sub(r'\n{3,}', '\n\n', s)

        # Escape everything (protect against XSS) — markupsafe.escape returns a Markup object
        escaped = escape(s)  # this escapes <, >, &, etc.

        # Convert newline characters to real <br/> tags for HTML rendering
        # escaped is Markup (safe); do replacement on its string form, then wrap in Markup
        escaped_with_br = Markup(str(escaped).replace('\n', '<br/>'))

        product['description_html'] = escaped_with_br

    except Exception:
        current_app.logger.exception("Error processing product.description")
        # fallback: simple escape + newline->br
        product['description_html'] = Markup(escape(raw_desc or '').replace('\n', '<br/>'))

    # --- variants ---
    cursor.execute("""
        SELECT pv.*
        FROM product_variants pv
        WHERE pv.product_id = %s
        ORDER BY pv.is_default DESC, pv.variant_id ASC
    """, (product_id,))
    variants = cursor.fetchall() or []
    for v in variants:
        v['price'] = float(v.get('price') or 0.0)
        v['stock_count'] = int(v.get('stock_count') or 0)
        # make sure variant string fields are never None
        for f in ('sku','size','color','color_hex'):
            v[f] = v.get(f) or ''

    # product-level images (variant_id IS NULL)
    cursor.execute("""
        SELECT *
        FROM product_images
        WHERE product_id = %s AND variant_id IS NULL
        ORDER BY is_primary DESC, position ASC, image_id ASC
    """, (product_id,))
    product_images = cursor.fetchall() or []
    for pi in product_images:
        pi['path'] = pi['path'].replace('\\', '/')

    # variant images grouped by variant_id
    cursor.execute("""
        SELECT *
        FROM product_images
        WHERE product_id = %s AND variant_id IS NOT NULL
        ORDER BY variant_id ASC, position ASC, image_id ASC
    """, (product_id,))
    all_variant_images = cursor.fetchall() or []
    variant_images = {}
    for img in all_variant_images:
        img['path'] = img['path'].replace('\\', '/')
        vid = img.get('variant_id')
        variant_images.setdefault(vid, []).append(img)

    # prepare thumbnail path for each variant (fallback product image / placeholder)
    for v in variants:
        vid = v.get('variant_id')
        if vid in variant_images and variant_images[vid]:
            v['thumb'] = variant_images[vid][0]['path']
        elif product_images:
            v['thumb'] = product_images[0]['path']
        elif product.get('image_path'):
            v['thumb'] = product['image_path']
        else:
            v['thumb'] = 'uploads/placeholder.png'

    # initial variant_id selection logic (variant_id or variant_sku query param)
    initial_variant_id = None
    qvid = request.args.get('variant_id')
    qsku = request.args.get('variant_sku')
    if qvid:
        try:
            qv = int(qvid)
            if any(int(x.get('variant_id')) == qv for x in variants):
                initial_variant_id = qv
        except Exception:
            pass
    elif qsku:
        for v in variants:
            if v.get('sku') and v['sku'] == qsku:
                initial_variant_id = int(v['variant_id'])
                break

    # Reviews aggregate & initial top 5
    cursor.execute("SELECT COALESCE(AVG(rating),0) AS avg_rating, COUNT(*) AS total_reviews FROM product_reviews WHERE product_id = %s", (product_id,))
    agg = cursor.fetchone() or {'avg_rating':0.0, 'total_reviews':0}
    avg_rating = float(agg.get('avg_rating') or 0.0)
    total_reviews = int(agg.get('total_reviews') or 0)

    cursor.execute("""
        SELECT pr.*, c.name AS customer_name
        FROM product_reviews pr
        LEFT JOIN customers c ON c.customer_id = pr.customer_id
        WHERE pr.product_id = %s
        ORDER BY pr.created_at DESC
        LIMIT 5
    """, (product_id,))
    top_reviews = cursor.fetchall() or []
    for r in top_reviews:
        r['customer_name'] = r.get('customer_name') or 'Anonymous'
        r['rating'] = int(r.get('rating') or 0)
        r['title'] = r.get('title') or ''
        r['body'] = r.get('body') or ''
        try:
            r['created_at_str'] = r['created_at'].strftime('%b %d, %Y') if r.get('created_at') else ''
        except Exception:
            r['created_at_str'] = str(r.get('created_at') or '')

    cursor.close()
    conn.close()

    # show developer debug panel when app.debug or session['is_dev'] set
    show_dev = bool(current_app.debug or session.get('is_dev'))

    return render_template(
        'customer/product_detail.html',
        product=product,
        variants=variants,
        product_images=product_images,
        variant_images=variant_images,
        initial_variant_id=initial_variant_id,
        avg_rating=round(avg_rating, 2),
        total_reviews=total_reviews,
        top_reviews=top_reviews,
        show_dev=show_dev
    )





# ---- AJAX endpoint to fetch reviews (JSON) with pagination and sorting ----
@main.route('/prod/<int:product_id>/reviews_ajax')
def reviews_ajax(product_id):
    """
    GET params:
      - sort: latest|oldest|highest|lowest
      - offset: int (default 0)
      - limit: int (default 5)
    Returns JSON { ok: True, reviews: [...], total_reviews, avg_rating }
    """
    sort = (request.args.get('sort') or 'latest').lower()
    offset = int(request.args.get('offset') or 0)
    limit = int(request.args.get('limit') or 5)
    sort_map = {
        'latest': 'pr.created_at DESC',
        'oldest': 'pr.created_at ASC',
        'highest': 'pr.rating DESC, pr.created_at DESC',
        'lowest': 'pr.rating ASC, pr.created_at DESC'
    }
    order_sql = sort_map.get(sort, sort_map['latest'])

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT COALESCE(AVG(rating),0) AS avg_rating, COUNT(*) AS total_reviews FROM product_reviews WHERE product_id = %s", (product_id,))
        agg = cursor.fetchone() or {'avg_rating':0.0, 'total_reviews':0}
        avg_rating = float(agg.get('avg_rating') or 0.0)
        total_reviews = int(agg.get('total_reviews') or 0)

        cursor.execute(f"""
            SELECT pr.*, c.name AS customer_name
            FROM product_reviews pr
            LEFT JOIN customers c ON c.customer_id = pr.customer_id
            WHERE pr.product_id = %s
            ORDER BY {order_sql}
            LIMIT %s OFFSET %s
        """, (product_id, limit, offset))
        rows = cursor.fetchall() or []
        # normalize
        for r in rows:
            r['customer_name'] = r.get('customer_name') or 'Anonymous'
            r['rating'] = int(r.get('rating') or 0)
            r['title'] = r.get('title') or ''
            r['body'] = r.get('body') or ''
            try:
                r['created_at_str'] = r['created_at'].strftime('%b %d, %Y') if r.get('created_at') else ''
            except:
                r['created_at_str'] = str(r.get('created_at') or '')
        return jsonify({
            "ok": True,
            "reviews": rows,
            "total_reviews": total_reviews,
            "avg_rating": round(avg_rating,2),
            "offset": offset,
            "limit": limit,
            "sort": sort
        })
    except Exception as e:
        current_app.logger.exception("Error fetching reviews_ajax")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ---- Optional server-side page showing all reviews (fallback) ----
@main.route('/prod/<int:product_id>/reviews')
def product_reviews_page(product_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT product_id, name FROM products WHERE product_id = %s", (product_id,))
    product = cursor.fetchone()
    if not product:
        cursor.close(); conn.close()
        flash("Product not found", "danger")
        return redirect(url_for('main.view_products'))
    cursor.execute("""
        SELECT pr.*, c.name AS customer_name
        FROM product_reviews pr
        LEFT JOIN customers c ON c.customer_id = pr.customer_id
        WHERE pr.product_id = %s
        ORDER BY pr.created_at DESC
        LIMIT 200
    """, (product_id,))
    reviews = cursor.fetchall() or []
    cursor.close(); conn.close()
    return render_template('customer/product_reviews.html', product=product, reviews=reviews)




@main.route('/cart/add', methods=['POST'])
@nocache
def cart_add():
    if 'customer_id' not in session:
        # AJAX clients receive JSON + redirect_url for login
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'ok': False,
                'message': 'Please login to add products.',
                'redirect_url': url_for('main.login')
            }), 401
        flash("Please login to add products.", "warning")
        return redirect(url_for('main.login'))

    product_id = request.form.get('product_id')
    variant_id = request.form.get('variant_id')
    print(product_id, variant_id)
    qty_raw = request.form.get('qty') or '1'

    # basic validation
    if not product_id or not variant_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'message': 'Invalid request. Missing product/variant.'}), 400
        flash("Invalid request. Missing product/variant.", "danger")
        return redirect(request.referrer or url_for('main.view_products'))

    try:
        qty = int(qty_raw)
    except (ValueError, TypeError):
        qty = 1
    if qty < 1:
        qty = 1

    # fetch variant and product details
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM product_variants WHERE variant_id = %s AND product_id = %s",
        (variant_id, product_id)
    )
    variant = cursor.fetchone()
    if not variant:
        cursor.close()
        conn.close()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'message': 'Selected variant not found.'}), 404
        flash("Selected variant not found.", "danger")
        return redirect(request.referrer or url_for('main.view_products'))

    cursor.execute(
        "SELECT name, image_path, sku as product_sku FROM products WHERE product_id = %s",
        (product_id,)
    )
    p = cursor.fetchone()

    # Try to get an image for the variant or product
    variant_image_path = None
    cursor.execute(
        "SELECT path FROM product_images WHERE variant_id = %s ORDER BY is_primary DESC, position ASC LIMIT 1",
        (variant_id,)
    )
    img = cursor.fetchone()
    if img and img.get('path'):
        variant_image_path = img.get('path')
    else:
        cursor.execute(
            "SELECT path FROM product_images WHERE product_id = %s AND (variant_id IS NULL OR variant_id = 0) ORDER BY is_primary DESC, position ASC LIMIT 1",
            (product_id,)
        )
        img2 = cursor.fetchone()
        if img2 and img2.get('path'):
            variant_image_path = img2.get('path')

    cursor.close()
    conn.close()

    max_avail = int(variant.get('stock_count') or 0)
    if max_avail <= 0:
        # out of stock
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'message': 'Sorry, this variant is out of stock.'}), 409
        flash("Sorry, this variant is out of stock.", "warning")
        return redirect(request.referrer or url_for('main.view_products'))

    # clamp qty to available stock (for new items or when partial fill possible)
    clamped = False
    if qty > max_avail:
        qty = max_avail
        clamped = True

    price = float(variant.get('price') or 0.0)
    sku = variant.get('sku') or ''
    name = p.get('name') if p else ''
    image_path = variant_image_path if variant_image_path else (p.get('image_path') if p and p.get('image_path') else None)

    cart = session.get('cart', [])

    # Try to merge with existing same product+variant item
    merged = False
    for item in cart:
        if str(item.get('variant_id')) == str(variant_id) and str(item.get('product_id')) == str(product_id):
            existing_qty = int(item.get('qty', 0))
            # If already at or beyond stock, do not add more — return an error instead.
            if existing_qty >= max_avail:
                # AJAX: return JSON error so frontend shows correct state
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'ok': False,
                        'message': f"Cannot add more — already at maximum available stock ({max_avail}).",
                        'cart_count': sum(int(i.get('qty', 0)) for i in cart),
                        'cart_item_qty': existing_qty
                    }), 409
                # non-AJAX fallback
                flash(f"Cannot add more — already at maximum available stock ({max_avail}).", "warning")
                return redirect(request.referrer or url_for('main.view_prod_detail', product_id=product_id, variant_id=variant_id))

            # compute new quantity
            new_qty =  qty
            if new_qty > max_avail:
                # increase to max available and notify (clamped)
                new_qty = max_avail
                item['qty'] = new_qty
                item['max_qty'] = max_avail
                merged = True
                session['cart'] = cart
                session.modified = True
                # return success with clamped message for AJAX
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    cart_count = sum(int(i.get('qty', 0)) for i in session.get('cart', []))
                    return jsonify({
                        'ok': True,
                        'message': f"Quantity reduced to available stock ({max_avail}). Item added to cart.",
                        'cart_count': cart_count,
                        'product_id': product_id,
                        'variant_id': variant_id,
                        'cart_item_qty': item.get('qty', 0)
                    }), 200
                # non-AJAX
                flash(f"Quantity reduced to available stock ({max_avail}).", "info")
                return redirect(url_for('main.view_prod_detail', product_id=product_id, variant_id=variant_id))

            # normal merge within stock
            item['qty'] = new_qty
            item['max_qty'] = max_avail
            merged = True
            session['cart'] = cart
            session.modified = True
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                cart_count = sum(int(i.get('qty', 0)) for i in session.get('cart', []))
                return jsonify({
                    'ok': True,
                    'message': 'Added to cart.',
                    'cart_count': cart_count,
                    'product_id': product_id,
                    'variant_id': variant_id,
                    'cart_item_qty': item.get('qty', 0)
                }), 200
            flash("Added to cart", "success")
            return redirect(url_for('main.view_prod_detail', product_id=product_id, variant_id=variant_id))

    # not merged => create new cart item (we already clamped qty above)
    if not merged:
        cart_item = {
            'cart_item_id': uuid.uuid4().hex,
            'product_id': int(product_id),
            'variant_id': int(variant_id),
            'sku': sku,
            'name': name,
            'price': price,
            'qty': qty,
            'image_path': image_path,
            'max_qty': max_avail
        }
        cart.append(cart_item)
        session['cart'] = cart
        session.modified = True

        cart_count = sum(int(i.get('qty', 0)) for i in session.get('cart', []))
        # AJAX response: success (with clamped message if applicable)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            message = "Added to cart"
            if clamped:
                message = f"Quantity reduced to available stock ({max_avail}). Item added to cart."
            # find the cart item qty to return
            cart_item_qty = 0
            for it in session.get('cart', []):
                if str(it.get('variant_id')) == str(variant_id) and str(it.get('product_id')) == str(product_id):
                    cart_item_qty = int(it.get('qty', 0))
                    break
            return jsonify({
                'ok': True,
                'message': message,
                'cart_count': cart_count,
                'product_id': product_id,
                'variant_id': variant_id,
                'cart_item_qty': cart_item_qty,
                'redirect_url': url_for('main.view_cart')
            }), 200

        # non-AJAX behavior preserved
        if clamped:
            flash(f"Quantity reduced to available stock ({max_avail}).", "info")
        flash("Added to cart", "success")


# NEW endpoint: update cart item quantity (AJAX)
@main.route('/cart/update_qty', methods=['POST'])
@nocache
def cart_update_qty():
    # requires login for cart operations
    if 'customer_id' not in session:
        return jsonify({'ok': False, 'message': 'Please login to update cart.'}), 401

    product_id = request.form.get('product_id')
    variant_id = request.form.get('variant_id')
    qty_raw = request.form.get('qty')

    if not product_id or not variant_id or qty_raw is None:
        return jsonify({'ok': False, 'message': 'Missing parameters.'}), 400

    try:
        new_qty = int(qty_raw)
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'message': 'Invalid quantity.'}), 400

    if new_qty < 0:
        return jsonify({'ok': False, 'message': 'Invalid quantity.'}), 400

    # fetch variant to check stock
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM product_variants WHERE variant_id = %s AND product_id = %s",
        (variant_id, product_id)
    )
    variant = cursor.fetchone()
    cursor.close()
    conn.close()

    if not variant:
        return jsonify({'ok': False, 'message': 'Variant not found.'}), 404

    max_avail = int(variant.get('stock_count') or 0)
    if new_qty > max_avail:
        return jsonify({'ok': False, 'message': f'Requested quantity exceeds available stock .', 'max_qty': max_avail}), 409

    cart = session.get('cart', [])

    found = False
    for item in cart:
        if str(item.get('variant_id')) == str(variant_id) and str(item.get('product_id')) == str(product_id):
            found = True
            if new_qty == 0:
                # remove item
                cart.remove(item)
            else:
                item['qty'] = new_qty
                item['max_qty'] = max_avail
            break

    if not found and new_qty > 0:
        # create new cart item (client asked to set >0 for an item not currently present)
        price = float(variant.get('price') or 0.0)
        sku = variant.get('sku') or ''
        # try to fetch product name/image path
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT name, image_path FROM products WHERE product_id = %s", (product_id,))
        p = cursor.fetchone()
        cursor.close()
        conn.close()
        image_path = p.get('image_path') if p and p.get('image_path') else None
        cart_item = {
            'cart_item_id': uuid.uuid4().hex,
            'product_id': int(product_id),
            'variant_id': int(variant_id),
            'sku': sku,
            'name': p.get('name') if p else '',
            'price': price,
            'qty': new_qty,
            'image_path': image_path,
            'max_qty': max_avail
        }
        cart.append(cart_item)

    session['cart'] = cart
    session.modified = True

    cart_count = sum(int(i.get('qty', 0)) for i in session.get('cart', []))
    # find the current qty for this item (0 if not present)
    current_qty = 0
    for it in session.get('cart', []):
        if str(it.get('variant_id')) == str(variant_id) and str(it.get('product_id')) == str(product_id):
            current_qty = int(it.get('qty', 0))
            break

    return jsonify({'ok': True, 'message': 'Cart updated.', 'cart_count': cart_count, 'cart_item_qty': current_qty}), 200


# NEW endpoint: check cart item status (quick, read-only)
@main.route('/cart/item_status', methods=['GET'])
@nocache
def cart_item_status():
    product_id = request.args.get('product_id')
    variant_id = request.args.get('variant_id')

    if not product_id or not variant_id:
        return jsonify({'ok': False, 'message': 'Missing parameters.'}), 400

    cart = session.get('cart', [])
    current_qty = 0
    for it in cart:
        if str(it.get('variant_id')) == str(variant_id) and str(it.get('product_id')) == str(product_id):
            current_qty = int(it.get('qty', 0))
            break
    cart_count = sum(int(i.get('qty', 0)) for i in cart)

    return jsonify({'ok': True, 'cart_item_qty': current_qty, 'cart_count': cart_count}), 200



# ------------------ wishlist routes (drop in to your routes file) ------------------


# ...existing code...
@main.route('/wishlist/toggle', methods=['POST'])
def wishlist_toggle():
    customer_id = session.get('customer_id')
    if not customer_id:
        # if XHR, return 401; else redirect to login
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(ok=False, message="authentication required"), 401
        return redirect(url_for('auth.login', next=request.url))

    variant_id = request.form.get('variant_id') or (request.json and request.json.get('variant_id'))
    product_id = request.form.get('product_id') or (request.json and request.json.get('product_id'))
    if not variant_id or not product_id:
        return jsonify(ok=False, message="missing variant_id or product_id"), 400

    try:
        vid = int(variant_id)
        pid = int(product_id)
    except Exception:
        return jsonify(ok=False, message="invalid IDs"), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        # use DictCursor for convenience if psycopg2 available
        cur = conn.cursor(cursor_factory=getattr(psycopg2.extras, 'DictCursor', None))
        # check existing entry
        cur.execute("SELECT wishlist_id FROM public.wishlist WHERE customer_id = %s AND variant_id = %s", (customer_id, vid))
        row = cur.fetchone()
        if row:
            # remove existing
            # row may be tuple or dict depending on cursor; handle both
            existing_id = row['wishlist_id'] if isinstance(row, dict) else row[0]
            cur.execute("DELETE FROM public.wishlist WHERE wishlist_id = %s", (existing_id,))
            conn.commit()
            action = 'removed'
        else:
            # insert new
            # For Postgres RETURNING wishlist_id is useful; for MySQL the wrapper will not return - but commit anyway
            try:
                cur.execute("INSERT INTO public.wishlist (customer_id, product_id, variant_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) RETURNING wishlist_id", (customer_id, pid, vid))
                new_row = cur.fetchone()
                # ensure cursor consumed for RETURNING
            except Exception:
                # fallback for DBs without RETURNING (MySQL)
                cur.execute("INSERT INTO public.wishlist (customer_id, product_id, variant_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", (customer_id, pid, vid))
            conn.commit()
            action = 'added'

        # get updated count
        cur.execute("SELECT count(*) AS cnt FROM public.wishlist WHERE customer_id = %s", (customer_id,))
        cnt_row = cur.fetchone()
        count = int(cnt_row['cnt'] if isinstance(cnt_row, dict) and 'cnt' in cnt_row else (cnt_row[0] if cnt_row else 0))
        return jsonify(ok=True, action=action, wishlist_count=count)
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        current_app.logger.exception("wishlist toggle failed: %s", e)
        return jsonify(ok=False, message="server error"), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass
# ...existing code...


@main.route('/wishlist/status', methods=['GET'])
@nocache
def wishlist_status():
    customer_id = session.get('customer_id')
    variant_id = request.args.get('variant_id')
    if not variant_id:
        return jsonify(ok=False, message='Missing variant_id'), 400
    try:
        vid = int(variant_id)
    except Exception:
        return jsonify(ok=False, message='Invalid variant_id'), 400

    if not customer_id:
        # not logged in -> not wished
        return jsonify(ok=True, wished=False)

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT 1 FROM public.wishlist WHERE customer_id = %s AND variant_id = %s LIMIT 1", (customer_id, vid))
    r = cur.fetchone()
    wished = bool(r)
    return jsonify(ok=True, wished=wished)



# ---- Check wishlist status for variant (used by product detail JS) ----
@main.route('/wishlist', methods=['GET'])
@nocache
def wishlist_page():
    customer_id = session.get('customer_id')
    if not customer_id:
        return redirect(url_for('main.login', next=request.path))

    conn = get_db()
    # DictCursor when available
    cur = conn.cursor(cursor_factory=getattr(psycopg2.extras, 'DictCursor', None))

    # Query wishlist items and join product + variant + one thumbnail image
    cur.execute("""
      SELECT w.wishlist_id, w.created_at,
             p.product_id, p.name as product_name, p.image_path,
             p.rating_avg, p.reviews_count,
             v.variant_id, v.price, v.size, v.color,
             COALESCE(
               (SELECT pi.path
                FROM public.product_images pi
                WHERE pi.variant_id = v.variant_id
                ORDER BY pi.is_primary DESC, pi.position ASC
                LIMIT 1),
               p.image_path
             ) AS thumb_path
      FROM public.wishlist w
      JOIN public.product_variants v ON v.variant_id = w.variant_id
      JOIN public.products p ON p.product_id = w.product_id
      WHERE w.customer_id = %s
      ORDER BY w.created_at DESC
      """, (customer_id,))
    rows = cur.fetchall()

    wishlist_items = []
    for r in rows:
        wishlist_items.append({
            'wishlist_id': r['wishlist_id'],
            'added_at': r['created_at'],
            'added_at_str': r['created_at'].strftime('%d %b %Y') if r['created_at'] else '',
            'product': {
                'product_id': r['product_id'],
                'name': r['product_name'],
                'image_path': r['image_path'],
                'rating_avg': float(r['rating_avg']) if r.get('rating_avg') is not None else 0.0,
                'reviews_count': int(r['reviews_count']) if r.get('reviews_count') is not None else 0
            },
            'variant': {
                'variant_id': r['variant_id'],
                'price': float(r['price']) if r['price'] is not None else 0.0,
                'size': r['size'],
                'color': r['color']
            },
            'thumb': r['thumb_path']
        })

    # Pass count
    cur.execute("SELECT count(*) as cnt FROM public.wishlist WHERE customer_id = %s", (customer_id,))
    cnt_row = cur.fetchone()
    wishlist_count = int(cnt_row['cnt']) if cnt_row else 0

    return render_template('customer/wishlist.html', wishlist_items=wishlist_items, wishlist_count=wishlist_count)




# Backend: cart routes (drop in to your routes file)

@main.route('/cart')
@nocache
def view_cart():
    if 'customer_id' not in session:
        flash("Please login to add products.", "warning")
        return redirect(url_for('main.login'))
    """
    Display session cart (list of dicts). Show subtotal, default shipping (50), and total.
    """
    cart = session.get('cart', [])  # list of items
    subtotal = 0.0
    for it in cart:
        try:
            subtotal += float(it.get('price', 0.0)) * int(it.get('qty', 0))
        except Exception:
            pass

    shipping_cost = 50.0  # default shipping cost
    total = subtotal + shipping_cost

    return render_template('customer/cart.html', cart=cart, subtotal=subtotal, shipping_cost=shipping_cost, total=total)


@main.route('/update_cart_quantity', methods=['POST'])
@nocache
def update_cart_quantity():
    if 'customer_id' not in session:
        flash("Please login to add products.", "warning")
        return redirect(url_for('main.login'))
    """
    Expects:
      - cart_item_id: identifies cart entry
      - action: 'increase' / 'decrease' / 'set'
      - if action == 'set' provide 'qty' numeric
    """
    cart = session.get('cart', [])  # list
    cart_item_id = request.form.get('cart_item_id')
    action = request.form.get('action')
    if not cart_item_id or not action:
        flash("Invalid request.", "danger")
        return redirect(url_for('main.view_cart'))

    # find item
    found = False
    for i, item in enumerate(cart):
        if str(item.get('cart_item_id')) == str(cart_item_id):
            found = True
            try:
                current = int(item.get('qty', 0))
            except Exception:
                current = 0
            max_qty = int(item.get('max_qty', 0) or 0)

            if action == 'increase':
                new_qty = current + 1
                if max_qty and new_qty > max_qty:
                    new_qty = max_qty
                    flash(f"Quantity limited to available stock .", "info")
                item['qty'] = new_qty

            elif action == 'decrease':
                new_qty = current - 1
                if new_qty <= 0:
                    # remove item
                    cart.pop(i)
                    flash("Item removed from cart.", "info")
                else:
                    item['qty'] = new_qty

            elif action == 'set':
                # set explicit qty
                q_raw = request.form.get('qty')
                try:
                    q = int(q_raw)
                    if q < 1:
                        q = 1
                except Exception:
                    q = current or 1
                if max_qty and q > max_qty:
                    q = max_qty
                    flash(f"Quantity limited to available stock ({max_qty}).", "info")
                item['qty'] = q
            break

    if not found:
        flash("Cart item not found.", "danger")

    session['cart'] = cart
    session.modified = True
    return redirect(url_for('main.view_cart'))


@main.route('/remove_cart_item', methods=['POST'])
@nocache
def remove_cart_item():
    if 'customer_id' not in session:
        flash("Please login to add products.", "warning")
        return redirect(url_for('main.login'))
    """
    Expects cart_item_id form field.
    """
    cart_item_id = request.form.get('cart_item_id')
    if not cart_item_id:
        flash("Invalid request.", "danger")
        return redirect(url_for('main.view_cart'))

    cart = session.get('cart', [])
    new_cart = [it for it in cart if str(it.get('cart_item_id')) != str(cart_item_id)]
    if len(new_cart) != len(cart):
        flash("Item removed from cart.", "success")
    else:
        flash("Item not found in cart.", "warning")
    session['cart'] = new_cart
    session.modified = True
    return redirect(url_for('main.view_cart'))


@main.route('/checkout', methods=['GET'])
@nocache
def checkout():
    if 'customer_id' not in session:
        flash("Please login to continue to checkout.", "warning")
        return redirect(url_for('main.login'))

    cart = session.get('cart', [])
    if not cart:
        flash("Cart is empty.", "warning")
        return redirect(url_for('main.view_cart'))

    customer_id = session['customer_id']
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    # fetch customer's saved addresses
    cursor.execute("SELECT * FROM addresses WHERE customer_id = %s ORDER BY is_default DESC, address_id DESC", (customer_id,))
    addresses = cursor.fetchall()
    cursor.close()
    conn.close()

    # compute subtotal and totals
    subtotal = 0.0
    for it in cart:
        try:
            subtotal += float(it.get('price', 0.0)) * int(it.get('qty', 0))
        except Exception:
            pass
    shipping_cost = 50.0
    total = subtotal + shipping_cost

    return render_template('customer/checkout_select_address.html',
                           cart=cart, addresses=addresses,
                           subtotal=subtotal, shipping_cost=shipping_cost, total=total)


@main.route('/place_cart_order', methods=['POST'])
@nocache
def place_cart_order():
    # require login
    if 'customer_id' not in session:
        flash("Please login to place order.", "warning")
        return redirect(url_for('main.login'))

    cart = session.get('cart', [])
    if not cart:
        flash("Cart is empty!", "danger")
        return redirect(url_for('main.view_cart'))

    customer_id = session['customer_id']

    # read form fields
    shipping_address_id = (request.form.get('shipping_address_id') or '').strip() or None
    new_name = (request.form.get('new_name') or '').strip()
    new_phone = (request.form.get('new_phone') or '').strip()
    new_line1 = (request.form.get('new_line1') or '').strip()
    new_line2 = (request.form.get('new_line2') or '').strip()
    new_city = (request.form.get('new_city') or '').strip()
    new_state = (request.form.get('new_state') or '').strip()
    new_postal = (request.form.get('new_postal_code') or '').strip()
    new_country = (request.form.get('new_country') or 'India').strip()
    new_is_default = 1 if request.form.get('new_is_default') else 0

    address_id_to_use = None
    conn = None
    cursor = None

    # If the user filled the new address required fields, prefer inserting that address.
    wants_new_address = bool(new_name or new_line1 or new_city or new_state or new_postal)

    try:
        conn = get_db()
        cursor = conn.cursor()

        if wants_new_address:
            # basic server-side validation for required new fields
            if not (new_name and new_line1 and new_city and new_state and new_postal):
                flash("Please fill name, address line 1, city, state and postal code for new address.", "warning")
                return redirect(url_for('main.checkout'))

            insert_q = """
                INSERT INTO addresses (customer_id, name, phone, line1, line2, city, state, postal_code, country, is_default)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """
            cursor.execute(insert_q, (customer_id, new_name, new_phone or None, new_line1, new_line2 or None,
                                      new_city, new_state, new_postal, new_country or 'India', new_is_default))
            address_id_to_use = cursor.lastrowid

            if new_is_default:
                # unset other defaults
                cursor.execute("UPDATE addresses SET is_default = 0 WHERE customer_id=%s AND address_id != %s",
                               (customer_id, address_id_to_use))

            conn.commit()

        else:
            # Use selected existing address if present
            if shipping_address_id:
                cursor.execute("SELECT address_id FROM addresses WHERE address_id=%s AND customer_id=%s",
                               (shipping_address_id, customer_id))
                row = cursor.fetchone()
                if not row:
                    flash("Selected address not found.", "danger")
                    return redirect(url_for('main.checkout'))
                address_id_to_use = int(shipping_address_id)
            else:
                flash("Please select a shipping address or provide a new one.", "warning")
                return redirect(url_for('main.checkout'))

    except Exception as e:
        if conn:
            conn.rollback()
        current_app.logger.exception("Error handling address in place_cart_order")
        flash("Error saving or validating address. Try again.", "danger")
        return redirect(url_for('main.checkout'))
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass

    # --- Compute totals ---
    try:
        subtotal = 0.0
        for it in cart:
            subtotal += float(it.get('price', 0.0)) * int(it.get('qty', 0))
    except Exception:
        flash("Invalid cart data.", "danger")
        return redirect(url_for('main.view_cart'))

    shipping_cost = 50.0
    order_total = subtotal + shipping_cost
    amount_paise = int(round(order_total * 100))

    # --- Create Razorpay client and create an order (authorize only) ---
    RZP_KEY_ID = os.environ.get('RAZORPAY_KEY_ID')
    RZP_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET')
    if not RZP_KEY_ID or not RZP_KEY_SECRET:
        flash("Payment gateway not configured.", "danger")
        return redirect(url_for('main.view_cart'))

    try:
        rz_module = globals().get('razorpay')
        if not rz_module:
            import razorpay as rz_module
        client = rz_module.Client(auth=(RZP_KEY_ID, RZP_KEY_SECRET))
    except Exception:
        current_app.logger.exception("Razorpay init error")
        flash("Payment gateway error. Contact admin.", "danger")
        return redirect(url_for('main.view_cart'))

    try:
        razorpay_order = client.order.create({
            'amount': amount_paise,
            'currency': 'INR',
            'payment_capture': 0   # authorize-only; capture later after DB checks
        })
        razorpay_order_id = razorpay_order.get('id')
    except Exception:
        current_app.logger.exception("Razorpay create order failed")
        flash("Error creating payment order. Try again.", "danger")
        return redirect(url_for('main.view_cart'))

    # Save pending order into session (used by payment_success)
    session['pending_order'] = {
        'customer_id': customer_id,
        'cart': cart,
        'subtotal': subtotal,
        'shipping_cost': shipping_cost,
        'total_amount': order_total,
        'amount_paise': amount_paise,
        'shipping_address_id': address_id_to_use,
        'razorpay_order_id': razorpay_order_id,
        'created_at': datetime.utcnow().isoformat()
    }
    session.modified = True

    # show the Razorpay checkout page
    return render_template('customer/checkout.html',
                           razorpay_key=RZP_KEY_ID,
                           razorpay_order_id=razorpay_order_id,
                           amount=amount_paise,
                           currency='INR')

# ---- Invoice PDF generation utility ----

def format_address(addr, include_email=None):
    if not addr:
        return ""
    fields = []
    if include_email:
        fields.append(include_email)
    fields.extend([
        addr.get('name') or '',
        addr.get('phone') or '',
        addr.get('line1') or '',
        addr.get('line2') or '',
        f"{addr.get('city') or ''}, {addr.get('state') or ''} {addr.get('postal_code') or ''}",
        addr.get('country') or ''
    ])
    return "<br/>".join([f for f in fields if f])

class FooterCanvas(Canvas):
    def showPage(self):
        self.draw_footer()
        self.draw_page_border()
        Canvas.showPage(self)

    def save(self):
        # Draw footer/border on last page but do NOT call showPage()
        self.draw_footer()
        self.draw_page_border()
        Canvas.save(self)

    def draw_footer(self):
        self.saveState()
        self.setFont('Helvetica', 9)
        footer = f"Champalal & Sons | Page {self._pageNumber}"
        self.setFillColor(colors.darkgrey)
        bottom_y = 11 * mm
        self.drawRightString(A4[0] - 18 * mm, bottom_y, footer)
        self.restoreState()

    def draw_page_border(self):
        self.saveState()
        self.setStrokeColor(colors.black)
        self.setLineWidth(1)
        self.rect(10, 10, A4[0] - 20, A4[1] - 20)
        self.restoreState()

def generate_invoice_pdf(order_id, payment_db_id, invoice_dir=None):
    """
    Generate a professional invoice PDF.
    Uses 'Rs.' (text) for currency and displays only the shipping address (falls back to billing if absent).
    Returns filename on success or None on failure.
    """
    try:
        if invoice_dir is None:
            invoice_dir = current_app.config.get('INVOICE_DIR') or os.environ.get('INVOICE_DIR')
        if not invoice_dir:
            invoice_dir = os.path.join(current_app.instance_path, 'invoices')
        os.makedirs(invoice_dir, exist_ok=True)
    except Exception:
        current_app.logger.exception("Cannot create/access invoice directory")
        return None

    # fetch DB rows
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM orders WHERE order_id = %s", (order_id,))
        order = cursor.fetchone()
        if not order:
            current_app.logger.error("generate_invoice_pdf: order %s not found", order_id)
            return None

        cursor.execute("SELECT * FROM customers WHERE customer_id = %s", (order.get('customer_id'),))
        customer = cursor.fetchone() or {}

        # default billing (customer default), shipping if provided
        cursor.execute(
            "SELECT * FROM addresses WHERE customer_id = %s AND is_default = 1 ORDER BY address_id DESC LIMIT 1",
            (order.get('customer_id'),)
        )
        billing_addr = cursor.fetchone()
        ship_addr = None
        if order.get('shipping_address_id'):
            cursor.execute("SELECT * FROM addresses WHERE address_id = %s", (order.get('shipping_address_id'),))
            ship_addr = cursor.fetchone()

        cursor.execute("""
            SELECT oi.*, p.name AS product_name, pv.sku AS variant_sku
            FROM order_items oi
            LEFT JOIN products p ON p.product_id = oi.product_id
            LEFT JOIN product_variants pv ON pv.variant_id = oi.variant_id
            WHERE oi.order_id = %s
        """, (order_id,))
        items = cursor.fetchall() or []

        cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_db_id,))
        payment = cursor.fetchone() or {}

    except Exception as e:
        current_app.logger.exception("Error fetching DB rows for invoice: %s", e)
        return None
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass

    ts = int(time.time())
    fname = secure_filename(f"invoice_order{order_id}_{ts}.pdf")
    out_path = os.path.join(invoice_dir, fname)

    try:
        doc = SimpleDocTemplate(out_path, pagesize=A4,
                                leftMargin=18*mm, rightMargin=18*mm,
                                topMargin=18*mm, bottomMargin=18*mm)

        styles = getSampleStyleSheet()
        styleN = styles['Normal']
        styleN.fontName = "Helvetica"
        styleN.fontSize = 10
        styleSmall = ParagraphStyle('small', parent=styleN, fontSize=9, leading=11)
        styleHeader = ParagraphStyle('header', parent=styleN, fontSize=12, fontName='Helvetica-Bold')
        styleTableHead = ParagraphStyle('tablehead', parent=styleN, fontSize=11, fontName='Helvetica-Bold', textColor=colors.whitesmoke, alignment=TA_RIGHT)

        elems = []

        company_name = "Champalal & Sons"
        company_addr = "Beside Madhubani PO, Madhubani Bazar<br/>Purnia, Bihar, India - 854301"
        company_gst = "GSTIN: 10AAEHV2589P1ZL"

        created_at_str = ""
        if order.get("created_at"):
            created_at_str = order.get("created_at").strftime("%Y-%m-%d %H:%M:%S")

        # Logo handling (tries several candidate places; scales to fit)
        logo_flowable = None
        logo_path = current_app.config.get("COMPANY_LOGO_PATH", "") or ""
        logo_path="C&S Logo.png"
        candidate_paths = []
        if logo_path:
            if os.path.isabs(logo_path):
                candidate_paths.append(logo_path)
            else:
                candidate_paths.extend([
                    os.path.join(current_app.root_path, logo_path),
                    os.path.join(current_app.instance_path, logo_path),
                    os.path.join(current_app.root_path, "static", logo_path),
                    os.path.join(current_app.root_path, "static", "images", logo_path),
                ])
        logo_path_final = None
        for p in candidate_paths:
            if p and os.path.exists(p) and os.path.isfile(p):
                logo_path_final = p
                break

        if logo_path_final:
            try:
                reader = ImageReader(logo_path_final)
                img_w_px, img_h_px = reader.getSize()
                max_logo_w = 50 * mm
                max_logo_h = 30 * mm
                aspect = float(img_w_px) / max(img_h_px, 1)
                logo_w = max_logo_w
                logo_h = logo_w / aspect
                if logo_h > max_logo_h:
                    logo_h = max_logo_h
                    logo_w = logo_h * aspect
                logo_flowable = Image(logo_path_final, width=logo_w, height=logo_h)
                logo_flowable.hAlign = 'LEFT'
            except Exception:
                current_app.logger.exception("Failed to load/scale company logo for invoice")
                logo_flowable = None

        # Header: logo + company info (left) and invoice meta (right)
        left_block = []
        if logo_flowable:
            left_block.append(logo_flowable)
            left_block.append(Spacer(1, 4))
        left_block.append(Paragraph(f"<b>{company_name}</b><br/>{company_addr}<br/>{company_gst}", styleN))
        right_meta = Paragraph(
            f"<b>Invoice:</b> {order_id}<br/><b>Order date:</b> {created_at_str}<br/><b>Order ID:</b> {order.get('order_id')}",
            styleN
        )
        header_table = Table([[left_block, right_meta]], colWidths=[doc.width * 0.66, doc.width * 0.34])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        elems.append(header_table)
        elems.append(Spacer(1, 10))

        # Show only SHIPPING address (fallback to billing if shipping missing)
        shipping_display_addr = ship_addr or billing_addr
        shipping_email = customer.get("email") if customer else ""

        payment_lines = [
            f"Method: {payment.get('method', '-') or '-'}",
            f"Payment ID: {payment.get('gateway_payment_id', '-') or '-'}",
            f"Status: {payment.get('status', '-') or '-'}",
        ]
        payment_par = Paragraph("<b>PAYMENT</b><br/>" + "<br/>".join(payment_lines), styleN)

        # Detail table: SHIP TO (left) and PAYMENT (right)
        detail_table = Table([
            [
                Paragraph(f"<b>SHIP TO</b><br/>{format_address(shipping_display_addr, shipping_email)}", styleN),
                payment_par
            ]
        ], colWidths=[doc.width*0.66, doc.width*0.34])
        detail_table.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 0.9, colors.HexColor('#333333')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ]))
        elems.append(detail_table)
        elems.append(Spacer(1, 12))

        # Items table: show product name, SKU, qty, unit (Rs.), amount (Rs.)
        table_data = [
            [
                Paragraph("<b>ITEM</b>", styleTableHead),
                Paragraph("<b>SKU</b>", styleTableHead),
                Paragraph("<b>QTY</b>", styleTableHead),
                Paragraph("<b>UNIT (Rs.)</b>", styleTableHead),
                Paragraph("<b>AMOUNT (Rs.)</b>", styleTableHead)
            ]
        ]
        for it in items:
            qty = int(it.get('quantity') or 0)
            unit_price = float(it.get('unit_price') or 0.0)
            total_price = float(it.get('total_price') or (unit_price * qty))
            table_data.append([
                Paragraph(f"<b>{it.get('product_name') or 'Product'}</b>", styleN),
                it.get('variant_sku') or '-',
                str(qty),
                f"Rs.{unit_price:,.2f}",
                f"Rs.{total_price:,.2f}"
            ])

        table = Table(table_data, colWidths=[doc.width*0.36, doc.width*0.20, doc.width*0.10, doc.width*0.17, doc.width*0.17], repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.9, colors.HexColor('#222222')),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#222222')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 11),
            ('FONTSIZE', (0,1), (-1,-1), 10),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (2,1), (-1,-1), 'RIGHT'),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,0), 8),
            ('TOPPADDING', (0,0), (-1,0), 8),
        ]))
        elems.append(table)
        elems.append(Spacer(1, 14))

        # Totals (use Rs.)
        shipping_cost = float(order.get('shipping_cost') or 0.0)
        total_amount = float(order.get('total_amount') or 0.0)
        subtotal = total_amount - shipping_cost
        totals_data = [
            ['Subtotal', f"Rs.{subtotal:,.2f}"],
            ['Shipping', f"Rs.{shipping_cost:,.2f}"],
            ['Total', f"Rs.{total_amount:,.2f}"]
        ]
        totals_table = Table(totals_data, colWidths=[doc.width*0.74, doc.width*0.26])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('LINEABOVE', (0,-1), (-1,-1), 1.2, colors.HexColor('#222222')),
            ('LINEBELOW', (0,-1), (-1,-1), 2.2, colors.HexColor('#222222')),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ]))
        elems.append(totals_table)
        elems.append(Spacer(1, 10))

        # Notes
        notes = Paragraph(
            "Notes: Inspect goods in delivery agent's presence. Report damage at delivery to be eligible for returns/refund.",
            styleSmall
        )
        elems.append(notes)

        # Page decorator: border, watermark, footer
        def draw_page(canvas, doc):
            canvas.saveState()
            # border
            canvas.setStrokeColor(colors.HexColor('#444444'))
            canvas.setLineWidth(0.8)
            left = doc.leftMargin - 6
            bottom = doc.bottomMargin - 6
            width = A4[0] - doc.leftMargin - doc.rightMargin + 12
            height = A4[1] - doc.topMargin - doc.bottomMargin + 12
            canvas.rect(left, bottom, width, height)

            # watermark (center, rotated, subtle)
            canvas.setFont('Helvetica', 40)
            canvas.setFillColor(colors.HexColor('#ededed'))
            canvas.translate(A4[0]/2.0, A4[1]/2.0)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, company_name)
            canvas.restoreState()

            # footer (right)
            canvas.saveState()
            footer_txt = f"{company_name} | Page {canvas.getPageNumber()}"
            canvas.setFont('Helvetica', 9)
            canvas.setFillColor(colors.darkgrey)
            canvas.drawRightString(A4[0] - doc.rightMargin, 12 * mm, footer_txt)
            canvas.restoreState()

        # Build (use onFirstPage/onLaterPages to avoid duplicate-blank page issues)
        doc.build(elems, onFirstPage=draw_page, onLaterPages=draw_page)

        return fname

    except Exception as e:
        current_app.logger.exception("generate_invoice_pdf failed: %s", e)
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return None
# ---------- Modified payment_success (replace your existing function) ----------
@main.route('/payment_success', methods=['POST'])
def payment_success():
    data = request.get_json() or {}
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')

    if not (razorpay_payment_id and razorpay_order_id and razorpay_signature):
        return jsonify({'status': 'error', 'error': 'Missing payment parameters'}), 400

    pending = session.get('pending_order')
    if not pending or pending.get('razorpay_order_id') != razorpay_order_id:
        return jsonify({'status': 'error', 'error': 'No matching pending order in session'}), 400

    # Razorpay client + signature verify (keeps previous logic)
    RZP_KEY_ID = os.environ.get('RAZORPAY_KEY_ID')
    RZP_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET')
    if not RZP_KEY_ID or not RZP_KEY_SECRET:
        return jsonify({'status': 'error', 'error': 'Payment gateway not configured'}), 500

    try:
        rz_module = globals().get('razorpay')
        if not rz_module:
            import razorpay as rz_module
        client = rz_module.Client(auth=(RZP_KEY_ID, RZP_KEY_SECRET))
        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })
    except Exception as e:
        current_app.logger.exception("Razorpay signature verification failed")
        return jsonify({'status': 'error', 'error': f'Verification failed: {e}'}), 400

    # fetch payment details from Razorpay
    try:
        payment_obj = client.payment.fetch(razorpay_payment_id)
        payment_status = payment_obj.get('status')  # 'authorized' | 'captured', etc.
    except Exception as e:
        current_app.logger.exception("Failed to fetch payment from Razorpay")
        return jsonify({'status': 'error', 'error': 'Failed to fetch payment details'}), 500

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cart = pending.get('cart', [])
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart empty in pending order'}), 400

        # lock required variant rows
        variant_ids = sorted({int(item['variant_id']) for item in cart})
        for vid in variant_ids:
            cursor.execute("SELECT variant_id, stock_count FROM product_variants WHERE variant_id = %s FOR UPDATE", (vid,))
            v = cursor.fetchone()
            if not v:
                conn.rollback()
                return jsonify({'status': 'error', 'error': f'Variant {vid} missing'}), 400

        # validate stock quantities
        for it in cart:
            vid = int(it['variant_id'])
            qty = int(it['qty'])
            cursor.execute("SELECT stock_count FROM product_variants WHERE variant_id = %s", (vid,))
            row = cursor.fetchone()
            current_stock = int(row.get('stock_count', 0))
            if current_stock < qty:
                conn.rollback()
                # if captured try refund, else inform client
                if payment_status == 'captured':
                    try:
                        client.payment.refund(razorpay_payment_id, {'speed': 'standard'})
                    except Exception:
                        current_app.logger.exception("Refund attempt failed after stock shortage")
                    return jsonify({'status': 'error', 'error': 'Insufficient stock; payment refunded'}), 400
                else:
                    return jsonify({'status': 'error', 'error': 'Insufficient stock; payment not captured'}), 400

        # capture if authorized
        if payment_status == 'authorized':
            try:
                client.payment.capture(razorpay_payment_id, pending.get('amount_paise'))
                payment_status_after = 'captured'
            except Exception as e:
                conn.rollback()
                current_app.logger.exception("Payment capture failed")
                return jsonify({'status': 'error', 'error': 'Payment capture failed: ' + str(e)}), 500
        else:
            payment_status_after = payment_status

        # insert order
        customer_id = pending.get('customer_id')
        shipping_address_id = pending.get('shipping_address_id')
        shipping_cost = pending.get('shipping_cost', 0.0)
        total_amount = pending.get('total_amount')

        cursor.execute("""
            INSERT INTO orders (customer_id, total_amount, currency, payment_status, payment_gateway, status, shipping_address_id, shipping_cost)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            customer_id,
            total_amount,
            'INR',
            'paid' if payment_status_after == 'captured' else 'pending',
            'razorpay',
            'processing' if payment_status_after == 'captured' else 'waiting to be accepted',
            shipping_address_id,
            shipping_cost
        ))
        order_id = cursor.lastrowid

        # insert order_items and decrement stock
        for it in cart:
            product_id = int(it['product_id'])
            variant_id = int(it['variant_id'])
            qty = int(it['qty'])
            unit_price = float(it['price'])
            cursor.execute("INSERT INTO order_items (order_id, product_id, variant_id, quantity, unit_price) VALUES (%s,%s,%s,%s,%s)",
                           (order_id, product_id, variant_id, qty, unit_price))
            cursor.execute("UPDATE product_variants SET stock_count = stock_count - %s WHERE variant_id = %s", (qty, variant_id))

        # insert payments row
        cursor.execute("""
            INSERT INTO payments (order_id, gateway_payment_id, gateway_signature, amount, currency, status, raw_response)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (order_id, razorpay_payment_id, razorpay_signature, total_amount, 'INR',
              'captured' if payment_status_after == 'captured' else payment_status_after,
              json.dumps(payment_obj)))
        payment_db_id = cursor.lastrowid

        # link payment to order
        cursor.execute("UPDATE orders SET last_payment_id = %s WHERE order_id = %s", (payment_db_id, order_id))

        conn.commit()
        
        # Attempt to generate invoice PDF (best-effort). If it fails, log but do not break order.
        try:
            invoice_filename = generate_invoice_pdf(order_id, payment_db_id)
            if invoice_filename:
                # store invoice filename in payments.invoice_path
                conn2 = get_db()
                cur2 = conn2.cursor()
                # store filename only (invoice_dir configured in app). You can store absolute path if you prefer.
                cur2.execute("UPDATE payments SET invoice_path = %s WHERE id = %s", (invoice_filename, payment_db_id))
                conn2.commit()
                cur2.close()
                conn2.close()
            else:
                current_app.logger.warning("Invoice generation returned no filename for order %s", order_id)
        except Exception as e:
            current_app.logger.exception("Invoice generation failed for order %s: %s", order_id, e)

        # clear session pending and cart
        session.pop('pending_order', None)
        session.pop('cart', None)
        session.modified = True

        return jsonify({'status': 'ok', 'order_id': order_id}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        current_app.logger.exception("Error finalizing order after payment")
        return jsonify({'status': 'error', 'error': str(e)}), 500
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass


# ---------- Secure invoice download route ----------
@main.route('/invoice/download', methods=['POST'])
def download_invoice():
    """
    POST endpoint to download invoice for an order.
    Accepts form param 'order_id'.
    Customers may download invoices for their own orders.
    Owners (admins) may download any invoice.
    """
    # require login
    if 'customer_id' not in session and 'owner_id' not in session and not session.get('is_owner', False):
        flash("Please login to download invoice", "warning")
        return redirect(url_for('main.login'))

    # decide redirect target helper based on caller type (owner vs customer)
    is_owner = ('owner_id' in session) or session.get('is_owner', False)
    def redirect_owner_or_customer(endpoint_customer='main.view_orders', endpoint_owner='main.owner_view_orders'):
        return redirect(url_for(endpoint_owner if is_owner else endpoint_customer))

    order_id = request.form.get('order_id')
    if not order_id:
        flash("Missing order id", "warning")
        return redirect_owner_or_customer()

    try:
        order_id = int(order_id)
    except ValueError:
        flash("Invalid order id", "danger")
        return redirect_owner_or_customer()

    # DB lookup
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT customer_id FROM orders WHERE order_id = %s", (order_id,))
        o = cursor.fetchone()
        if not o:
            flash("Order not found", "danger")
            return redirect_owner_or_customer()

        # permission: owner/admin can download any invoice
        if not is_owner:
            # must be the customer who owns the order
            if 'customer_id' not in session or int(o.get('customer_id')) != int(session.get('customer_id')):
                flash("Permission denied", "danger")
                return redirect_owner_or_customer()

        # fetch latest payment row that has invoice_path
        cursor.execute("""
            SELECT invoice_path
            FROM payments
            WHERE order_id = %s AND invoice_path IS NOT NULL AND invoice_path != ''
            ORDER BY id DESC
            LIMIT 1
        """, (order_id,))
        p = cursor.fetchone()
        if not p or not p.get('invoice_path'):
            flash("Invoice not available", "warning")
            return redirect_owner_or_customer()

        invoice_fname = p.get('invoice_path')

        # determine invoice dir (use configured or fallback)
        invoice_dir = current_app.config.get('INVOICE_DIR')
        if not invoice_dir:
            invoice_dir = os.path.join(current_app.instance_path, 'invoices')

        # Build safe absolute path and ensure it's within invoice_dir
        invoice_dir_abs = os.path.abspath(invoice_dir)
        fullpath = os.path.abspath(os.path.join(invoice_dir_abs, invoice_fname))

        # security: ensure final path is inside invoice_dir_abs (prevent path traversal)
        if not (fullpath == invoice_dir_abs or fullpath.startswith(invoice_dir_abs + os.sep)):
            current_app.logger.error("Potential invoice path traversal attempt: %s", fullpath)
            flash("Invalid invoice path", "danger")
            return redirect_owner_or_customer()

        if not os.path.exists(fullpath) or not os.path.isfile(fullpath):
            current_app.logger.error("Invoice file missing: %s", fullpath)
            flash("Invoice file missing", "danger")
            return redirect_owner_or_customer()

        # send file for download
        # If your Flask version is older and does not support download_name,
        # use attachment_filename=<name> instead.
        return send_file(fullpath, as_attachment=True, download_name=os.path.basename(fullpath))

    except Exception as e:
        current_app.logger.exception("Error while trying to download invoice for order %s: %s", order_id, e)
        flash("Unable to download invoice. Try again.", "danger")
        return redirect_owner_or_customer()
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass



# -----------------view orders--------------



@main.route('/orders')
@nocache
def view_orders():
    # -------------- auth (unchanged) --------------
    if 'customer_id' not in session:
        flash("Please log in to view orders.", "warning")
        return redirect('/login')

    # ---------- device detection (server-side) ----------
    ua_string = request.headers.get('User-Agent', '') or ''
    is_mobile = False
    try:
        # user-agents is recommended: pip install user-agents
        ua = ua_parse(ua_string)
        # treat tablets as mobile for your mobile template — tweak if needed
        is_mobile = bool(ua.is_mobile or ua.is_tablet)
    except Exception:
        # If user_agents isn't available or parse fails, default to desktop behavior
        is_mobile = False

    # Choose templates depending on device
    fragment_template = 'customer/_orders_fragment_mobile.html' if is_mobile else 'customer/_orders_fragment.html'
    full_template = 'customer/view_orders_mobile.html' if is_mobile else 'customer/view_orders.html'

    # -------------- request params / pagination (unchanged) --------------
    customer_id = int(session['customer_id'])
    status = request.args.get('status')  # e.g. processing,confirmed,out for delivery,delivered,cancelled,refunded
    q = (request.args.get('q') or '').strip()
    sort = request.args.get('sort','date_desc')  # date_desc,date_asc,total_desc,total_asc

    # pagination
    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    per_page = 10
    offset = (page - 1) * per_page

    order_by_map = {
        'date_desc': 'o.order_date DESC, o.order_id DESC',
        'date_asc': 'o.order_date ASC, o.order_id ASC',
        'total_desc': 'o.total_amount DESC, o.order_date DESC',
        'total_asc': 'o.total_amount ASC, o.order_date DESC'
    }
    order_by = order_by_map.get(sort, order_by_map['date_desc'])

    # Build filter clauses
    where_clauses = ["o.customer_id = %s"]
    params = [customer_id]

    if status and status.lower() != 'all':
        where_clauses.append("o.status = %s")
        params.append(status)

    # Case-insensitive search (Postgres uses TEXT)
    if q:
        q_lower = f"%{q.lower()}%"
        where_clauses.append("""(
            LOWER(CAST(o.order_id AS TEXT)) LIKE %s
            OR LOWER(p.name) LIKE %s
            OR LOWER(pv.sku) LIKE %s
            OR LOWER(ai.name) LIKE %s
            OR LOWER(ai.line1) LIKE %s
        )""")
        params.extend([q_lower, q_lower, q_lower, q_lower, q_lower])

    where_sql = " AND ".join(where_clauses)

    # First: fetch order_ids for this page. Use a subquery so ORDER BY expressions are present in select list
    order_ids = []
    has_more = False
    try:
        conn = get_db()
        cur = conn.cursor()
        # ask for per_page+1 to detect has_more
        q_order_ids = f"""
            SELECT oids.order_id FROM (
                SELECT o.order_id, o.order_date, o.total_amount
                FROM orders o
                JOIN order_items oi ON o.order_id = oi.order_id
                JOIN products p ON oi.product_id = p.product_id
                LEFT JOIN product_variants pv ON oi.variant_id = pv.variant_id
                LEFT JOIN addresses ai ON o.shipping_address_id = ai.address_id
                WHERE {where_sql}
                GROUP BY o.order_id, o.order_date, o.total_amount
                ORDER BY {order_by}
            ) AS oids
            LIMIT %s OFFSET %s
        """
        params_page = list(params) + [per_page + 1, offset]
        cur.execute(q_order_ids, tuple(params_page))
        rows_ids = cur.fetchall()
        cur.close()
        conn.close()
        if rows_ids:
            order_ids = [r[0] for r in rows_ids]
    except Exception as e:
        current_app.logger.exception("Could not fetch order ids for pagination: %s", str(e))
        order_ids = []

    if len(order_ids) > per_page:
        has_more = True
        order_ids = order_ids[:per_page]

    orders = OrderedDict()
    if order_ids:
        try:
            conn = get_db()
            cur = conn.cursor(dictionary=True)

            placeholders = ','.join(['%s'] * len(order_ids))

            # preserve page order using CASE WHEN ... THEN index END
            case_parts = []
            case_params = []
            for idx, oid in enumerate(order_ids):
                case_parts.append(f"WHEN o.order_id = %s THEN {idx}")
                case_params.append(oid)
            case_sql = "CASE " + " ".join(case_parts) + f" ELSE {len(order_ids)} END"

            sql = f"""
                SELECT
                    o.order_id,
                    o.order_date,
                    o.total_amount,
                    o.currency,
                    o.payment_status,
                    o.payment_gateway,
                    o.shipping_cost,
                    o.status AS order_status,
                    o.last_payment_id,
                    ai.address_id AS shipping_address_id,
                    ai.name AS shipping_name,
                    ai.phone AS shipping_phone,
                    ai.line1 AS shipping_line1,
                    ai.line2 AS shipping_line2,
                    ai.city AS shipping_city,
                    ai.state AS shipping_state,
                    ai.postal_code AS shipping_postal_code,
                    ai.country AS shipping_country,
                    oi.order_item_id,
                    oi.product_id,
                    oi.variant_id,
                    oi.quantity,
                    oi.unit_price,
                    oi.total_price,
                    p.name AS product_name,
                    p.image_path,
                    pv.sku AS variant_sku,
                    pv.size AS variant_size,
                    pv.color AS variant_color
                FROM orders o
                JOIN order_items oi ON o.order_id = oi.order_id
                JOIN products p ON oi.product_id = p.product_id
                LEFT JOIN product_variants pv ON oi.variant_id = pv.variant_id
                LEFT JOIN addresses ai ON o.shipping_address_id = ai.address_id
                WHERE o.order_id IN ({placeholders})
                ORDER BY {case_sql}
            """
            cur.execute(sql, tuple(order_ids + case_params))
            rows = cur.fetchall()
            cur.close()
            conn.close()
        except Exception as e:
            current_app.logger.exception("Could not fetch order rows: %s", str(e))
            rows = []

        # Fetch images
        variant_ids = set()
        product_ids = set()
        for r in rows:
            if r.get('variant_id') not in (None, 0):
                try:
                    variant_ids.add(int(r.get('variant_id')))
                except Exception:
                    pass
            try:
                product_ids.add(int(r.get('product_id')))
            except Exception:
                pass

        variant_image_map = {}
        product_image_map = {}

        if variant_ids or product_ids:
            try:
                conn = get_db()
                cur = conn.cursor(dictionary=True)
                clauses = []
                params_imgs = []
                if variant_ids:
                    placeholders_v = ','.join(['%s'] * len(variant_ids))
                    clauses.append(f"variant_id IN ({placeholders_v})")
                    params_imgs.extend(list(variant_ids))
                if product_ids:
                    placeholders_p = ','.join(['%s'] * len(product_ids))
                    clauses.append(f"(variant_id IS NULL AND product_id IN ({placeholders_p}))")
                    params_imgs.extend(list(product_ids))
                where_img = " OR ".join(clauses)
                qimg = f"""
                    SELECT product_id, variant_id, path, is_primary, position, image_id
                    FROM product_images
                    WHERE {where_img}
                    ORDER BY is_primary DESC, position ASC, image_id ASC
                """
                cur.execute(qimg, tuple(params_imgs))
                img_rows = cur.fetchall()
                cur.close()
                conn.close()

                for ir in img_rows:
                    vid = ir.get('variant_id')
                    pid = ir.get('product_id')
                    path = ir.get('path')
                    if vid not in (None, 0):
                        if vid not in variant_image_map:
                            variant_image_map[vid] = path
                    else:
                        if pid not in product_image_map:
                            product_image_map[pid] = path
            except Exception as e:
                current_app.logger.exception("Could not fetch product images for orders view: %s", str(e))

        # group items by order_id
        for r in rows:
            oid = r['order_id']
            if oid not in orders:
                orders[oid] = {
                    "order_date": r['order_date'],
                    "total_amount": r['total_amount'],
                    "currency": r.get('currency') or 'INR',
                    "payment_status": r.get('payment_status'),
                    "payment_gateway": r.get('payment_gateway'),
                    "shipping_cost": r.get('shipping_cost') or 0.00,
                    "order_status": r.get('order_status'),
                    "last_payment_id": r.get('last_payment_id'),
                    "shipping_address": {
                        "address_id": r.get('shipping_address_id'),
                        "name": r.get('shipping_name'),
                        "phone": r.get('shipping_phone'),
                        "line1": r.get('shipping_line1'),
                        "line2": r.get('shipping_line2'),
                        "city": r.get('shipping_city'),
                        "state": r.get('shipping_state'),
                        "postal_code": r.get('shipping_postal_code'),
                        "country": r.get('shipping_country'),
                    },
                    "items": []
                }

            chosen_image = None
            vid = r.get('variant_id')
            pid = r.get('product_id')
            if vid not in (None, 0) and vid in variant_image_map:
                chosen_image = variant_image_map.get(vid)
            elif pid in product_image_map:
                chosen_image = product_image_map.get(pid)
            else:
                chosen_image = r.get('image_path')

            orders[oid]['items'].append({
                "order_item_id": r['order_item_id'],
                "product_id": r['product_id'],
                "variant_id": r.get('variant_id'),
                "product_name": r['product_name'],
                "image_path": chosen_image,
                "quantity": r['quantity'],
                "unit_price": float(r['unit_price']) if r['unit_price'] is not None else None,
                "total_price": float(r['total_price']) if r['total_price'] is not None else (float(r['unit_price'] or 0) * int(r['quantity'] or 0)),
                "variant": {
                    "sku": r.get('variant_sku'),
                    "size": r.get('variant_size'),
                    "color": r.get('variant_color')
                },
                "reviewed": False,
                "rating": None,
                "review": None
            })

        # --- Fetch existing reviews (if any) for these order_ids for THIS customer ---
        try:
            order_ids_list = list(orders.keys())
            if order_ids_list:
                conn = get_db()
                cur = conn.cursor(dictionary=True)
                placeholders = ','.join(['%s'] * len(order_ids_list))
                params_rev = [customer_id] + order_ids_list
                qrev = f"""
                    SELECT product_id, order_id, rating, title, body, created_at
                    FROM product_reviews
                    WHERE customer_id = %s AND order_id IN ({placeholders})
                    ORDER BY created_at DESC
                """
                cur.execute(qrev, tuple(params_rev))
                rev_rows = cur.fetchall()
                cur.close()
                conn.close()

                review_map = {}
                for rr in rev_rows:
                    try:
                        key = (int(rr['order_id']), int(rr['product_id']))
                    except Exception:
                        continue
                    if key not in review_map:
                        review_map[key] = {
                            'rating': int(rr['rating']) if rr.get('rating') is not None else None,
                            'title': rr.get('title'),
                            'body': rr.get('body'),
                            'created_at': rr.get('created_at')
                        }

                for oid, order in orders.items():
                    for it in order['items']:
                        key = (int(oid), int(it['product_id']))
                        rev = review_map.get(key)
                        if rev:
                            it['reviewed'] = True
                            it['rating'] = rev.get('rating')
                            it['review'] = rev
                        else:
                            it['reviewed'] = False
                            it['rating'] = None
                            it['review'] = None
        except Exception as e:
            current_app.logger.exception("Could not fetch/attach reviews for orders view: %s", str(e))

    # If AJAX request: return rendered HTML fragment + has_more (choose mobile/desktop fragment based on detection)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            rendered = render_template(fragment_template, orders=orders)
            resp = jsonify(success=True, html=rendered, has_more=has_more)
            resp.status_code = 200
            # IMPORTANT: responses differ by user agent
            resp.headers['Vary'] = 'User-Agent'
            return resp
        except Exception as e:
            current_app.logger.exception("Error rendering orders fragment: %s", str(e))
            resp = jsonify(success=False, message="Rendering error")
            resp.status_code = 500
            resp.headers['Vary'] = 'User-Agent'
            return resp

    # Non-AJAX full render: render desktop or mobile full template
    try:
        resp = make_response(render_template(
            full_template,
            orders=orders,
            current_status=(status or 'all'),
            q=q,
            sort=sort,
            page=page,
            per_page=per_page,
            has_more=has_more
        ))
        # mark response as varying by UA so caches behave correctly
        resp.headers['Vary'] = 'User-Agent'
        return resp
    except Exception as e:
        current_app.logger.exception("Error rendering full orders page: %s", str(e))
        # fallback: render desktop template if mobile template rendering fails
        resp = make_response(render_template(
            "customer/view_orders.html",
            orders=orders,
            current_status=(status or 'all'),
            q=q,
            sort=sort,
            page=page,
            per_page=per_page,
            has_more=has_more
        ))
        resp.headers['Vary'] = 'User-Agent'
        return resp

# -----------------view order detail--------------

@main.route('/orders/<int:order_id>')
@nocache
def view_order(order_id):
    # auth
    if 'customer_id' not in session:
        flash("Please log in to view the order.", "warning")
        return redirect('/login')

    customer_id = int(session['customer_id'])

    # fetch order + items + product info + shipping address
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)

        # fetch order meta and shipping address
        q_order = """
            SELECT o.order_id, o.order_date, o.total_amount, o.currency, o.status as order_status,
                   o.shipping_cost, o.payment_status, o.payment_gateway, o.updated_at,
                   ai.address_id AS shipping_address_id, ai.name AS shipping_name, ai.phone AS shipping_phone,
                   ai.line1 AS shipping_line1, ai.line2 AS shipping_line2, ai.city AS shipping_city,
                   ai.state AS shipping_state, ai.postal_code AS shipping_postal_code, ai.country AS shipping_country
            FROM orders o
            LEFT JOIN addresses ai ON o.shipping_address_id = ai.address_id
            WHERE o.order_id = %s
            LIMIT 1
        """
        cur.execute(q_order, (order_id,))
        order_row = cur.fetchone()
        if not order_row:
            cur.close()
            conn.close()
            flash("Order not found.", "warning")
            return redirect(url_for('main.view_orders'))

        # ensure owner
        # If cursor returned dictionary without customer_id, fetch again to check owner
        cur_check = conn.cursor()
        cur_check.execute("SELECT customer_id FROM orders WHERE order_id = %s LIMIT 1", (order_id,))
        row_check = cur_check.fetchone()
        cur_check.close()
        if not row_check or int(row_check[0]) != customer_id:
            cur.close()
            conn.close()
            flash("You are not authorized to view this order.", "warning")
            return redirect(url_for('main.view_orders'))

        # fetch order items
        q_items = """
            SELECT oi.order_item_id, oi.product_id, oi.variant_id, oi.quantity, oi.unit_price, oi.total_price,
                   p.name AS product_name, p.image_path, pv.sku AS variant_sku, pv.size AS variant_size, pv.color AS variant_color
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            LEFT JOIN product_variants pv ON oi.variant_id = pv.variant_id
            WHERE oi.order_id = %s
            ORDER BY oi.order_item_id ASC
        """
        cur.execute(q_items, (order_id,))
        item_rows = cur.fetchall()

        # collect ids for images & reviews
        product_ids = set()
        variant_ids = set()
        for r in item_rows:
            try:
                product_ids.add(int(r.get('product_id')))
            except Exception:
                pass
            vid = r.get('variant_id')
            if vid not in (None, 0):
                try:
                    variant_ids.add(int(vid))
                except Exception:
                    pass

        # fetch images (prefer variant images)
        variant_image_map = {}
        product_image_map = {}
        if variant_ids or product_ids:
            try:
                cur_imgs = conn.cursor(dictionary=True)
                clauses = []
                params_imgs = []
                if variant_ids:
                    placeholders_v = ','.join(['%s'] * len(variant_ids))
                    clauses.append(f"variant_id IN ({placeholders_v})")
                    params_imgs.extend(list(variant_ids))
                if product_ids:
                    placeholders_p = ','.join(['%s'] * len(product_ids))
                    # fallback images where variant_id IS NULL for product images
                    clauses.append(f"(variant_id IS NULL AND product_id IN ({placeholders_p}))")
                    params_imgs.extend(list(product_ids))
                where_img = " OR ".join(clauses)
                qimg = f"""
                    SELECT product_id, variant_id, path, is_primary, position, image_id
                    FROM product_images
                    WHERE {where_img}
                    ORDER BY is_primary DESC, position ASC, image_id ASC
                """
                cur_imgs.execute(qimg, tuple(params_imgs))
                img_rows = cur_imgs.fetchall()
                cur_imgs.close()
                for ir in img_rows:
                    vid = ir.get('variant_id')
                    pid = ir.get('product_id')
                    path = ir.get('path')
                    if vid not in (None, 0):
                        if vid not in variant_image_map:
                            variant_image_map[vid] = path
                    else:
                        if pid not in product_image_map:
                            product_image_map[pid] = path
            except Exception as e:
                current_app.logger.exception("Could not fetch images for order detail: %s", str(e))

        # build items list
        items = []
        for r in item_rows:
            vid = r.get('variant_id')
            pid = r.get('product_id')
            if vid not in (None, 0) and vid in variant_image_map:
                chosen_image = variant_image_map.get(vid)
            elif pid in product_image_map:
                chosen_image = product_image_map.get(pid)
            else:
                chosen_image = r.get('image_path')

            items.append({
                "order_item_id": r['order_item_id'],
                "product_id": r['product_id'],
                "variant_id": r.get('variant_id'),
                "product_name": r['product_name'],
                "image_path": chosen_image,
                "quantity": r['quantity'],
                "unit_price": float(r['unit_price']) if r['unit_price'] is not None else None,
                "total_price": float(r['total_price']) if r['total_price'] is not None else None,
                "variant": {
                    "sku": r.get('variant_sku'),
                    "size": r.get('variant_size'),
                    "color": r.get('variant_color')
                },
                # will fill review info next
                "reviewed": False,
                "rating": None,
                "review": None
            })

        # fetch reviews for this specific order for this customer
        try:
            cur_rev = conn.cursor(dictionary=True)
            qrev = """
                SELECT product_id, rating, title, body, created_at
                FROM product_reviews
                WHERE customer_id = %s AND order_id = %s
                ORDER BY created_at DESC
            """
            cur_rev.execute(qrev, (customer_id, order_id))
            rev_rows = cur_rev.fetchall()
            cur_rev.close()

            if rev_rows:
                # map product_id -> most recent review for this order
                rev_map = {}
                for rr in rev_rows:
                    try:
                        pidk = int(rr.get('product_id'))
                    except Exception:
                        continue
                    if pidk not in rev_map:
                        rev_map[pidk] = {
                            "rating": int(rr.get('rating')) if rr.get('rating') is not None else None,
                            "title": rr.get('title'),
                            "body": rr.get('body'),
                            "created_at": rr.get('created_at')
                        }
                for it in items:
                    pidk = int(it['product_id'])
                    if pidk in rev_map:
                        it['reviewed'] = True
                        it['rating'] = rev_map[pidk].get('rating')
                        it['review'] = rev_map[pidk]
        except Exception as e:
            current_app.logger.exception("Could not fetch reviews for order detail: %s", str(e))

        # prepare order object for template
        order = {
            "order_id": order_row['order_id'],
            "order_date": order_row['order_date'],
            "total_amount": float(order_row['total_amount']) if order_row.get('total_amount') is not None else 0.0,
            "currency": order_row.get('currency') or 'INR',
            "order_status": order_row.get('order_status'),
            "shipping_cost": float(order_row.get('shipping_cost') or 0.0),
            "payment_status": order_row.get('payment_status'),
            "payment_gateway": order_row.get('payment_gateway'),
            "updated_at": order_row.get('updated_at'),
            "shipping_address": order_row.get('shipping_address') if 'shipping_address' in order_row else {
                "address_id": order_row.get('shipping_address_id'),
                "name": order_row.get('shipping_name'),
                "phone": order_row.get('shipping_phone'),
                "line1": order_row.get('shipping_line1'),
                "line2": order_row.get('shipping_line2'),
                "city": order_row.get('shipping_city'),
                "state": order_row.get('shipping_state'),
                "postal_code": order_row.get('shipping_postal_code'),
                "country": order_row.get('shipping_country'),
            },
            "items": items
        }

        cur.close()
        conn.close()

    except Exception as e:
        current_app.logger.exception("Error building order detail page: %s", str(e))
        try:
            cur.close()
        except:
            pass
        try:
            conn.close()
        except:
            pass
        flash("Could not load order information. Please try again.", "warning")
        return redirect(url_for('main.view_orders'))

    # render mobile template (we assume mobile here; if you detect device switch as before, you may choose templates)
    try:
        return render_template('customer/view_order_mobile.html', order=order)
    except Exception as e:
        current_app.logger.exception("Error rendering order detail template: %s", str(e))
        # fallback to desktop template if exists
        return redirect(url_for('main'))


@main.route('/submit_review', methods=['POST'])
@nocache
def submit_review():
    if 'customer_id' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Please login to submit a review."), 401
        flash("Please login to submit a review.", "warning")
        return redirect(url_for('main.login'))

    customer_id = int(session['customer_id'])
    product_id = request.form.get('product_id', type=int)
    variant_id = request.form.get('variant_id', type=int)
    order_id = request.form.get('order_id', type=int)
    rating = request.form.get('rating', type=int)
    title = (request.form.get('title') or '').strip()
    body = (request.form.get('body') or '').strip()

    if not product_id or not order_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Missing product or order information."), 400
        flash("Missing product or order information.", "danger")
        return redirect(url_for('main.view_orders'))

    if not rating or rating < 1 or rating > 5:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Rating must be between 1 and 5."), 400
        flash("Rating must be between 1 and 5.", "warning")
        return redirect(url_for('main.view_orders'))

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        # verify order belongs to customer and is delivered
        cur.execute("SELECT status, customer_id FROM orders WHERE order_id = %s LIMIT 1", (order_id,))
        row = cur.fetchone()
        if not row:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message="Order not found."), 404
            flash("Order not found.", "danger")
            return redirect(url_for('main.view_orders'))

        if int(row.get('customer_id')) != customer_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message="You are not authorized to review for this order."), 403
            flash("You are not authorized to review for this order.", "danger")
            return redirect(url_for('main.view_orders'))

        order_status = (row.get('status') or '').strip().lower()
        if order_status != 'delivered':
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message="You can only review products from delivered orders."), 400
            flash("You can only review products from delivered orders.", "warning")
            return redirect(url_for('main.view_orders'))

        # verify the product was part of the order (and variant if provided)
        if variant_id:
            cur.execute("SELECT 1 FROM order_items WHERE order_id = %s AND product_id = %s AND variant_id = %s LIMIT 1",
                        (order_id, product_id, variant_id))
        else:
            cur.execute("SELECT 1 FROM order_items WHERE order_id = %s AND product_id = %s LIMIT 1", (order_id, product_id))
        if not cur.fetchone():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message="This product was not part of the selected order."), 400
            flash("This product was not part of the selected order.", "danger")
            return redirect(url_for('main.view_orders'))

        # prevent duplicate review for the same (product, customer, order)
        cur.execute("SELECT 1 FROM product_reviews WHERE product_id = %s AND customer_id = %s AND order_id = %s LIMIT 1",
                    (product_id, customer_id, order_id))
        if cur.fetchone():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message="You have already reviewed this product for that order."), 409
            flash("You have already reviewed this product for that order.", "info")
            return redirect(url_for('main.view_orders'))

        # insert review (is_verified_purchase = 1 because we verified the order)
        cur.execute("""
            INSERT INTO product_reviews
              (product_id, customer_id, rating, title, body, is_verified_purchase, order_id, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (product_id, customer_id, rating, title or None, body or None, 1, order_id))

        # Recalculate aggregate rating and count for the product and update products table.
        cur.execute("""
            SELECT COUNT(*) AS cnt, AVG(rating) AS avg_rating
            FROM product_reviews
            WHERE product_id = %s
        """, (product_id,))
        agg = cur.fetchone()
        if isinstance(agg, dict):
            cnt = int(agg.get('cnt') or 0)
            avg = float(agg.get('avg_rating')) if agg.get('avg_rating') is not None else 0.0
        else:
            cnt = int(agg[0]) if agg and agg[0] is not None else 0
            avg = float(agg[1]) if agg and agg[1] is not None else 0.0

        avg_rounded = round(avg, 2)

        cur.execute("""
            UPDATE products
            SET rating_avg = %s,
                reviews_count = %s,
                updated_at = NOW()
            WHERE product_id = %s
        """, (avg_rounded, cnt, product_id))

        conn.commit()

        # If AJAX -> return JSON payload with info for frontend to update inline stars
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            created_at = datetime.utcnow().isoformat() + 'Z'
            return jsonify(success=True,
                           message="Thank you — your review has been submitted.",
                           product_id=int(product_id),
                           variant_id=(int(variant_id) if variant_id else ""),
                           order_id=int(order_id),
                           rating=int(rating),
                           title=title or None,
                           body=body or None,
                           created_at=created_at), 200

        # Non-AJAX fallback: original behavior
        flash("Thank you — your review has been submitted.", "success")
        return redirect(url_for('main.view_orders'))

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Error saving review and updating product aggregates: %s", str(e))

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="An error occurred while saving your review. Please try again."), 500

        flash("An error occurred while saving your review. Please try again.", "danger")
        return redirect(url_for('main.view_orders'))
    finally:
        try: cur.close()
        except: pass
        try: conn.close()
        except: pass




# -------------------------request order cancellation---------------


@main.route('/request_order_cancellation', methods=['POST'])
@nocache
def request_order_cancellation():
    # ensure logged-in
    if 'customer_id' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Please log in."), 401
        return redirect(url_for('main.login'))

    # fetch order_id from frontend form
    order_id = request.form.get('order_id', type=int)
    if not order_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='Invalid order id.'), 400
        flash('Invalid order id.', 'warning')
        return redirect(url_for('main.view_orders'))

    try:
        customer_id = int(session.get('customer_id'))
    except (TypeError, ValueError):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='Session error. Please log in again.'), 401
        flash('Session error. Please log in again.', 'warning')
        return redirect(url_for('main.login'))

    conn = get_db()
    if conn is None:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='Database connection error.'), 500
        flash('Database connection error.', 'danger')
        return redirect(url_for('main.view_orders'))

    cur = None
    try:
        cur = conn.cursor()
        # fetch current status and owner
        cur.execute("SELECT status, customer_id FROM orders WHERE order_id = %s", (order_id,))
        row = cur.fetchone()
        if not row:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message='Order not found.'), 404
            flash('Order not found.', 'warning')
            return redirect(url_for('main.view_orders'))

        status_from_db, owner_id = row[0], row[1]

        # ensure the logged-in customer owns this order
        if owner_id != customer_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message='You are not authorized to modify this order.'), 403
            flash('You are not authorized to modify this order.', 'warning')
            return redirect(url_for('main.view_orders'))

        curr = (status_from_db or '').strip().lower()
        if curr in ('processing', 'confirmed'):
            # update to cancellation-request for this customer's order
            cur.execute(
                """
                UPDATE orders
                SET status = %s, updated_at = NOW()
                WHERE order_id = %s AND customer_id = %s
                """,
                ('cancellation-request', order_id, customer_id)
            )
            conn.commit()

            if cur.rowcount:
                msg = 'Cancellation request submitted successfully. We will review and update your order shortly.'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify(success=True, message=msg, order_id=order_id, new_status='cancellation-request'), 200
                flash(msg, 'success')
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify(success=False, message='Unable to update order. Please try again.'), 500
                flash('Unable to update order. Please try again.', 'danger')

        elif curr in ('cancellation-request', 'cancellation requested'):
            msg = 'A cancellation request is already in progress for this order.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message=msg, order_id=order_id, new_status=curr), 409
            flash(msg, 'info')
        elif curr in ('cancelled', 'refunded'):
            msg = 'This order has already been cancelled.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message=msg, order_id=order_id, new_status=curr), 400
            flash(msg, 'warning')
        else:
            msg = 'This order cannot be cancelled at its current stage.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(success=False, message=msg, order_id=order_id, new_status=curr), 400
            flash(msg, 'warning')

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Error while processing cancellation request: %s", str(e))
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='An error occurred while processing your request. Please try again later.'), 500
        flash('An error occurred while processing your request. Please try again later.', 'danger')
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass

    # Non-AJAX fallback — redirect to orders page
    return redirect(url_for('main.view_orders'))


#---------------------------------------------------owner section---------------------------------------------------


@main.route('/owner-index')
@nocache
def owner_index():
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    return render_template("owner/owner_index.html")
@main.route('/owner-logout')
def owner_logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect('/login')


# --------------------add product--------------------


# Keep your allowed_file and ALLOWED_IMAGE_EXT definition
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "avif"}

def allowed_file(filename):
    return bool(filename) and "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXT


# Modified add_product route (replace your original function with this)
@main.route('/add-product', methods=['GET', 'POST'])
@nocache
def add_product():
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    if request.method == 'POST':
        # ---------- Read product-level fields ----------
        name = (request.form.get('name') or '').strip()
        sku = (request.form.get('sku') or '').strip() or None
        brand = request.form.get('brand') or None
        category = request.form.get('category') or None
        short_description = request.form.get('short_description') or None
        description = request.form.get('description') or None
        currency = request.form.get('currency') or 'INR'
        total_stock_input = request.form.get('total_stock') or '0'
        try:
            stock_count = int(total_stock_input)
        except (ValueError, TypeError):
            stock_count = 0
        weight = request.form.get('weight') or None
        material = request.form.get('material') or None
        fit = request.form.get('fit') or None
        pattern = request.form.get('pattern') or None
        occasion = request.form.get('occasion') or None
        season = request.form.get('season') or None
        sustainability = request.form.get('sustainability') or None
        care_instructions = request.form.get('care_instructions') or None
        is_returnable = 1 if request.form.get('is_returnable') else 0
        is_active = 1 if request.form.get('is_active') else 0

        main_image = request.files.get('main_image')  # single main image
        additional_images = request.files.getlist('images')
        # Variant arrays
        variant_sizes = request.form.getlist('variant_size[]')
        variant_colors = request.form.getlist('variant_color[]')
        variant_color_hex = request.form.getlist('variant_color_hex[]')
        variant_skus = request.form.getlist('variant_sku[]')
        variant_prices = request.form.getlist('variant_price[]')
        variant_stocks = request.form.getlist('variant_stock[]')

        if not name:
            flash("Product name is required", "danger")
            return render_template('owner/add_product.html')

        conn = None
        cursor = None
        try:
            conn = get_db()   # assume this returns a psycopg2 connection (Postgres)
            cursor = conn.cursor()

            # generate SKU if not provided
            if not sku:
                base = ''.join(ch for ch in (name or 'prod') if ch.isalnum())[:20]
                sku = f"{base}{int(time.time()) % 10000}"

            # insert product (image_path set below if main image uploaded) - use RETURNING
            insert_product_q = """
                INSERT INTO products
                (name, brand, sku, category, short_description, description, image_path,
                 currency, stock_count, weight, material, fit, pattern, occasion,
                 season, sustainability, care_instructions, is_returnable, is_active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING product_id
            """
            product_values = (
                name, brand, sku, category, short_description, description, None,
                currency, 0, weight, material, fit, pattern, occasion,
                season, sustainability, care_instructions, is_returnable, is_active
            )
            cursor.execute(insert_product_q, product_values)
            product_id = cursor.fetchone()[0]
            current_app.logger.debug("[DEBUG] Inserted product_id=%s", product_id)

            # ---------- Save main product image to R2 (ONLY update products.image_path) ----------
            if main_image and getattr(main_image, 'filename', None) and allowed_file(main_image.filename):
                orig = secure_filename(main_image.filename)
                unique = f"{product_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                filename = f"{unique}_{orig}"
                key = f"products/{product_id}/main/{filename}"
                try:
                    url = upload_to_r2(main_image, key)
                    # store HTTP URL in products.image_path
                    cursor.execute("UPDATE products SET image_path = %s WHERE product_id = %s", (url, product_id))
                    current_app.logger.debug("[DEBUG] Uploaded main image to R2: %s", url)
                except Exception as e:
                    current_app.logger.exception("Failed uploading main image for product %s: %s", product_id, e)
                    # do not abort full product creation for one upload failure
                    flash(f"Warning: failed to upload main image ({e})", "warning")

            # ---------- Save additional product-level images to R2 ----------
            pos = 1
            for img in (additional_images or []):
                if img and getattr(img, 'filename', None) and allowed_file(img.filename):
                    orig = secure_filename(img.filename)
                    filename = f"{product_id}_add_{pos}_{int(time.time())}_{uuid.uuid4().hex[:6]}_{orig}"
                    key = f"products/{product_id}/images/{filename}"
                    try:
                        url = upload_to_r2(img, key)
                        cursor.execute(
                            "INSERT INTO product_images (product_id, variant_id, path, alt_text, position, is_primary) VALUES (%s,%s,%s,%s,%s,%s)",
                            (product_id, None, url, None, pos, 0)
                        )
                        current_app.logger.debug("[DEBUG] Uploaded additional image to R2: %s", url)
                        pos += 1
                    except Exception as e:
                        current_app.logger.exception("Failed uploading additional image for product %s: %s", product_id, e)
                        # continue — don't abort

            # ---------- Build filtered variant list (skip fully empty entries) ----------
            variants = []
            max_len = max(len(variant_sizes), len(variant_prices), len(variant_stocks),
                          len(variant_skus), len(variant_colors), len(variant_color_hex))
            for i in range(max_len):
                size = (variant_sizes[i].strip() if i < len(variant_sizes) and variant_sizes[i] else '') or ''
                color = (variant_colors[i].strip() if i < len(variant_colors) and variant_colors[i] else '') or ''
                color_hex = (variant_color_hex[i].strip() if i < len(variant_color_hex) and variant_color_hex[i] else '') or ''
                vsku = (variant_skus[i].strip() if i < len(variant_skus) and variant_skus[i] else '') or ''
                price_raw = (variant_prices[i] if i < len(variant_prices) else '') or ''
                stock_raw = (variant_stocks[i] if i < len(variant_stocks) else '') or ''

                try:
                    price = float(price_raw) if str(price_raw).strip() else 0.0
                except (ValueError, TypeError):
                    price = 0.0
                try:
                    vstock = int(float(stock_raw)) if str(stock_raw).strip() else 0
                except (ValueError, TypeError):
                    vstock = 0

                # skip completely empty variant rows
                if not (size or color or vsku or price or vstock):
                    continue

                variants.append({
                    'size': size or None,
                    'color': color or None,
                    'color_hex': color_hex or None,
                    'sku': vsku or None,
                    'price': price,
                    'stock': vstock
                })

            # ---------- Helper to collect files for a given variant index robustly ----------
            def collect_variant_files(idx):
                files = []
                try:
                    files = request.files.getlist(f"variant_images_{idx}") or []
                except Exception:
                    files = []

                if not files:
                    for key in request.files:
                        if key == f"variant_images_{idx}" or key.startswith(f"variant_images_{idx}") or key.endswith(f"_{idx}") or f"[{idx}]" in key:
                            files.extend(request.files.getlist(key))

                if not files:
                    for key in request.files:
                        if "variant_images" in key and str(idx) in key:
                            files.extend(request.files.getlist(key))

                unique_files = []
                seen_names = set()
                for f in files:
                    name = getattr(f, 'filename', None)
                    if name and name not in seen_names:
                        seen_names.add(name)
                        unique_files.append(f)
                return unique_files

            # ---------- Insert variants and save variant images to R2 ----------
            total_stock_from_variants = 0
            first_variant_has_images = False

            for idx, v in enumerate(variants):
                vindex = idx + 1
                vsku = v['sku'] or f"{sku}{vindex}"
                is_def = 1 if idx == 0 else 0

                insert_variant_q = """
                    INSERT INTO product_variants
                    (product_id, sku, size, color, price, color_hex, stock_count, is_default)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING variant_id
                """
                cursor.execute(insert_variant_q, (product_id, vsku, v['size'], v['color'], v['price'], v['color_hex'], v['stock'], is_def))
                variant_id = cursor.fetchone()[0]
                total_stock_from_variants += v['stock']
                current_app.logger.debug("[DEBUG] Inserted variant id=%s sku=%s stock=%s", variant_id, vsku, v['stock'])

                # collect files robustly for this variant index
                vfiles = collect_variant_files(idx)
                current_app.logger.debug("[DEBUG] Collected %s file(s) for variant index %s", len(vfiles), idx)

                vpos = 0
                for vf in vfiles:
                    if vf and getattr(vf, 'filename', None) and allowed_file(vf.filename):
                        orig = secure_filename(vf.filename)
                        filename = f"{product_id}_var{idx}_{vpos}_{int(time.time())}_{uuid.uuid4().hex[:6]}_{orig}"
                        key = f"products/{product_id}/variants/{variant_id}/{filename}"
                        try:
                            url = upload_to_r2(vf, key)
                            is_primary = 1 if (idx == 0 and vpos == 0 and not first_variant_has_images) else 0
                            cursor.execute(
                                "INSERT INTO product_images (product_id, variant_id, path, alt_text, position, is_primary) VALUES (%s,%s,%s,%s,%s,%s)",
                                (product_id, variant_id, url, None, vpos, is_primary)
                            )
                            current_app.logger.debug("[DEBUG] Uploaded variant image to R2: %s", url)
                            vpos += 1
                        except Exception as e:
                            current_app.logger.exception("Failed uploading variant image for product %s variant %s: %s", product_id, variant_id, e)
                            # continue

                if idx == 0 and vpos > 0:
                    first_variant_has_images = True

            # ---------- Update products.stock_count with computed value ----------
            if total_stock_from_variants > 0:
                cursor.execute("UPDATE products SET stock_count = %s WHERE product_id = %s", (total_stock_from_variants, product_id))
            else:
                cursor.execute("UPDATE products SET stock_count = %s WHERE product_id = %s", (stock_count, product_id))

            # if first variant had images, clear product-level primary images (if any)
            if first_variant_has_images:
                try:
                    cursor.execute("UPDATE product_images SET is_primary = 0 WHERE product_id = %s AND variant_id IS NULL", (product_id,))
                except Exception:
                    pass

            conn.commit()
            flash('Product added successfully!', 'success')
            return render_template('owner/add_product.html')

        except Exception as e:
            if conn:
                conn.rollback()
            current_app.logger.exception("[ERROR] Error adding product: %s", e)
            flash(f'Error adding product: {e}', 'danger')
            return render_template('owner/add_product.html')
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # GET
    return render_template('owner/add_product.html')


# -------------------view products-----------------

# Add/replace in your routes file


@main.route('/view-products')
@nocache
def view_owner_products():
    # owner only
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    # read query params (search/filter/sort)
    q = (request.args.get('q') or '').strip()
    sort = request.args.get('sort') or 'newest'   # default sort
    selected_categories = request.args.getlist('category')  # can be many
    selected_brands = request.args.getlist('brand')
    selected_tags = request.args.getlist('tag')
    selected_colors = request.args.getlist('color')
    selected_sizes = request.args.getlist('size')
    # price range
    min_price = request.args.get('min_price') or None
    max_price = request.args.get('max_price') or None
    # rating threshold (e.g., 4 for 4★ & above)
    rating_min = request.args.get('rating') or None

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Build WHERE clauses (safe parameterized)
    where_clauses = []
    params = []

    # search across name, brand, category, short_description, description
    if q:
        where_clauses.append("(p.name LIKE %s OR p.brand LIKE %s OR p.category LIKE %s OR p.short_description LIKE %s OR p.description LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like, like, like])

    if selected_categories:
        placeholders = ",".join(["%s"] * len(selected_categories))
        where_clauses.append(f"p.category IN ({placeholders})")
        params.extend(selected_categories)

    if selected_brands:
        placeholders = ",".join(["%s"] * len(selected_brands))
        where_clauses.append(f"p.brand IN ({placeholders})")
        params.extend(selected_brands)

    # left joins below will provide pv for price and variants; tags handled via join in main query
    # We'll apply color/size/tag filters using HAVING (after GROUP BY) for aggregated columns or via EXISTS checks in WHERE
    # For simplicity and correctness we use EXISTS subqueries for color/size/tag (avoids complex HAVING)
    if selected_colors:
        # require product has at least one variant with any of these colors
        placeholders = ",".join(["%s"] * len(selected_colors))
        where_clauses.append(f"EXISTS (SELECT 1 FROM product_variants pv_c WHERE pv_c.product_id = p.product_id AND pv_c.color IN ({placeholders}))")
        params.extend(selected_colors)

    if selected_sizes:
        placeholders = ",".join(["%s"] * len(selected_sizes))
        where_clauses.append(f"EXISTS (SELECT 1 FROM product_variants pv_s WHERE pv_s.product_id = p.product_id AND pv_s.size IN ({placeholders}))")
        params.extend(selected_sizes)

    if selected_tags:
        placeholders = ",".join(["%s"] * len(selected_tags))
        where_clauses.append(f"EXISTS (SELECT 1 FROM product_tags pt JOIN tags t ON t.tag_id = pt.tag_id WHERE pt.product_id = p.product_id AND t.tag_id IN ({placeholders}))")
        params.extend(selected_tags)

    # combine where
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Main query: aggregate variants & images by product
    # We compute min_price, max_price, total_stock, avg_rating (products.rating_avg already exists)
    main_q = f"""
        SELECT
            p.product_id, p.name, p.brand, p.category, p.image_path, p.is_active, p.is_returnable,
            COALESCE(MIN(pv.price), 0) AS min_price,
            COALESCE(MAX(pv.price), 0) AS max_price,
            COALESCE(SUM(pv.stock_count), 0) AS total_stock,
            COUNT(DISTINCT pv.variant_id) AS variant_count,
            COALESCE(p.rating_avg, 0) AS rating_avg,
            COUNT(DISTINCT pi.image_id) AS total_images,
            p.created_at
        FROM products p
        LEFT JOIN product_variants pv ON pv.product_id = p.product_id
        LEFT JOIN product_images pi ON pi.product_id = p.product_id
        WHERE {where_sql}
        GROUP BY p.product_id
    """

    # Apply price and rating filters via wrapping query or HAVING clause
    having_clauses = []
    having_params = []
    if min_price:
        having_clauses.append("MIN(pv.price) >= %s")
        having_params.append(float(min_price))
    if max_price:
        having_clauses.append("MIN(pv.price) <= %s")
        having_params.append(float(max_price))
    if rating_min:
        having_clauses.append("COALESCE(p.rating_avg,0) >= %s")
        having_params.append(float(rating_min))

    having_sql = (" HAVING " + " AND ".join(having_clauses)) if having_clauses else ""

    # Sorting
    sort_sql = " ORDER BY p.created_at DESC "
    if sort == 'low':
        sort_sql = " ORDER BY min_price ASC "
    elif sort == 'high':
        sort_sql = " ORDER BY min_price DESC "
    elif sort == 'rating':
        sort_sql = " ORDER BY rating_avg DESC "
    elif sort == 'newest':
        sort_sql = " ORDER BY p.created_at DESC "

    final_q = main_q + having_sql + sort_sql

    # Execute product query
    cursor.execute(final_q, params + having_params)
    products = cursor.fetchall() or []

    # Format price_range and stats for each product (template convenience)
    for p in products:
        p['price_range'] = {
            'min': float(p['min_price'] or 0),
            'max': float(p['max_price'] or 0),
            'has_range': (p['min_price'] is not None and p['max_price'] is not None and p['min_price'] != p['max_price'] and p['variant_count'] > 1)
        }
        p['stats'] = {
            'variants': int(p['variant_count'] or 0),
            'total_stock': int(p['total_stock'] or 0),
            'total_images': int(p['total_images'] or 0)
        }
        if p.get('image_path'):
            p['image_path'] = p['image_path'].replace('\\', '/')

    # --- Fetch dynamic filter values (distinct categories, brands, tags, colors, sizes) ---
    # categories
    cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category <> '' ORDER BY category ASC")
    categories = [r['category'] for r in cursor.fetchall()]

    # brands
    cursor.execute("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand <> '' ORDER BY brand ASC")
    brands = [r['brand'] for r in cursor.fetchall()]

    # tags (id + name)
    cursor.execute("""
        SELECT t.tag_id, t.name FROM tags t
        JOIN product_tags pt ON pt.tag_id = t.tag_id
        GROUP BY t.tag_id, t.name
        ORDER BY t.name ASC
    """)
    tags = cursor.fetchall()  # list of dicts with tag_id and name

    # colors
    cursor.execute("SELECT DISTINCT color FROM product_variants WHERE color IS NOT NULL AND color <> '' ORDER BY color ASC")
    colors = [r['color'] for r in cursor.fetchall()]

    # sizes
    cursor.execute("SELECT DISTINCT size FROM product_variants WHERE size IS NOT NULL AND size <> '' ORDER BY size ASC")
    sizes = [r['size'] for r in cursor.fetchall()]

    # compute global min/max price for slider defaults (from variants)
    cursor.execute("SELECT COALESCE(MIN(price),0) AS min_price, COALESCE(MAX(price),0) AS max_price FROM product_variants")
    price_row = cursor.fetchone()
    global_min_price = float(price_row['min_price'] or 0)
    global_max_price = float(price_row['max_price'] or 0)

    cursor.close()
    conn.close()

    # pass current query params so template can keep boxes checked
    context = {
        'products': products,
        'filters': {
            'categories': categories,
            'brands': brands,
            'tags': tags,
            'colors': colors,
            'sizes': sizes,
            'global_min_price': int(global_min_price),
            'global_max_price': int(global_max_price),
        },
        # reflect selected filters back to template (so boxes remain checked)
        'selected': {
            'q': q, 'sort': sort,
            'categories': selected_categories,
            'brands': selected_brands,
            'tags': selected_tags,
            'colors': selected_colors,
            'sizes': selected_sizes,
            'min_price': min_price,
            'max_price': max_price,
            'rating': rating_min
        },
        # include request.args for convenience
        'request_args': request.args
    }
    return render_template('owner/view_products.html', **context)



import urllib.parse

# Helper: try to obtain a variant_id from form, args, or referrer query string.
def _extract_variant_id_from_request():
    """
    Returns an integer variant_id if present in:
      - request.form (fields: 'variant_id', 'edit_variant_id')
      - request.args (query param 'variant_id' or 'variant_sku' not handled here)
      - request.referrer (parses query string)
    Otherwise returns None.
    """
    # 1) check form fields (common names)
    for fname in ('variant_id', 'edit_variant_id', 'current_variant_id', 'open_variant_id'):
        v = request.form.get(fname)
        if v:
            try:
                return int(v)
            except Exception:
                pass

    # 2) check request.args
    v = request.args.get('variant_id')
    if v:
        try:
            return int(v)
        except Exception:
            pass

    # 3) try to parse from referrer query string
    ref = request.referrer
    if ref:
        try:
            parsed = urllib.parse.urlparse(ref)
            qs = urllib.parse.parse_qs(parsed.query)
            vlist = qs.get('variant_id') or qs.get('variantId') or qs.get('variant')
            if vlist:
                try:
                    return int(vlist[0])
                except Exception:
                    pass
        except Exception:
            pass

    return None

# ---------- View product detail (unchanged) ----------
@main.route('/product/<int:product_id>')
@nocache
def view_product_detail(product_id):
    # owner-only
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM products WHERE product_id = %s", (product_id,))
    product = cursor.fetchone()
    if not product:
        cursor.close(); conn.close()
        flash("Product not found", "danger")
        return redirect(url_for('main.view_owner_products'))

    # Optional ownership check: if products have owner_id column, ensure owner owns it
    if 'owner_id' in product and product.get('owner_id') is not None:
        if int(product.get('owner_id')) != int(session.get('owner_id')):
            cursor.close(); conn.close()
            flash("You are not authorized to view this product.", "danger")
            return redirect(url_for('main.view_owner_products'))

    # Normalize simple fields
    if product.get('image_path'):
        product['image_path'] = product['image_path'].replace('\\', '/')
    for fld in ('brand','category','short_description','description','material',
                'fit','care_instructions','pattern','occasion','season','sustainability','weight'):
        product[fld] = product.get(fld) or ''

    # Keep raw DB description (unescaped) for debug panel
    raw_desc = product.get('description') or ''
    product['description_raw'] = raw_desc

    # Description normalization (same robust pipeline as customer)
    try:
        s = _html.unescape(raw_desc or '')

        # Replace any <br> (case-insensitive) with newline
        s = re.sub(r'(?i)<\s*br\s*/?\s*>', '\n', s)

        # Convert literal backslash-n sequences to real newline (if DB stored \n as text)
        s = s.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')

        # Normalize CRLF & CR to LF
        s = s.replace('\r\n', '\n').replace('\r', '\n')

        # Strip leading/trailing whitespace and collapse 3+ newlines to 2 for readability
        s = s.strip()
        s = re.sub(r'\n{3,}', '\n\n', s)

        # Escape everything (protect against XSS)
        escaped = escape(s)

        # Convert newline characters to real <br/> tags for HTML rendering
        escaped_with_br = Markup(str(escaped).replace('\n', '<br/>'))

        product['description_html'] = escaped_with_br

    except Exception:
        current_app.logger.exception("Error processing product.description")
        product['description_html'] = Markup(escape(raw_desc or '').replace('\n', '<br/>'))

    # --- variants ---
    cursor.execute("""
        SELECT pv.*
        FROM product_variants pv
        WHERE pv.product_id = %s
        ORDER BY pv.is_default DESC, pv.variant_id ASC
    """, (product_id,))
    variants = cursor.fetchall() or []
    for v in variants:
        v['price'] = float(v.get('price') or 0.0)
        v['stock_count'] = int(v.get('stock_count') or 0)
        for f in ('sku','size','color','color_hex'):
            v[f] = v.get(f) or ''

    # product-level images (variant_id IS NULL)
    cursor.execute("""
        SELECT *
        FROM product_images
        WHERE product_id = %s AND variant_id IS NULL
        ORDER BY is_primary DESC, position ASC, image_id ASC
    """, (product_id,))
    product_images = cursor.fetchall() or []
    for pi in product_images:
        pi['path'] = pi['path'].replace('\\', '/')

    # variant images grouped by variant_id
    cursor.execute("""
        SELECT *
        FROM product_images
        WHERE product_id = %s AND variant_id IS NOT NULL
        ORDER BY variant_id ASC, position ASC, image_id ASC
    """, (product_id,))
    all_variant_images = cursor.fetchall() or []
    variant_images = {}
    for img in all_variant_images:
        img['path'] = img['path'].replace('\\', '/')
        vid = img.get('variant_id')
        variant_images.setdefault(vid, []).append(img)

    # prepare thumbnail path for each variant (fallback product image / placeholder)
    for v in variants:
        vid = v.get('variant_id')
        if vid in variant_images and variant_images[vid]:
            v['thumb'] = variant_images[vid][0]['path']
        elif product_images:
            v['thumb'] = product_images[0]['path']
        elif product.get('image_path'):
            v['thumb'] = product['image_path']
        else:
            v['thumb'] = 'uploads/placeholder.png'

    # initial variant selection (optional: from query params)
    initial_variant_id = None
    qvid = request.args.get('variant_id')
    qsku = request.args.get('variant_sku')
    if qvid:
        try:
            qv = int(qvid)
            if any(int(x.get('variant_id')) == qv for x in variants):
                initial_variant_id = qv
        except Exception:
            pass
    elif qsku:
        for v in variants:
            if v.get('sku') and v['sku'] == qsku:
                initial_variant_id = int(v['variant_id'])
                break

    # Reviews aggregate & initial top 5 (same as customer)
    cursor.execute("SELECT COALESCE(AVG(rating),0) AS avg_rating, COUNT(*) AS total_reviews FROM product_reviews WHERE product_id = %s", (product_id,))
    agg = cursor.fetchone() or {'avg_rating':0.0, 'total_reviews':0}
    avg_rating = float(agg.get('avg_rating') or 0.0)
    total_reviews = int(agg.get('total_reviews') or 0)

    cursor.execute("""
        SELECT pr.*, c.name AS customer_name
        FROM product_reviews pr
        LEFT JOIN customers c ON c.customer_id = pr.customer_id
        WHERE pr.product_id = %s
        ORDER BY pr.created_at DESC
        LIMIT 5
    """, (product_id,))
    top_reviews = cursor.fetchall() or []
    for r in top_reviews:
        r['customer_name'] = r.get('customer_name') or 'Anonymous'
        r['rating'] = int(r.get('rating') or 0)
        r['title'] = r.get('title') or ''
        r['body'] = r.get('body') or ''
        try:
            r['created_at_str'] = r['created_at'].strftime('%b %d, %Y') if r.get('created_at') else ''
        except Exception:
            r['created_at_str'] = str(r.get('created_at') or '')

    cursor.close()
    conn.close()

    # show developer debug panel either when app.debug or session['is_dev']
    show_dev = bool(current_app.debug or session.get('is_dev'))

    return render_template(
        'owner/product_detail.html',
        product=product,
        variants=variants,
        product_images=product_images,
        variant_images=variant_images,
        initial_variant_id=initial_variant_id,
        avg_rating=round(avg_rating, 2),
        total_reviews=total_reviews,
        top_reviews=top_reviews,
        show_dev=show_dev
    )

# ---------- Edit product (POST only) ----------
# ---------- Utility to get a dict-like cursor compatible across DB wrappers ----------
def _get_dict_cursor(conn):
    """
    Try to return a cursor that yields dict-like rows.
    Works with psycopg2 (RealDictCursor) and fallbacks to other styles.
    """
    try:
        # psycopg2
        from psycopg2.extras import RealDictCursor
        return conn.cursor(cursor_factory=RealDictCursor)
    except Exception:
        # try MySQL-style dictionary parameter
        try:
            return conn.cursor(dictionary=True)
        except Exception:
            # final fallback: regular cursor (tuples) — caller must handle
            return conn.cursor()

# ---------- Route: edit product (with R2 main image replacement) ----------

@main.route('/product/<int:product_id>/edit', methods=['POST'])
@nocache
def edit_product(product_id):
    # Owner auth
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    conn = None
    cursor = None
    try:
        conn = get_db()

        # We'll try to use a dict-like cursor for convenience
        cursor = _get_dict_cursor(conn)

        # Lock & fetch the product row for update to avoid races
        # Note: psycopg2 supports FOR UPDATE; wrappers should too. If not, fallback to a normal SELECT.
        try:
            cursor.execute("SELECT * FROM products WHERE product_id = %s FOR UPDATE", (product_id,))
        except Exception:
            cursor.execute("SELECT * FROM products WHERE product_id = %s", (product_id,))
        product = cursor.fetchone()
        if not product:
            flash("Product not found.", "danger")
            return redirect(url_for('main.view_owner_products'))

        # --- Read and sanitize fields (same as before) ---
        name = (request.form.get('name') or '').strip()
        brand = (request.form.get('brand') or '').strip() or None
        category = (request.form.get('category') or '').strip() or None
        short_description = (request.form.get('short_description') or '').strip() or None
        description = (request.form.get('description') or '').strip() or None

        material = (request.form.get('material') or '').strip() or None
        fit = (request.form.get('fit') or '').strip() or None
        care_instructions = (request.form.get('care_instructions') or '').strip() or None
        pattern = (request.form.get('pattern') or '').strip() or None
        occasion = (request.form.get('occasion') or '').strip() or None
        season = (request.form.get('season') or '').strip() or None
        sustainability = (request.form.get('sustainability') or '').strip() or None

        weight_raw = (request.form.get('weight') or '').strip()
        try:
            weight = float(weight_raw) if weight_raw != '' else None
        except Exception:
            weight = None

        is_returnable = 1 if request.form.get('is_returnable') in ('1', 'on', 'true', 'yes') else 0
        sku = (request.form.get('sku') or '').strip() or None

        # product_images deletion (optional)
        delete_image_ids = request.form.getlist('delete_image_ids') or []
        try:
            delete_image_ids = [int(x) for x in delete_image_ids if str(x).strip() != '']
        except Exception:
            delete_image_ids = []

        # new product image files (the UI field is product_images). We only care if at least one file provided.
        new_files = request.files.getlist('product_images') or []
        # normalize to first valid file for the product main image replacement (per spec there's only one main)
        new_main_file = None
        for f in new_files:
            if f and getattr(f, 'filename', None) and f.filename.strip():
                # optional: validate extension via allowed_file() if you have one
                new_main_file = f
                break

        # --- Build and execute product update (non-image fields) ---
        update_fields = {
            'name': name or (product.get('name') if isinstance(product, dict) else product[1]),
            'brand': brand,
            'category': category,
            'short_description': short_description,
            'description': description,
            'material': material,
            'fit': fit,
            'care_instructions': care_instructions,
            'pattern': pattern,
            'occasion': occasion,
            'season': season,
            'sustainability': sustainability,
            'weight': weight,
            'is_returnable': is_returnable,
            'sku': sku
        }

        set_clauses = []
        params = []
        for k, v in update_fields.items():
            set_clauses.append(f"{k} = %s")
            params.append(v)
        # also update updated_at to now()
        set_clauses.append("updated_at = (now() AT TIME ZONE 'Asia/Kolkata')")
        sql = f"UPDATE products SET {', '.join(set_clauses)} WHERE product_id = %s"
        params.append(product_id)
        cursor.execute(sql, tuple(params))

        # ---------- Handle deletion of specific product_images rows (if provided) ----------
        if delete_image_ids:
            # fetch their paths and delete objects from R2
            fmt = ",".join(["%s"] * len(delete_image_ids))
            cursor.execute(f"SELECT image_id, path FROM product_images WHERE image_id IN ({fmt}) AND product_id = %s", tuple(delete_image_ids + [product_id]))
            to_delete_rows = cursor.fetchall() or []
            # delete DB rows
            cursor.execute(f"DELETE FROM product_images WHERE image_id IN ({fmt}) AND product_id = %s", tuple(delete_image_ids + [product_id]))
            # attempt to remove S3 objects (best-effort; log failures)
            for r in to_delete_rows:
                # r may be dict-like
                path = r.get('path') if isinstance(r, dict) else r[2] if len(r) > 2 else None
                if not path:
                    continue
                key = _r2_key_from_public_url(path)
                if key:
                    try:
                        delete_from_r2(key)
                    except Exception as e:
                        current_app.logger.exception("Failed to delete product_images object %s: %s", key, e)

        # ---------- Handle replacement of main product image (ONLY if a new file was provided) ----------
        old_image_url = product.get('image_path') if isinstance(product, dict) else product[6]  # best-effort index fallback
        new_uploaded_key = None
        new_public_url = None
        if new_main_file:
            # Choose a safe filename and key under main/
            orig = secure_filename(getattr(new_main_file, "filename"))
            unique = f"{product_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}_{orig}"
            key = f"products/{product_id}/main/{unique}"

            # Upload new file to R2 (private upload, public url returned by upload_to_r2)
            try:
                new_public_url = upload_to_r2(new_main_file, key)
                new_uploaded_key = key
            except Exception as e:
                # Upload failed — rollback DB and inform owner
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                current_app.logger.exception("Failed uploading new main image for product %s: %s", product_id, e)
                flash(f"Failed to upload new image: {e}", "danger")
                # redirect back to product page
                vid = _extract_variant_id_from_request()
                if vid:
                    return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=vid))
                return redirect(url_for('main.view_product_detail', product_id=product_id))

            # Now that upload succeeded, update DB: set image_path and update product_images primary flags and insert new product_images row
            try:
                # set other product_images.is_primary = 0 for this product
                cursor.execute("UPDATE product_images SET is_primary = 0 WHERE product_id = %s", (product_id,))

                # determine next position for product-level images (variant_id IS NULL)
                cursor.execute("SELECT COALESCE(MAX(position), -1) AS m FROM product_images WHERE product_id = %s AND variant_id IS NULL", (product_id,))
                row = cursor.fetchone()
                # row may be dict-like or tuple
                max_pos = None
                if isinstance(row, dict):
                    max_pos = row.get('m')
                elif row and len(row) >= 1:
                    max_pos = row[0]
                next_pos = (max_pos if max_pos is not None else -1) + 1

                # insert new product_images record with is_primary=1
                cursor.execute(
                    "INSERT INTO product_images (product_id, variant_id, path, alt_text, position, is_primary) VALUES (%s,%s,%s,%s,%s,%s)",
                    (product_id, None, new_public_url, None, next_pos, 1)
                )

                # update products.image_path to new public url
                cursor.execute("UPDATE products SET image_path = %s, updated_at = (now() AT TIME ZONE 'Asia/Kolkata') WHERE product_id = %s", (new_public_url, product_id))

                # commit DB transaction now (so DB points to the new URL)
                conn.commit()

                # after commit, delete the previous object from R2 (best-effort)
                try:
                    old_key = _r2_key_from_public_url(old_image_url)
                    if old_key:
                        deleted = delete_from_r2(old_key)
                        if not deleted:
                            current_app.logger.warning("Could not delete old R2 object for product %s key=%s", product_id, old_key)
                except Exception as e:
                    current_app.logger.exception("Failed to delete previous product main image for product %s: %s", product_id, e)

                flash("Product updated successfully.", "success")
                vid = _extract_variant_id_from_request()
                if vid:
                    return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=vid))
                return redirect(url_for('main.view_product_detail', product_id=product_id))

            except Exception as e:
                # DB update/commit failed after upload — try to remove newly uploaded object to avoid orphaning
                try:
                    if new_uploaded_key:
                        delete_from_r2(new_uploaded_key)
                except Exception:
                    current_app.logger.exception("Failed to cleanup newly uploaded object after DB failure: %s", new_uploaded_key)
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                current_app.logger.exception("Database error while updating product image/records for product %s: %s", product_id, e)
                flash(f"Database error updating product: {e}", "danger")
                vid = _extract_variant_id_from_request()
                if vid:
                    return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=vid))
                return redirect(url_for('main.view_product_detail', product_id=product_id))

        else:
            # No new main image provided — we only updated non-image fields and possibly deleted selected product_images above.
            try:
                conn.commit()
            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                current_app.logger.exception("Failed committing product update (no-image flow) for product %s: %s", product_id, e)
                flash(f"Database error: {e}", "danger")
                vid = _extract_variant_id_from_request()
                if vid:
                    return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=vid))
                return redirect(url_for('main.view_product_detail', product_id=product_id))

            flash("Product updated successfully.", "success")
            vid = _extract_variant_id_from_request()
            if vid:
                return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=vid))
            return redirect(url_for('main.view_product_detail', product_id=product_id))

    except Exception as e:
        # Generic error handler
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        current_app.logger.exception("Unexpected error editing product %s: %s", product_id, e)
        flash(f"Unexpected error: {e}", "danger")
        vid = _extract_variant_id_from_request()
        if vid:
            return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=vid))
        return redirect(url_for('main.view_product_detail', product_id=product_id))
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ---------- Delete a single image (AJAX) (updated to delete R2 object) ----------
@main.route('/product/image/<int:image_id>/delete', methods=['POST'])
@nocache
def delete_image(image_id):
    if 'owner_id' not in session:
        return jsonify({"ok": False, "error": "Owner login required"}), 403

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = _get_dict_cursor(conn)

        # fetch image row
        cursor.execute("SELECT image_id, product_id, variant_id, path FROM product_images WHERE image_id = %s", (image_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Image not found"}), 404

        # parse key for R2 deletion (if path looks like an R2 public URL)
        path = row.get('path') if isinstance(row, dict) else (row[3] if len(row) > 3 else None)
        key = _r2_key_from_public_url(path) if path else None

        # delete DB row inside transaction
        try:
            cursor.execute("DELETE FROM product_images WHERE image_id = %s", (image_id,))
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            current_app.logger.exception("DB error deleting product_images row %s: %s", image_id, e)
            return jsonify({"ok": False, "error": "Database error"}), 500

        # After DB commit, attempt to delete R2 object (best-effort)
        if key:
            try:
                delete_from_r2(key)
            except Exception as e:
                current_app.logger.exception("Failed to delete R2 object for image %s key=%s: %s", image_id, key, e)
                # still return success because DB row deleted; but include warning
                return jsonify({"ok": True, "deleted": int(image_id), "warning": "Failed to delete remote object"}), 200

        return jsonify({"ok": True, "deleted": int(image_id)}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        current_app.logger.exception("Unexpected error deleting image: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

# ---------- Edit variant route (upload/delete to R2 + DB ACID) ----------
@main.route('/product/<int:product_id>/variant/<int:variant_id>/edit', methods=['GET', 'POST'])
@nocache
def edit_variant(product_id, variant_id):
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = _get_dict_cursor(conn)

        # Verify product
        cursor.execute("SELECT product_id, name FROM products WHERE product_id = %s", (product_id,))
        prod = cursor.fetchone()
        if not prod:
            flash("Product not found.", "danger")
            return redirect(url_for('main.view_owner_products'))

        # Fetch variant (lock for update if possible)
        try:
            cursor.execute("SELECT * FROM product_variants WHERE variant_id = %s AND product_id = %s FOR UPDATE", (variant_id, product_id))
        except Exception:
            cursor.execute("SELECT * FROM product_variants WHERE variant_id = %s AND product_id = %s", (variant_id, product_id))
        variant = cursor.fetchone()
        if not variant:
            flash("Variant not found for this product.", "danger")
            return redirect(url_for('main.view_product_detail', product_id=product_id))

        if request.method == 'GET':
            cursor.execute("SELECT * FROM product_images WHERE variant_id = %s ORDER BY is_primary DESC, position ASC, image_id ASC", (variant_id,))
            v_images = cursor.fetchall() or []
            cursor.execute("SELECT * FROM product_images WHERE product_id = %s AND variant_id IS NULL ORDER BY is_primary DESC, position ASC", (product_id,))
            p_images = cursor.fetchall() or []
            for img in (v_images + p_images):
                if isinstance(img, dict) and img.get('path'):
                    img['path'] = img['path'].replace('\\', '/')
            return render_template('owner/variant_edit.html', product=prod, variant=variant, variant_images=v_images, product_images=p_images)

        # POST: apply updates
        sku = (request.form.get('sku') or '').strip() or None
        size = (request.form.get('size') or '').strip() or None
        color = (request.form.get('color') or '').strip() or None
        color_hex = (request.form.get('color_hex') or '').strip() or None
        price_raw = (request.form.get('price') or '').strip()
        stock_raw = (request.form.get('stock') or '').strip()
        is_default_flag = request.form.get('is_default') in ('1', 'on', 'true', 'yes')

        # sanitize numeric inputs
        try:
            price = float(price_raw) if price_raw != '' else 0.0
        except Exception:
            price = 0.0
        try:
            stock_count = int(float(stock_raw)) if stock_raw != '' else 0
        except Exception:
            stock_count = 0

        # SKU uniqueness check
        if sku:
            cursor.execute("SELECT 1 FROM product_variants WHERE sku = %s AND variant_id != %s LIMIT 1", (sku, variant_id))
            if cursor.fetchone():
                flash("SKU already in use by another variant.", "danger")
                return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=variant_id))

        # Deletions requested (checkboxes named delete_image_ids)
        delete_ids = request.form.getlist('delete_image_ids') or []
        try:
            delete_ids = [int(x) for x in delete_ids if str(x).strip() != '']
        except Exception:
            delete_ids = []

        # New uploaded files for this variant
        uploaded_files = request.files.getlist('variant_images') or []
        # Filter out empty entries
        uploaded_files = [f for f in uploaded_files if f and getattr(f, 'filename', None) and f.filename.strip()]

        # Pre-check: existing images count for variant (to determine primary logic)
        cursor.execute("SELECT COUNT(*) AS cnt FROM product_images WHERE variant_id = %s", (variant_id,))
        row = cursor.fetchone()
        existing_count = 0
        if isinstance(row, dict):
            existing_count = int(row.get('cnt', 0))
        elif row and len(row) >= 1:
            existing_count = int(row[0])

        # Prepare to upload files to R2 first
        uploaded_records = []  # list of dicts: { key, public_url, filename }
        try:
            # Upload each file to R2 (collect public URLs)
            for idx, f in enumerate(uploaded_files):
                # optional: check allowed_file if you have it
                try:
                    filename_safe = secure_filename(getattr(f, "filename"))
                except Exception:
                    filename_safe = f"upload_{int(time.time())}_{idx}"

                unique = f"{product_id}_var{variant_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}_{filename_safe}"
                key = f"products/{product_id}/variants/{variant_id}/{unique}"
                try:
                    public_url = upload_to_r2(f, key)
                    uploaded_records.append({"key": key, "public_url": public_url})
                except Exception as e:
                    # cleanup any previously uploaded objects in this loop
                    for rec in uploaded_records:
                        try:
                            delete_from_r2(rec.get('key'))
                        except Exception:
                            current_app.logger.exception("Failed cleanup after upload error for key=%s", rec.get('key'))
                    raise

            # All uploads succeeded — now perform DB updates in transaction
            # If this variant is set as default, clear other variants first
            if is_default_flag:
                cursor.execute("UPDATE product_variants SET is_default = 0 WHERE product_id = %s", (product_id,))

            # Update variant row fields
            cursor.execute("""
                UPDATE product_variants
                SET sku = %s, size = %s, color = %s, color_hex = %s, price = %s, stock_count = %s, is_default = %s, updated_at = (now() AT TIME ZONE 'Asia/Kolkata')
                WHERE variant_id = %s AND product_id = %s
            """, (sku, size, color, color_hex, price, stock_count, 1 if is_default_flag else 0, variant_id, product_id))

            # Handle deletion of selected variant images:
            delete_old_keys = []  # collect keys to delete AFTER commit
            if delete_ids:
                fmt = ",".join(["%s"] * len(delete_ids))
                cursor.execute(f"SELECT image_id, path FROM product_images WHERE image_id IN ({fmt}) AND variant_id = %s AND product_id = %s",
                               tuple(delete_ids + [variant_id, product_id]))
                rows = cursor.fetchall() or []
                # remove DB rows
                cursor.execute(f"DELETE FROM product_images WHERE image_id IN ({fmt}) AND variant_id = %s AND product_id = %s",
                               tuple(delete_ids + [variant_id, product_id]))
                # collect keys for deletion
                for r in rows:
                    path = r.get('path') if isinstance(r, dict) else (r[2] if len(r) > 2 else None)
                    if path:
                        k = _r2_key_from_public_url(path)
                        if k:
                            delete_old_keys.append(k)

            # Insert uploaded records into product_images
            inserted = 0
            # figure starting position for variant images
            cursor.execute("SELECT COALESCE(MAX(position), -1) AS m FROM product_images WHERE variant_id = %s", (variant_id,))
            currow = cursor.fetchone()
            maxpos = None
            if isinstance(currow, dict):
                maxpos = currow.get('m')
            elif currow and len(currow) >= 1:
                maxpos = currow[0]
            next_pos = (maxpos if maxpos is not None else -1) + 1

            # If there were no images before (existing_count == 0) and uploaded_records not empty, mark the first as is_primary
            for rec_idx, rec in enumerate(uploaded_records):
                is_primary = 1 if (existing_count == 0 and rec_idx == 0) else 0
                cursor.execute(
                    "INSERT INTO product_images (product_id, variant_id, path, alt_text, position, is_primary) VALUES (%s,%s,%s,%s,%s,%s)",
                    (product_id, variant_id, rec['public_url'], None, next_pos, is_primary)
                )
                next_pos += 1
                inserted += 1

            # Recalculate product.stock_count (sum of variant stock_count)
            cursor.execute("SELECT COALESCE(SUM(stock_count), 0) AS tot FROM product_variants WHERE product_id = %s", (product_id,))
            row = cursor.fetchone()
            total_stock = int(row['tot'] if isinstance(row, dict) and row.get('tot') is not None else (row[0] if row else 0))
            cursor.execute("UPDATE products SET stock_count = %s, updated_at = (now() AT TIME ZONE 'Asia/Kolkata') WHERE product_id = %s", (total_stock, product_id))

            # Commit transaction
            conn.commit()

            # After commit: delete old R2 objects (best-effort)
            for k in delete_old_keys:
                try:
                    delete_from_r2(k)
                except Exception:
                    current_app.logger.exception("Failed to delete old variant image key=%s after commit", k)

            flash("Variant updated successfully.", "success")
            return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=variant_id))

        except Exception as e:
            # Any exception in uploads or DB updates:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            current_app.logger.exception("Error editing variant (R2/DB) product=%s variant=%s: %s", product_id, variant_id, e)
            flash(f"Error updating variant: {e}", "danger")
            # cleanup: delete any newly uploaded objects (if present in uploaded_records)
            try:
                for rec in uploaded_records:
                    try:
                        delete_from_r2(rec.get('key'))
                    except Exception:
                        current_app.logger.exception("Failed to cleanup uploaded object %s", rec.get('key'))
            except Exception:
                pass
            return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=variant_id))

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        current_app.logger.exception("Unexpected error editing variant: %s", e)
        flash(f"Unexpected error: {e}", "danger")
        return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=variant_id))
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ---------- Delete variant route ----------
@main.route('/product/<int:product_id>/variant/<int:variant_id>/delete', methods=['POST'])
@nocache
def delete_variant(product_id, variant_id):
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    conn = None
    cursor = None
    r2_keys_to_delete = []
    try:
        conn = get_db()
        # try to get a dict-like cursor if available for nicer access
        try:
            from psycopg2.extras import RealDictCursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        except Exception:
            try:
                cursor = conn.cursor(dictionary=True)
            except Exception:
                cursor = conn.cursor()

        # Fetch all image paths for this variant (collect R2 keys to delete later)
        cursor.execute("SELECT image_id, path FROM product_images WHERE variant_id = %s", (variant_id,))
        rows = cursor.fetchall() or []

        # derive R2 keys for deletion (but do not delete yet)
        for r in rows:
            # r may be dict-like or tuple
            path = None
            if isinstance(r, dict):
                path = r.get('path')
            else:
                # assume tuple (image_id, path)
                if len(r) >= 2:
                    path = r[1]
            if not path:
                continue
            key = _r2_key_from_public_url(path)
            if key:
                r2_keys_to_delete.append(key)

        # Begin DB transaction: remove image rows, variant row, update product stock
        try:
            # delete image rows for this variant
            cursor.execute("DELETE FROM product_images WHERE variant_id = %s", (variant_id,))

            # delete the variant row (ensure product match)
            cursor.execute("DELETE FROM product_variants WHERE variant_id = %s AND product_id = %s", (variant_id, product_id))

            # Recalculate total product stock from remaining variants and update products table
            cursor.execute("SELECT COALESCE(SUM(stock_count),0) AS tot FROM product_variants WHERE product_id = %s", (product_id,))
            tot_row = cursor.fetchone()
            total_stock = 0
            if isinstance(tot_row, dict):
                total_stock = int(tot_row.get('tot', 0) or 0)
            else:
                # tuple
                total_stock = int(tot_row[0] if tot_row and tot_row[0] is not None else 0)

            cursor.execute("UPDATE products SET stock_count = %s, updated_at = (now() AT TIME ZONE 'Asia/Kolkata') WHERE product_id = %s", (total_stock, product_id))

            # commit DB changes
            conn.commit()
            flash("Variant deleted successfully.", "success")

        except Exception as db_err:
            if conn:
                conn.rollback()
            current_app.logger.exception("DB error deleting variant %s for product %s: %s", variant_id, product_id, db_err)
            flash(f"Error deleting variant: {db_err}", "danger")
            return redirect(url_for('main.view_product_detail', product_id=product_id))

    except Exception as e:
        # any unexpected error in fetch phase
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        current_app.logger.exception("Unexpected error while preparing to delete variant %s of product %s: %s", variant_id, product_id, e)
        flash(f"Unexpected error: {e}", "danger")
        return redirect(url_for('main.view_product_detail', product_id=product_id))
    finally:
        # close DB resources
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # After successful DB commit, attempt to delete the remote R2 objects (best-effort).
    # We do this after commit to avoid the risk of deleting remote objects and then failing DB commit.
    for key in r2_keys_to_delete:
        try:
            ok = delete_from_r2(key)
            if not ok:
                current_app.logger.warning("delete_from_r2 returned False for key=%s", key)
        except Exception as de:
            current_app.logger.exception("Failed to delete R2 object key=%s for deleted variant %s: %s", key, variant_id, de)

    # Redirect to the product page without a variant id (deleted)
    return redirect(url_for('main.view_product_detail', product_id=product_id))



# ---------- Add variant route ----------
@main.route('/product/<int:product_id>/add-variant', methods=['POST'])
@nocache
def add_variant(product_id):
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    # Read fields from form (modal form will post these)
    size = (request.form.get('size') or '').strip() or None
    color = (request.form.get('color') or '').strip() or None
    color_hex = (request.form.get('color_hex') or '').strip() or None
    vsku = (request.form.get('sku') or '').strip() or None
    price_raw = request.form.get('price') or ''
    stock_raw = request.form.get('stock') or '0'

    try:
        price = float(price_raw) if str(price_raw).strip() else 0.0
    except (ValueError, TypeError):
        price = 0.0
    try:
        vstock = int(float(stock_raw)) if str(stock_raw).strip() else 0
    except (ValueError, TypeError):
        vstock = 0

    # variant images input name in modal: 'variant_images' (multiple)
    files = request.files.getlist('variant_images')

    conn = None
    cursor = None
    uploaded_r2_keys = []   # keep track of uploaded keys for cleanup if needed
    try:
        conn = get_db()
        # try to obtain a dict-like cursor if available for nicer access, fallback otherwise
        try:
            # If using psycopg2 wrapper, this may work; if not, cursor() fallback used
            from psycopg2.extras import RealDictCursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        except Exception:
            try:
                cursor = conn.cursor(dictionary=True)
            except Exception:
                cursor = conn.cursor()

        # If SKU not provided, derive from product.sku or fallback
        cursor.execute("SELECT sku FROM products WHERE product_id = %s", (product_id,))
        prod_row = cursor.fetchone()
        prod_sku = None
        if prod_row:
            if isinstance(prod_row, dict):
                prod_sku = prod_row.get('sku')
            else:
                # tuple-like
                prod_sku = prod_row[0] if len(prod_row) > 0 else None
        prod_sku = prod_sku or f"P{product_id}"

        if not vsku:
            vsku = f"{prod_sku}{int(time.time()) % 10000}"

        # Insert variant and obtain variant_id in a DB-portable way
        # Use RETURNING for Postgres-friendly behavior; wrapper may support it.
        try:
            cursor.execute("""
                INSERT INTO product_variants
                  (product_id, sku, size, color, price, color_hex, stock_count, is_default)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING variant_id
            """, (product_id, vsku, size, color, price, color_hex, vstock, 0))
            ins_row = cursor.fetchone()
            if ins_row:
                # ins_row may be dict or tuple
                if isinstance(ins_row, dict):
                    variant_id = ins_row.get('variant_id') or list(ins_row.values())[0]
                else:
                    variant_id = ins_row[0]
            else:
                # fallback to lastrowid (MySQL-style wrapper)
                variant_id = getattr(cursor, 'lastrowid', None)
        except Exception:
            # Some DB drivers (MySQL older) don't support RETURNING; fallback to separate insert + lastrowid
            cursor.execute("""
                INSERT INTO product_variants
                  (product_id, sku, size, color, price, color_hex, stock_count, is_default)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (product_id, vsku, size, color, price, color_hex, vstock, 0))
            variant_id = getattr(cursor, 'lastrowid', None)
            # if still None, try to fetch by unique fields (best-effort)
            if not variant_id:
                cursor.execute("SELECT variant_id FROM product_variants WHERE product_id = %s AND sku = %s ORDER BY created_at DESC LIMIT 1", (product_id, vsku))
                row = cursor.fetchone()
                if row:
                    if isinstance(row, dict):
                        variant_id = row.get('variant_id') or list(row.values())[0]
                    else:
                        variant_id = row[0]

        if not variant_id:
            raise Exception("Could not determine variant_id after insert.")

        # POSITION: find next position index for this variant (if any)
        cursor.execute("SELECT COALESCE(MAX(position), -1) AS m FROM product_images WHERE variant_id = %s", (variant_id,))
        p_row = cursor.fetchone()
        if p_row:
            if isinstance(p_row, dict):
                next_pos = (p_row.get('m') if p_row.get('m') is not None else -1) + 1
            else:
                next_pos = ((p_row[0] if p_row[0] is not None else -1) + 1)
        else:
            next_pos = 0

        # If no files uploaded, simply update product stock & commit
        if not files or all(not f or not getattr(f, 'filename', None) for f in files):
            # update product stock_count (recalculate sum)
            cursor.execute("SELECT COALESCE(SUM(stock_count),0) AS tot FROM product_variants WHERE product_id = %s", (product_id,))
            tot_row = cursor.fetchone()
            total_stock = 0
            if tot_row:
                if isinstance(tot_row, dict):
                    total_stock = int(tot_row.get('tot', 0) or 0)
                else:
                    total_stock = int(tot_row[0] if tot_row[0] is not None else 0)
            cursor.execute("UPDATE products SET stock_count = %s, updated_at = (now() AT TIME ZONE 'Asia/Kolkata') WHERE product_id = %s", (total_stock, product_id))

            conn.commit()
            flash("Variant added successfully.", "success")
            return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=variant_id))

        # Upload files to R2 and insert product_images rows (all in the same DB transaction)
        vpos = next_pos
        inserted_count = 0
        for f in (files or []):
            if not f or not getattr(f, 'filename', None):
                continue
            if not allowed_file(f.filename):
                # skip invalid extension
                continue
            orig = secure_filename(f.filename)
            unique = f"{product_id}_var{variant_id}_{vpos}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            filename = f"{unique}_{orig}"
            # key under the product's main/variants structure:
            # user asked: product images go in "products/{product_id}/variants/{variant_id}/..."
            key = f"products/{product_id}/variants/{variant_id}/{filename}"
            try:
                public_url = upload_to_r2(f, key)  # may raise
                # remember key in case we need to cleanup
                uploaded_r2_keys.append(key)

                # is_primary: if this is the first inserted image for this variant mark primary
                is_primary = 1 if (inserted_count == 0) else 0

                # Insert DB row using public_url as path
                cursor.execute(
                    "INSERT INTO product_images (product_id, variant_id, path, alt_text, position, is_primary) VALUES (%s,%s,%s,%s,%s,%s)",
                    (product_id, variant_id, public_url, None, vpos, is_primary)
                )
                vpos += 1
                inserted_count += 1
            except Exception as up_err:
                # Something went wrong uploading or inserting -> rollback & cleanup uploaded R2 objects
                current_app.logger.exception("Failed uploading/inserting variant image for product %s variant %s: %s", product_id, variant_id, up_err)
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                # attempt to delete any uploaded objects so far
                for k in uploaded_r2_keys:
                    try:
                        delete_from_r2(k)
                    except Exception:
                        current_app.logger.exception("Failed to cleanup R2 key %s after upload error", k)
                flash(f"Error saving variant image: {up_err}", "danger")
                return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=variant_id))

        # Recalculate product stock_count (sum of variant stock_count)
        cursor.execute("SELECT COALESCE(SUM(stock_count),0) AS tot FROM product_variants WHERE product_id = %s", (product_id,))
        tot_row = cursor.fetchone()
        total_stock = 0
        if tot_row:
            if isinstance(tot_row, dict):
                total_stock = int(tot_row.get('tot', 0) or 0)
            else:
                total_stock = int(tot_row[0] if tot_row[0] is not None else 0)
        cursor.execute("UPDATE products SET stock_count = %s, updated_at = (now() AT TIME ZONE 'Asia/Kolkata') WHERE product_id = %s", (total_stock, product_id))

        # All good -> commit
        conn.commit()
        flash("Variant added successfully.", "success")

        # After adding, redirect to product detail with the newly created variant selected
        return redirect(url_for('main.view_product_detail', product_id=product_id, variant_id=variant_id))

    except Exception as e:
        # catch-all: rollback & cleanup uploaded objects
        current_app.logger.exception("Unexpected error adding variant for product %s: %s", product_id, e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        for k in uploaded_r2_keys:
            try:
                delete_from_r2(k)
            except Exception:
                current_app.logger.exception("Failed to cleanup R2 key %s after unexpected error", k)
        flash(f"Unexpected error: {e}", "danger")
        return redirect(url_for('main.view_product_detail', product_id=product_id))
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# Delete a product


@main.route('/delete_product/<int:product_id>', methods=['POST'])
@nocache
def delete_product(product_id):
    # owner auth
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # ensure product exists
        cursor.execute("SELECT product_id, image_path FROM products WHERE product_id = %s", (product_id,))
        product = cursor.fetchone()
        if not product:
            flash("Product not found", "danger")
            return redirect(url_for('main.view_owner_products'))

        # fetch all image rows (product-level and variant-level) so we can remove from R2
        cursor.execute("SELECT image_id, path FROM product_images WHERE product_id = %s", (product_id,))
        rows = cursor.fetchall() or []

        # collect unique R2 keys to delete
        r2_keys_to_delete = set()

        for r in rows:
            path = r.get('path') or ''
            if not path:
                continue

            # try to derive R2 key from stored path/public url
            try:
                key = _r2_key_from_public_url(path)
                if key:
                    r2_keys_to_delete.add(key)
                else:
                    current_app.logger.debug("Could not derive R2 key from product_images.path: %s", path)
            except Exception as ex:
                current_app.logger.debug("Failed to compute R2 key for path %s : %s", path, ex)

        # also consider the standalone products.image_path (if set and different from product_images)
        prod_img = product.get('image_path') or ''
        if prod_img:
            try:
                key = _r2_key_from_public_url(prod_img)
                if key:
                    r2_keys_to_delete.add(key)
                else:
                    current_app.logger.debug("Could not derive R2 key from products.image_path: %s", prod_img)
            except Exception as ex:
                current_app.logger.debug("Failed to compute R2 key for product.image_path %s : %s", prod_img, ex)

        # Attempt to delete collected R2 objects (best-effort; log failures)
        for k in list(r2_keys_to_delete):
            try:
                ok = delete_from_r2(k)
                if not ok:
                    current_app.logger.warning("delete_from_r2 reported failure for key: %s", k)
            except Exception as ex:
                current_app.logger.exception("Exception while deleting R2 key %s: %s", k, ex)

        # Now delete the product row (assumes FK cascade will remove product_images/product_variants)
        cursor.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
        conn.commit()

        flash('Product deleted successfully!', 'success')
        return redirect(url_for('main.view_owner_products'))

    except Exception as e:
        if conn:
            conn.rollback()
        current_app.logger.exception("Error deleting product %s: %s", product_id, e)
        flash("An error occurred while deleting the product.", "danger")
        # safe fallback: redirect back to product detail page
        return redirect(url_for('main.view_product_detail', product_id=product_id))

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# --------------------- View and manage orders (customer and owner) ---------------------



@main.route('/delete_order_item', methods=['POST'])
def delete_order_item():
    if 'customer_id' not in session:
        flash("Please log in to delete order items.", "warning")
        return redirect(url_for('main.login'))

    order_id = request.form.get('order_id')
    product_name = request.form.get('product_name')
    if not order_id or not product_name:
        flash("Invalid request.", "danger")
        return redirect(url_for('main.view_orders'))

    conn = get_db()
    cursor = conn.cursor()
    # Get product_id from product_name (assuming product_name is unique, otherwise use product_id in form)
    cursor.execute("SELECT product_id FROM Products WHERE name = %s", (product_name,))
    product_row = cursor.fetchone()
    if not product_row:
        flash("Product not found.", "danger")
        cursor.close()
        conn.close()
        return redirect(url_for('main.view_orders'))
    product_id = product_row[0]

    # Get price and quantity for the item to be deleted
    cursor.execute("SELECT quantity, price FROM Order_Items WHERE order_id = %s AND product_id = %s", (order_id, product_id))
    item_row = cursor.fetchone()
    if not item_row:
        flash("Order item not found.", "danger")
        cursor.close()
        conn.close()
        return redirect(url_for('main.view_orders'))
    quantity, price = item_row
    item_total = quantity * price

    # Delete the item from Order_Items
    cursor.execute("DELETE FROM Order_Items WHERE order_id = %s AND product_id = %s", (order_id, product_id))
    conn.commit()

    # Update the order's total_amount to the sum of remaining order items
    cursor.execute("SELECT SUM(quantity * price) FROM Order_Items WHERE order_id = %s", (order_id,))
    new_total = cursor.fetchone()[0] or 0
    cursor.execute("UPDATE Orders SET total_amount = %s WHERE order_id = %s", (new_total, order_id))
    conn.commit()

    # If the order has no more items, delete the order itself
    cursor.execute("SELECT COUNT(*) FROM Order_Items WHERE order_id = %s", (order_id,))
    count = cursor.fetchone()[0]
    if count == 0:
        cursor.execute("DELETE FROM Orders WHERE order_id = %s", (order_id,))
        conn.commit()
        flash("Order deleted as it had no more items.", "success")
    else:
        flash("Order item deleted successfully!", "success")

    cursor.close()
    conn.close()
    return redirect(url_for('main.view_orders'))

#--------------------- include cancellation-request in allowed statuses (between delivered and cancelled)------------------
ALLOWED_STATUSES = ['processing', 'confirmed', 'out for delivery', 'delivered', 'cancellation-request', 'cancelled', 'refunded']

# or whatever route name you already used; keep route mapping same in your app
# --- back-end: owner_view_orders (updated to attach latest review by that customer for each item) ---

@main.route('/owner/orders')
@main.route('/owner-orders')
@nocache
def owner_view_orders():
    if 'owner_id' not in session:
        flash("Please log in as owner to view this page", "warning")
        return redirect('/login')

    status = request.args.get('status')
    q = request.args.get('q','').strip()
    sort = request.args.get('sort','date_desc')

    order_by_map = {
        'date_desc': 'o.order_date DESC, o.order_id DESC',
        'date_asc': 'o.order_date ASC, o.order_id ASC',
        'total_desc': 'o.total_amount DESC, o.order_date DESC',
        'total_asc': 'o.total_amount ASC, o.order_date DESC'
    }
    order_by = order_by_map.get(sort, order_by_map['date_desc'])

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    where_clauses = []
    params = []

    if status and status.lower() != 'all':
        where_clauses.append("o.status = %s")
        params.append(status)

    if q:
        like = f"%{q}%"
        where_clauses.append("(CAST(o.order_id AS CHAR) LIKE %s OR p.name LIKE %s OR pv.sku LIKE %s OR c.name LIKE %s OR ai.line1 LIKE %s OR ai.name LIKE %s)")
        params.extend([like, like, like, like, like, like])

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = f"""
        SELECT
            o.order_id,
            o.order_date,
            o.total_amount,
            o.currency,
            o.payment_status,
            o.payment_gateway,
            o.shipping_cost,
            o.status AS order_status,
            o.last_payment_id,
            c.customer_id,
            c.name AS customer_name,
            c.email AS customer_email,
            ai.address_id AS shipping_address_id,
            ai.name AS shipping_name,
            ai.phone AS shipping_phone,
            ai.line1 AS shipping_line1,
            ai.line2 AS shipping_line2,
            ai.city AS shipping_city,
            ai.state AS shipping_state,
            ai.postal_code AS shipping_postal_code,
            ai.country AS shipping_country,
            oi.order_item_id,
            oi.product_id,
            oi.variant_id,
            oi.quantity,
            oi.unit_price,
            oi.total_price,
            p.name AS product_name,
            p.image_path,
            pv.sku AS variant_sku,
            pv.size AS variant_size,
            pv.color AS variant_color
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        LEFT JOIN product_variants pv ON oi.variant_id = pv.variant_id
        LEFT JOIN addresses ai ON o.shipping_address_id = ai.address_id
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        {where_sql}
        ORDER BY {order_by}
        LIMIT 2000
    """

    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    orders = OrderedDict()
    for r in rows:
        oid = r['order_id']
        if oid not in orders:
            orders[oid] = {
                "order_date": r['order_date'],
                "total_amount": r['total_amount'],
                "currency": r.get('currency') or 'INR',
                "payment_status": r.get('payment_status'),
                "payment_gateway": r.get('payment_gateway'),
                "shipping_cost": r.get('shipping_cost') or 0.00,
                "order_status": r.get('order_status'),
                "customer": {
                    "customer_id": r.get('customer_id'),
                    "name": r.get('customer_name'),
                    "email": r.get('customer_email')
                },
                "shipping_address": {
                    "address_id": r.get('shipping_address_id'),
                    "name": r.get('shipping_name'),
                    "phone": r.get('shipping_phone'),
                    "line1": r.get('shipping_line1'),
                    "line2": r.get('shipping_line2'),
                    "city": r.get('shipping_city'),
                    "state": r.get('shipping_state'),
                    "postal_code": r.get('shipping_postal_code'),
                    "country": r.get('shipping_country'),
                },
                "items": []
            }
        orders[oid]['items'].append({
            "order_item_id": r.get('order_item_id'),
            "product_id": r.get('product_id'),
            "variant_id": r.get('variant_id'),
            "product_name": r.get('product_name'),
            "image_path": r.get('image_path').replace('\\','/') if r.get('image_path') else None,
            "quantity": r.get('quantity'),
            "unit_price": float(r['unit_price']) if r['unit_price'] is not None else None,
            "total_price": float(r['total_price']) if r['total_price'] is not None else None,
            "variant": {
                "sku": r.get('variant_sku'),
                "size": r.get('variant_size'),
                "color": r.get('variant_color')
            },
            "review": None
        })

    # --- Attach review for the specific order/item if it exists ---
    # NOTE: this requires product_reviews.order_id column to exist and link to orders.order_id
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        for oid, od in orders.items():
            cust_id = od['customer'].get('customer_id')
            if not cust_id:
                continue
            for item in od['items']:
                try:
                    # Find review for this exact order + product + customer
                    cursor.execute("""
                        SELECT review_id, rating, title, body, created_at
                        FROM product_reviews
                        WHERE product_id = %s AND customer_id = %s AND order_id = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, (item['product_id'], cust_id, oid))
                    rev = cursor.fetchone()
                    if rev:
                        try:
                            created_at_str = rev['created_at'].strftime('%b %d, %Y') if rev.get('created_at') else ''
                        except Exception:
                            created_at_str = str(rev.get('created_at') or '')
                        item['review'] = {
                            'review_id': rev.get('review_id'),
                            'rating': int(rev.get('rating') or 0),
                            'title': rev.get('title') or '',
                            'body': rev.get('body') or '',
                            'created_at_str': created_at_str
                        }
                except Exception:
                    current_app.logger.exception("Error fetching review for product %s customer %s order %s",
                                                  item['product_id'], cust_id, oid)
        cursor.close()
        conn.close()
    except Exception:
        current_app.logger.exception("Error while attaching reviews to orders")

    return render_template(
        "owner/view_orders.html",
        orders=orders,
        current_status=(status or 'all'),
        q=q,
        sort=sort,
        allowed_statuses=ALLOWED_STATUSES
    )



@main.route('/owner/update_order_status', methods=['POST'])
def owner_update_order_status():
    """
    Accepts JSON or form data:
      { order_id: <id>, new_status: <status> }
    - requires owner_id in session
    - validates new_status is allowed
    - updates orders.status and updated_at
    - flashes a message to be displayed after reload
    - returns JSON {ok: True/False, message: ...}
    """
    if 'owner_id' not in session:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or request.form or {}
    order_id = data.get('order_id')
    new_status = (data.get('new_status') or '').strip().lower()

    if not order_id or not new_status:
        return jsonify({"ok": False, "error": "missing parameters"}), 400

    if new_status not in ALLOWED_STATUSES:
        return jsonify({"ok": False, "error": "invalid status"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        # Update status and updated_at for clarity (DB may auto-update)
        cursor.execute("UPDATE orders SET status = %s, updated_at = NOW() WHERE order_id = %s", (new_status, order_id))
        conn.commit()
        # Flash a message so owner sees it after reload
        flash(f"Order #{order_id} status updated to '{new_status}'.", "success")
    except Exception as e:
        conn.rollback()
        logging.exception("Error updating order status: %s", e)
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(e)}), 500

    cursor.close()
    conn.close()
    return jsonify({"ok": True, "order_id": order_id, "new_status": new_status})