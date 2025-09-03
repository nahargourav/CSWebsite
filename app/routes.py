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

# Environment helpers
from dotenv import load_dotenv

# Third-party / Flask
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    current_app, session, make_response, jsonify, send_file
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from markupsafe import escape, Markup

# OAuth / auth helpers
from flask_dance.contrib.google import make_google_blueprint, google
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Database
import mysql.connector
from app.db.db_config import get_db

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

# ---------------------------profile section--------------------------------------------


# ---- Profile page (tabs: profile, addresses, security) ----
@main.route('/profile')
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
@nocache
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
        flash("Please login to add products.", "warning")
        return redirect(url_for('main.login'))
    """
    Add a variant to cart stored in session.
    Expected form fields: product_id, variant_id, qty
    """
    product_id = request.form.get('product_id')
    variant_id = request.form.get('variant_id')
    qty_raw = request.form.get('qty') or '1'
    print("adding to cart")
    # basic validation
    if not product_id or not variant_id:
        flash("Invalid request. Missing product/variant.", "danger")
        return redirect(request.referrer or url_for('main.view_products'))
    print("fetched product id , now adding to cart")
    try:
        qty = int(qty_raw)
    except (ValueError, TypeError):
        qty = 1
    if qty < 1:
        qty = 1

    # fetch variant and product details to validate stock and get price/sku
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM product_variants WHERE variant_id = %s AND product_id = %s", (variant_id, product_id))
    variant = cursor.fetchone()
    if not variant:
        cursor.close()
        conn.close()
        flash("Selected variant not found.", "danger")
        return redirect(request.referrer or url_for('main.view_products'))

    cursor.execute("SELECT name, image_path, sku as product_sku FROM products WHERE product_id = %s", (product_id,))
    p = cursor.fetchone()
    cursor.close()
    conn.close()

    # stock check
    max_avail = int(variant.get('stock_count') or 0)
    if max_avail <= 0:
        flash("Sorry, this variant is out of stock.", "warning")
        return redirect(request.referrer or url_for('main.view_products'))

    # clamp qty to available stock
    if qty > max_avail:
        qty = max_avail
        flash(f"Quantity reduced to available stock ({max_avail}).", "info")

    # prepare cart item data
    price = float(variant.get('price') or 0.0)
    sku = variant.get('sku') or ''
    name = p.get('name') if p else ''
    # choose image: variant primary image if present else product image
    image_path = None
    # try to find variant image from product_images table or session? easiest: attempt to find product_images/variant_images by re-querying DB
    # but to avoid extra queries here, use product image as fallback
    image_path = p.get('image_path') if p and p.get('image_path') else None

    # Add to session cart structure: session['cart'] = [ {cart_item_id, product_id, variant_id, sku, name, price, qty, image_path, max_qty}, ... ]
    cart = session.get('cart', [])

    # Try to merge with existing same product+variant item
    merged = False
    for item in cart:
        if str(item.get('variant_id')) == str(variant_id) and str(item.get('product_id')) == str(product_id):
            new_qty = int(item.get('qty', 0)) + qty
            if new_qty > max_avail:
                new_qty = max_avail
                flash(f"Quantity limited to available stock ({max_avail}).", "info")
            item['qty'] = new_qty
            item['max_qty'] = max_avail
            merged = True
            break

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
    # optional: also set session.modified True to be sure
    session.modified = True

    flash("Added to cart", "success")
    # redirect back to product page
    return redirect(url_for('main.view_prod_detail', product_id=product_id))


# Backend: cart routes (drop in to your routes file)

@main.route('/cart')
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
                    flash(f"Quantity limited to available stock ({max_qty}).", "info")
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

    order_id = request.form.get('order_id')
    if not order_id:
        flash("Missing order id", "warning")
        return redirect(url_for('main.view_orders'))

    try:
        order_id = int(order_id)
    except ValueError:
        flash("Invalid order id", "danger")
        return redirect(url_for('main.view_orders'))

    # DB lookup
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT customer_id FROM orders WHERE order_id = %s", (order_id,))
        o = cursor.fetchone()
        if not o:
            flash("Order not found", "danger")
            return redirect(url_for('main.view_orders'))

        # permission: owner/admin can download any invoice
        is_owner = ('owner_id' in session) or session.get('is_owner', False)
        if not is_owner:
            # must be the customer who owns the order
            if 'customer_id' not in session or int(o.get('customer_id')) != int(session.get('customer_id')):
                flash("Permission denied", "danger")
                return redirect(url_for('main.view_orders'))

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
            return redirect(url_for('main.view_orders'))

        invoice_fname = p.get('invoice_path')

        # determine invoice dir (use configured or fallback)
        invoice_dir = current_app.config.get('INVOICE_DIR')
        if not invoice_dir:
            invoice_dir = os.path.join(current_app.instance_path, 'invoices')

        # Build safe absolute path and ensure it's within invoice_dir
        invoice_dir_abs = os.path.abspath(invoice_dir)
        fullpath = os.path.abspath(os.path.join(invoice_dir_abs, invoice_fname))

        # simple safety check to ensure invoice file is in invoice_dir
        if not fullpath.startswith(invoice_dir_abs + os.sep) and fullpath != invoice_dir_abs:
            current_app.logger.error("Potential invoice path traversal attempt: %s", fullpath)
            flash("Invalid invoice path", "danger")
            return redirect(url_for('main.view_orders'))

        if not os.path.exists(fullpath) or not os.path.isfile(fullpath):
            current_app.logger.error("Invoice file missing: %s", fullpath)
            flash("Invoice file missing", "danger")
            return redirect(url_for('main.view_orders'))

        # send file for download
        # If your Flask version is older and does not support download_name,
        # replace download_name=<name> with attachment_filename=<name>
        return send_file(fullpath, as_attachment=True, download_name=os.path.basename(fullpath))

    except Exception as e:
        current_app.logger.exception("Error while trying to download invoice for order %s: %s", order_id, e)
        flash("Unable to download invoice. Try again.", "danger")
        return redirect(url_for('main.view_orders'))
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


# -----------------view orders--------------

@main.route('/orders')
def view_orders():
    if 'customer_id' not in session:
        flash("Please log in to view orders.", "warning")
        return redirect('/login')

    customer_id = session['customer_id']
    status = request.args.get('status')  # e.g. processing,confirmed,out for delivery,delivered,cancelled,refunded
    q = request.args.get('q','').strip()
    sort = request.args.get('sort','date_desc')  # date_desc,date_asc,total_desc,total_asc

    order_by_map = {
        'date_desc': 'o.order_date DESC, o.order_id DESC',
        'date_asc': 'o.order_date ASC, o.order_id ASC',
        'total_desc': 'o.total_amount DESC, o.order_date DESC',
        'total_asc': 'o.total_amount ASC, o.order_date DESC'
    }
    order_by = order_by_map.get(sort, order_by_map['date_desc'])

    where_clauses = ["o.customer_id = %s"]
    params = [customer_id]

    if status and status.lower() != 'all':
        where_clauses.append("o.status = %s")
        params.append(status)

    if q:
        like = f"%{q}%"
        where_clauses.append("(CAST(o.order_id AS CHAR) LIKE %s OR p.name LIKE %s OR pv.sku LIKE %s OR ai.name LIKE %s OR ai.line1 LIKE %s)")
        params.extend([like, like, like, like, like])

    where_sql = " AND ".join(where_clauses)

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
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT 500
    """

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # group items by order_id
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
        orders[oid]['items'].append({
            "order_item_id": r['order_item_id'],
            "product_id": r['product_id'],
            "variant_id": r.get('variant_id'),
            "product_name": r['product_name'],
            "image_path": r.get('image_path'),
            "quantity": r['quantity'],
            "unit_price": float(r['unit_price']) if r['unit_price'] is not None else None,
            "total_price": float(r['total_price']) if r['total_price'] is not None else (float(r['unit_price'] or 0) * int(r['quantity'] or 0)),
            "variant": {
                "sku": r.get('variant_sku'),
                "size": r.get('variant_size'),
                "color": r.get('variant_color')
            },
            # default reviewed flag (will mark later)
            "reviewed": False
        })

    # --- Mark items that already have reviews for that order by this customer ---
    try:
        order_ids = list(orders.keys())
        if order_ids:
            conn = get_db()
            cur = conn.cursor(dictionary=True)
            placeholders = ','.join(['%s'] * len(order_ids))
            # first param is customer_id, then the order ids
            params = [customer_id] + order_ids
            qrev = f"SELECT product_id, order_id FROM product_reviews WHERE customer_id = %s AND order_id IN ({placeholders})"
            cur.execute(qrev, tuple(params))
            rev_rows = cur.fetchall()
            cur.close()
            conn.close()

            reviewed_pairs = set()
            for rr in rev_rows:
                try:
                    reviewed_pairs.add((int(rr['order_id']), int(rr['product_id'])))
                except Exception:
                    pass

            for oid, order in orders.items():
                for it in order['items']:
                    pair = (int(oid), int(it['product_id']))
                    it['reviewed'] = pair in reviewed_pairs
    except Exception as e:
        # don't fail page display on review-marking errors
        current_app.logger.exception("Could not mark reviewed items: %s", str(e))

    return render_template(
        "customer/view_orders.html",
        orders=orders,
        current_status=(status or 'all'),
        q=q,
        sort=sort
    )


@main.route('/submit_review', methods=['POST'])
def submit_review():
    if 'customer_id' not in session:
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
        flash("Missing product or order information.", "danger")
        return redirect(url_for('main.view_orders'))

    if not rating or rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5.", "warning")
        return redirect(url_for('main.view_orders'))

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        # verify order belongs to customer and is delivered
        cur.execute("SELECT status, customer_id FROM orders WHERE order_id = %s LIMIT 1", (order_id,))
        row = cur.fetchone()
        if not row:
            flash("Order not found.", "danger")
            return redirect(url_for('main.view_orders'))

        if int(row.get('customer_id')) != customer_id:
            flash("You are not authorized to review for this order.", "danger")
            return redirect(url_for('main.view_orders'))

        order_status = (row.get('status') or '').strip().lower()
        if order_status != 'delivered':
            flash("You can only review products from delivered orders.", "warning")
            return redirect(url_for('main.view_orders'))

        # verify the product was part of the order (and variant if provided)
        if variant_id:
            cur.execute("SELECT 1 FROM order_items WHERE order_id = %s AND product_id = %s AND variant_id = %s LIMIT 1",
                        (order_id, product_id, variant_id))
        else:
            cur.execute("SELECT 1 FROM order_items WHERE order_id = %s AND product_id = %s LIMIT 1", (order_id, product_id))
        if not cur.fetchone():
            flash("This product was not part of the selected order.", "danger")
            return redirect(url_for('main.view_orders'))

        # prevent duplicate review for the same (product, customer, order)
        cur.execute("SELECT 1 FROM product_reviews WHERE product_id = %s AND customer_id = %s AND order_id = %s LIMIT 1",
                    (product_id, customer_id, order_id))
        if cur.fetchone():
            flash("You have already reviewed this product for that order.", "info")
            return redirect(url_for('main.view_orders'))

        # insert review (is_verified_purchase = 1 because we verified the order)
        cur.execute("""
            INSERT INTO product_reviews
              (product_id, customer_id, rating, title, body, is_verified_purchase, order_id, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (product_id, customer_id, rating, title or None, body or None, 1, order_id))
        conn.commit()
        flash("Thank you — your review has been submitted.", "success")
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Error saving review: %s", str(e))
        flash("An error occurred while saving your review. Please try again.", "danger")
    finally:
        try: cur.close()
        except: pass
        try: conn.close()
        except: pass

    return redirect(url_for('main.view_orders'))


# -------------------------request order cancellation---------------


@main.route('/request_order_cancellation', methods=['POST'])
def request_order_cancellation():
    # ensure logged-in
    if 'customer_id' not in session:
        return redirect(url_for('main.login'))

    # fetch order_id from frontend form
    order_id = request.form.get('order_id', type=int)
    if not order_id:
        flash('Invalid order id.', 'warning')
        return redirect(url_for('main.view_orders'))

    # get customer id from session (safe cast to int)
    try:
        customer_id = int(session.get('customer_id'))
    except (TypeError, ValueError):
        flash('Session error. Please log in again.', 'warning')
        return redirect(url_for('main.login'))

    conn = get_db()
    if conn is None:
        flash('Database connection error.', 'danger')
        return redirect(url_for('main.view_orders'))

    cur = None
    try:
        cur = conn.cursor()
        # fetch current status and owner
        cur.execute("SELECT status, customer_id FROM orders WHERE order_id = %s", (order_id,))
        row = cur.fetchone()
        if not row:
            flash('Order not found.', 'warning')
            return redirect(url_for('main.view_orders'))

        status_from_db, owner_id = row[0], row[1]

        # ensure the logged-in customer owns this order
        if owner_id != customer_id:
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
                flash('Cancellation request submitted successfully. We will review and update your order shortly.', 'success')
            else:
                # unexpected: nothing updated
                flash('Unable to update order. Please try again.', 'danger')
        elif curr in ('cancellation-request', 'cancellation requested'):
            flash('A cancellation request is already in progress for this order.', 'info')
        else:
            flash('This order cannot be cancelled at its current stage.', 'warning')

    except Exception as e:
        # log e if you have logging; rollback to be safe
        try:
            conn.rollback()
        except Exception:
            pass
        flash('An error occurred while processing your request. Please try again later.', 'danger')
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass

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


ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif"}


def allowed_file(filename):
    return bool(filename) and "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXT


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

        # Variant arrays (may contain empty entries — we will filter them)
        variant_sizes = request.form.getlist('variant_size[]')
        variant_colors = request.form.getlist('variant_color[]')
        variant_color_hex = request.form.getlist('variant_color_hex[]')
        variant_skus = request.form.getlist('variant_sku[]')
        variant_prices = request.form.getlist('variant_price[]')
        variant_stocks = request.form.getlist('variant_stock[]')

        # Additional product-level images (optional)
        additional_images = request.files.getlist('images')

        if not name:
            flash("Product name is required", "danger")
            return render_template('owner/add_product.html')

        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()

            # generate SKU if not provided
            if not sku:
                base = ''.join(ch for ch in (name or 'prod') if ch.isalnum())[:20]
                sku = f"{base}{int(time.time()) % 10000}"

            # insert product (image_path set below if main image uploaded)
            insert_product_q = """
                INSERT INTO products
                (name, brand, sku, category, short_description, description, image_path,
                 currency, stock_count, weight, material, fit, pattern, occasion,
                 season, sustainability, care_instructions, is_returnable, is_active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """
            product_values = (
                name, brand, sku, category, short_description, description, None,
                currency, 0, weight, material, fit, pattern, occasion,
                season, sustainability, care_instructions, is_returnable, is_active
            )
            cursor.execute(insert_product_q, product_values)
            product_id = cursor.lastrowid
            print(f"[DEBUG] Inserted product_id={product_id}")

            # compute upload dir inside the Flask app root so it's reliable
            UPLOAD_BASE = os.path.join(current_app.root_path, 'static', 'uploads', 'products')
            os.makedirs(UPLOAD_BASE, exist_ok=True)
            print(f"[DEBUG] Upload base path: {UPLOAD_BASE}")

            # ---------- Save main product image (ONLY to products.image_path) ----------
            if main_image and main_image.filename and allowed_file(main_image.filename):
                orig = secure_filename(main_image.filename)
                unique = f"{product_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                filename = f"{unique}_{orig}"
                saved_path = os.path.join(UPLOAD_BASE, filename)
                try:
                    main_image.save(saved_path)
                    rel_path = os.path.join('uploads', 'products', filename).replace(os.path.sep, '/')
                    cursor.execute("UPDATE products SET image_path = %s WHERE product_id = %s", (rel_path, product_id))
                    print(f"[DEBUG] Saved main image to {saved_path} (exists: {os.path.exists(saved_path)})")
                except Exception as e:
                    print(f"[ERROR] Failed saving main image: {e}")
                    flash(f"Failed to save main image: {e}", "danger")
                    # continue — do not abort entire product creation for one save failure

            # ---------- Save additional product-level images (if any) ----------
            pos = 1
            for img in (additional_images or []):
                if img and img.filename and allowed_file(img.filename):
                    orig = secure_filename(img.filename)
                    filename = f"{product_id}_add_{pos}_{int(time.time())}_{uuid.uuid4().hex[:6]}_{orig}"
                    saved_path = os.path.join(UPLOAD_BASE, filename)
                    try:
                        img.save(saved_path)
                        rel = os.path.join('uploads', 'products', filename).replace(os.path.sep, '/')
                        cursor.execute(
                            "INSERT INTO product_images (product_id, variant_id, path, alt_text, position, is_primary) VALUES (%s,%s,%s,%s,%s,%s)",
                            (product_id, None, rel, None, pos, 0)
                        )
                        print(f"[DEBUG] Saved additional product image {saved_path} (exists: {os.path.exists(saved_path)})")
                        pos += 1
                    except Exception as e:
                        print(f"[ERROR] Failed saving additional product image: {e}")
                        # continue

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
                """
                1) Try request.files.getlist(f"variant_images_{idx}") -> preferred
                2) Fallback: collect any request.files entries whose key startswith "variant_images_{idx}"
                   or contains the index in brackets (some browsers/tools send variant_images_0[] or variant_images_0)
                3) As a last resort, scan all request.files and pick names containing "_{idx}" (conservative)
                """
                files = []
                try:
                    files = request.files.getlist(f"variant_images_{idx}") or []
                except Exception:
                    files = []

                # fallback heuristics
                if not files:
                    for key in request.files:
                        if key == f"variant_images_{idx}" or key.startswith(f"variant_images_{idx}") or key.endswith(f"_{idx}") or f"[{idx}]" in key:
                            files.extend(request.files.getlist(key))
                # final fallback: any key that contains f"variant_images" and idx as substring
                if not files:
                    for key in request.files:
                        if "variant_images" in key and str(idx) in key:
                            files.extend(request.files.getlist(key))
                # ensure unique file objects (avoid duplicates)
                unique_files = []
                seen_names = set()
                for f in files:
                    name = getattr(f, 'filename', None)
                    if name and name not in seen_names:
                        seen_names.add(name)
                        unique_files.append(f)
                return unique_files

            # ---------- Insert variants and save variant images ----------
            total_stock_from_variants = 0
            first_variant_has_images = False

            for idx, v in enumerate(variants):
                vindex = idx + 1
                vsku = v['sku'] or f"{sku}{vindex}"
                is_def = 1 if idx == 0 else 0

                cursor.execute(
                    """INSERT INTO product_variants
                       (product_id, sku, size, color, price, color_hex, stock_count, is_default)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (product_id, vsku, v['size'], v['color'], v['price'], v['color_hex'], v['stock'], is_def)
                )
                variant_id = cursor.lastrowid
                total_stock_from_variants += v['stock']
                print(f"[DEBUG] Inserted variant id={variant_id} sku={vsku} stock={v['stock']}")

                # collect files robustly for this variant index
                vfiles = collect_variant_files(idx)
                print(f"[DEBUG] Collected {len(vfiles)} file(s) for variant index {idx}: keys -> {[getattr(f, 'filename', None) for f in vfiles]}")

                vpos = 0
                for vf in vfiles:
                    if vf and getattr(vf, 'filename', None) and allowed_file(vf.filename):
                        orig = secure_filename(vf.filename)
                        filename = f"{product_id}_var{idx}_{vpos}_{int(time.time())}_{uuid.uuid4().hex[:6]}_{orig}"
                        saved_path = os.path.join(UPLOAD_BASE, filename)
                        try:
                            vf.save(saved_path)
                            vrel = os.path.join('uploads', 'products', filename).replace(os.path.sep, '/')
                            is_primary = 1 if (idx == 0 and vpos == 0 and not first_variant_has_images) else 0
                            cursor.execute(
                                "INSERT INTO product_images (product_id, variant_id, path, alt_text, position, is_primary) VALUES (%s,%s,%s,%s,%s,%s)",
                                (product_id, variant_id, vrel, None, vpos, is_primary)
                            )
                            print(f"[DEBUG] Saved variant image to {saved_path} (exists: {os.path.exists(saved_path)})")
                            vpos += 1
                        except Exception as e:
                            print(f"[ERROR] Failed saving variant image {orig}: {e}")
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

        except mysql.connector.Error as err:
            if conn:
                conn.rollback()
            print("[MYSQL ERROR]", err)
            flash(f'Error adding product: {err}', 'danger')
            return render_template('owner/add_product.html')
        except Exception as e:
            if conn:
                conn.rollback()
            print("[UNEXPECTED ERROR]", e)
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



@main.route('/product/<int:product_id>')
@nocache
def view_product_detail(product_id):
    """
    Fetch product, its variants (default first), product-level images,
    and variant images grouped by variant_id. Pass to template.
    """
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Fetch product row
    cursor.execute("SELECT * FROM products WHERE product_id = %s", (product_id,))
    product = cursor.fetchone()
    if not product:
        cursor.close()
        conn.close()
        flash("Product not found", "danger")
        return redirect(url_for('main.view_owner_products'))

    # Normalize image_path
    if product.get('image_path'):
        product['image_path'] = product['image_path'].replace('\\', '/')

    # Fetch variants, ordering default variant first (so it will be variants[0])
    cursor.execute("""
        SELECT pv.* 
        FROM product_variants pv
        WHERE pv.product_id = %s
        ORDER BY pv.is_default DESC, pv.variant_id ASC
    """, (product_id,))
    variants = cursor.fetchall()  # list of dicts

    # Convert numeric fields to proper python types for templates
    for v in variants:
        v['price'] = float(v['price'] or 0.0)
        v['stock_count'] = int(v['stock_count'] or 0)
        # ensure string fields aren't None in template
        for f in ('sku', 'size', 'color', 'color_hex'):
            if f in v and v[f] is None:
                v[f] = ''

    # Fetch product-level images (variant_id IS NULL), order by is_primary desc then position
    cursor.execute("""
        SELECT * FROM product_images
        WHERE product_id = %s AND variant_id IS NULL
        ORDER BY is_primary DESC, position ASC, image_id ASC
    """, (product_id,))
    product_images = cursor.fetchall()
    for pi in product_images:
        pi['path'] = pi['path'].replace('\\', '/')

    # Fetch variant images (variant_id IS NOT NULL) and group them by variant_id
    cursor.execute("""
        SELECT * FROM product_images
        WHERE product_id = %s AND variant_id IS NOT NULL
        ORDER BY variant_id ASC, position ASC, image_id ASC
    """, (product_id,))
    all_variant_images = cursor.fetchall()
    variant_images = {}
    for img in all_variant_images:
        img['path'] = img['path'].replace('\\', '/')
        vid = img['variant_id']
        if vid not in variant_images:
            variant_images[vid] = []
        variant_images[vid].append(img)

    cursor.close()
    conn.close()

    # If there is no product-level image, but variants exist and the default variant has images,
    # use the first variant image as fallback for initial display in templates.
    return render_template(
        'owner/product_detail.html',
        product=product,
        variants=variants,
        product_images=product_images,
        variant_images=variant_images
    )


# Delete a product
@main.route('/delete_product/<int:product_id>', methods=['POST'])
@nocache
def delete_product(product_id):
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    # remove image files recorded in product_images
    cursor.execute("SELECT path FROM product_images WHERE product_id = %s", (product_id,))
    rows = cursor.fetchall()
    for r in rows:
        if r and r.get('path'):
            image_path = os.path.join(current_app.static_folder, r['path'])
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception:
                    pass

    # delete product will cascade to images and variants via FK
    cursor.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
    conn.commit()
    conn.close()

    flash('Product deleted successfully!', 'success')
    return redirect('/view-products')

# put near your other imports at top of routes file


# ---------- Delete variant route ----------
@main.route('/product/<int:product_id>/variant/<int:variant_id>/delete', methods=['POST'])
@nocache
def delete_variant(product_id, variant_id):
    if 'owner_id' not in session:
        flash("Please log in as an owner.", "warning")
        return redirect('/login')

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Fetch all image paths for this variant
        cursor.execute("SELECT path FROM product_images WHERE variant_id = %s", (variant_id,))
        rows = cursor.fetchall()
        # Delete files from disk
        for (path,) in rows:
            if not path:
                continue
            abs_path = os.path.join(current_app.root_path, 'static', path.replace('/', os.path.sep))
            try:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            except Exception as e:
                # log but continue
                print(f"[WARN] Failed to remove file {abs_path}: {e}")

        # Remove image rows from DB
        cursor.execute("DELETE FROM product_images WHERE variant_id = %s", (variant_id,))

        # Remove variant row
        cursor.execute("DELETE FROM product_variants WHERE variant_id = %s AND product_id = %s", (variant_id, product_id))

        # Recalculate total product stock from remaining variants and update products table
        cursor.execute("SELECT COALESCE(SUM(stock_count),0) FROM product_variants WHERE product_id = %s", (product_id,))
        total_stock = cursor.fetchone()[0] or 0
        cursor.execute("UPDATE products SET stock_count = %s WHERE product_id = %s", (total_stock, product_id))

        conn.commit()
        flash("Variant deleted successfully.", "success")
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print("[MYSQL ERROR] deleting variant:", err)
        flash(f"Error deleting variant: {err}", "danger")
    except Exception as e:
        if conn:
            conn.rollback()
        print("[ERROR] deleting variant:", e)
        flash(f"Unexpected error: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

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
    try:
        conn = get_db()
        cursor = conn.cursor()

        # If SKU not provided, generate a SKU from product sku + timestamp fallback
        cursor.execute("SELECT sku FROM products WHERE product_id = %s", (product_id,))
        prod_row = cursor.fetchone()
        prod_sku = prod_row[0] if prod_row and prod_row[0] else f"P{product_id}"
        if not vsku:
            vsku = f"{prod_sku}{int(time.time()) % 10000}"

        # insert variant
        cursor.execute("""
            INSERT INTO product_variants
            (product_id, sku, size, color, price, color_hex, stock_count, is_default)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (product_id, vsku, size, color, price, color_hex, vstock, 0))
        variant_id = cursor.lastrowid

        # prepare upload dir
        UPLOAD_BASE = os.path.join(current_app.root_path, 'static', 'uploads', 'products')
        os.makedirs(UPLOAD_BASE, exist_ok=True)

        # save each file and insert into product_images
        vpos = 0
        for f in (files or []):
            if f and getattr(f, 'filename', None) and allowed_file(f.filename):
                orig = secure_filename(f.filename)
                unique = f"{product_id}_var{variant_id}_{vpos}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                filename = f"{unique}_{orig}"
                saved_path = os.path.join(UPLOAD_BASE, filename)
                try:
                    f.save(saved_path)
                    rel = os.path.join('uploads', 'products', filename).replace(os.path.sep, '/')
                    # is_primary: if this is the very first image for this variant, mark as primary(0/1) -> keep 1 for first
                    is_primary = 1 if vpos == 0 else 0
                    cursor.execute(
                        "INSERT INTO product_images (product_id, variant_id, path, alt_text, position, is_primary) VALUES (%s,%s,%s,%s,%s,%s)",
                        (product_id, variant_id, rel, None, vpos, is_primary)
                    )
                    vpos += 1
                except Exception as e:
                    print("[ERROR] saving variant image:", e)
                    # continue with other files

        # update product stock_count (recalculate sum)
        cursor.execute("SELECT COALESCE(SUM(stock_count),0) FROM product_variants WHERE product_id = %s", (product_id,))
        total_stock = cursor.fetchone()[0] or 0
        cursor.execute("UPDATE products SET stock_count = %s WHERE product_id = %s", (total_stock, product_id))

        conn.commit()
        flash("Variant added successfully.", "success")
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print("[MYSQL ERROR] adding variant:", err)
        flash(f"Error adding variant: {err}", "danger")
    except Exception as e:
        if conn:
            conn.rollback()
        print("[ERROR] adding variant:", e)
        flash(f"Unexpected error: {e}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('main.view_product_detail', product_id=product_id))


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

@main.route('/owner/orders')
@main.route('/owner-orders')
def owner_view_orders():
    if 'owner_id' not in session:
        flash("Please log in as owner to view this page", "warning")
        return redirect('/owner/login')

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
            "image_path": r.get('image_path'),
            "quantity": r.get('quantity'),
            "unit_price": float(r['unit_price']) if r['unit_price'] is not None else None,
            "total_price": float(r['total_price']) if r['total_price'] is not None else None,
            "variant": {
                "sku": r.get('variant_sku'),
                "size": r.get('variant_size'),
                "color": r.get('variant_color')
            }
        })

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
