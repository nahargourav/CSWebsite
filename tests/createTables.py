#!/usr/bin/env python3
"""
tests/createTables.py

Robust DDL applier (fixed):
  - Extracts statements robustly (keeps multiline statements intact, respects single/double quotes,
    line/block comments and dollar-quoted ($tag$) blocks).
  - Strips leading '--' comment lines when classifying a statement so CREATE TABLE blocks
    that start with a comment are correctly detected.
  - Executes in order: drops -> create tables -> indexes & constraints
  - Uses DATABASE_URL (env or hardcoded fallback). Prints masked DB URL.

Usage:
  export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
  python tests/createTables.py
"""
import os
import re
import sys
from dotenv import load_dotenv
import psycopg2
from urllib.parse import urlparse

load_dotenv()

# ---------- Put your full DDL here ----------
DDL = r"""
-- DROP existing tables (remove constraints/indexes via CASCADE)
DROP TABLE IF EXISTS public.product_tags CASCADE;
DROP TABLE IF EXISTS public.product_images CASCADE;
DROP TABLE IF EXISTS public.product_variants CASCADE;
DROP TABLE IF EXISTS public.product_reviews CASCADE;
DROP TABLE IF EXISTS public.order_items CASCADE;
DROP TABLE IF EXISTS public.payments CASCADE;
DROP TABLE IF EXISTS public.orders CASCADE;
DROP TABLE IF EXISTS public.addresses CASCADE;
DROP TABLE IF EXISTS public.tags CASCADE;
DROP TABLE IF EXISTS public.products CASCADE;
DROP TABLE IF EXISTS public.owners CASCADE;
DROP TABLE IF EXISTS public.customers CASCADE;
DROP TABLE IF EXISTS public.registration_otps CASCADE;
DROP TABLE IF EXISTS public.wishlist CASCADE;
DROP TABLE IF EXISTS public.contact_messages CASCADE;
DROP TABLE IF EXISTS public.applications CASCADE;
DROP TABLE IF EXISTS public.roles CASCADE;
DROP TABLE IF EXISTS public.bestsellers CASCADE;

-- Re-create tables (timestamps store India local wall-clock time via DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'))
-- Note: foreign keys will be added later via idempotent ALTER / DO blocks to avoid ordering issues.

-- customers
CREATE TABLE public.customers (
  customer_id serial PRIMARY KEY,
  name varchar(100) NOT NULL,
  email varchar(100) NOT NULL,
  password_hash varchar(255) NOT NULL,
  phone varchar(20),
  is_active smallint NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  updated_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- owners
CREATE TABLE public.owners (
  owner_id serial PRIMARY KEY,
  name varchar(100) NOT NULL,
  email varchar(100) NOT NULL,
  password_hash varchar(255) NOT NULL,
  phone varchar(20),
  is_active smallint NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  updated_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- products
CREATE TABLE public.products (
  product_id serial PRIMARY KEY,
  name varchar(200) NOT NULL,
  brand varchar(100),
  sku varchar(64),
  category varchar(150),
  short_description text,
  description text,
  image_path varchar(255),
  currency varchar(10) NOT NULL DEFAULT 'INR',
  stock_count integer NOT NULL DEFAULT 0 CHECK (stock_count >= 0),
  weight numeric(8,3),
  material varchar(255),
  fit varchar(50),
  care_instructions text,
  pattern varchar(50),
  occasion varchar(50),
  season varchar(50),
  sustainability varchar(255),
  rating_avg numeric(3,2) NOT NULL DEFAULT 0.00 CHECK (rating_avg >= 0 AND rating_avg <= 5),
  reviews_count integer NOT NULL DEFAULT 0 CHECK (reviews_count >= 0),
  is_returnable smallint NOT NULL DEFAULT 1 CHECK (is_returnable IN (0,1)),
  is_active smallint NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  updated_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- product_variants
CREATE TABLE public.product_variants (
  variant_id serial PRIMARY KEY,
  product_id integer NOT NULL,
  sku varchar(64),
  size varchar(50),
  color varchar(100),
  price numeric(10,2) NOT NULL DEFAULT 0.00 CHECK (price >= 0),
  color_hex varchar(7),
  stock_count integer NOT NULL DEFAULT 0 CHECK (stock_count >= 0),
  is_default smallint NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  updated_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- product_images
CREATE TABLE public.product_images (
  image_id serial PRIMARY KEY,
  product_id integer NOT NULL,
  variant_id integer,
  path varchar(255) NOT NULL,
  alt_text varchar(255),
  position integer NOT NULL DEFAULT 0,
  is_primary smallint NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- product_reviews
CREATE TABLE public.product_reviews (
  review_id serial PRIMARY KEY,
  product_id integer NOT NULL,
  customer_id integer,
  order_id integer,
  rating smallint NOT NULL CHECK (rating >= 1 AND rating <= 5),
  title varchar(255),
  body text,
  is_verified_purchase smallint NOT NULL DEFAULT 0 CHECK (is_verified_purchase IN (0,1)),
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- tags
CREATE TABLE public.tags (
  tag_id serial PRIMARY KEY,
  name varchar(100) NOT NULL
);

-- product_tags (many-to-many)
CREATE TABLE public.product_tags (
  product_id integer NOT NULL,
  tag_id integer NOT NULL,
  PRIMARY KEY (product_id, tag_id)
);

-- addresses
CREATE TABLE public.addresses (
  address_id serial PRIMARY KEY,
  customer_id integer,
  name varchar(150),
  phone varchar(20),
  line1 varchar(255) NOT NULL,
  line2 varchar(255),
  city varchar(100) NOT NULL,
  state varchar(100) NOT NULL,
  postal_code varchar(20) NOT NULL,
  country varchar(100) NOT NULL DEFAULT 'India',
  is_default smallint NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  updated_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- orders
CREATE TABLE public.orders (
  order_id serial PRIMARY KEY,
  customer_id integer,
  order_date timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  total_amount numeric(10,2) NOT NULL DEFAULT 0.00 CHECK (total_amount >= 0),
  currency varchar(10) NOT NULL DEFAULT 'INR',
  payment_status varchar(50) NOT NULL DEFAULT 'pending',
  payment_gateway varchar(50),
  shipping_address_id integer,
  shipping_cost numeric(10,2) NOT NULL DEFAULT 0.00 CHECK (shipping_cost >= 0),
  status varchar(50) NOT NULL DEFAULT 'waiting to be accepted',
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  updated_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  last_payment_id integer
);

-- payments
CREATE TABLE public.payments (
  id serial PRIMARY KEY,
  order_id integer NOT NULL,
  gateway_payment_id varchar(255),
  gateway_signature varchar(255),
  amount numeric(10,2) NOT NULL CHECK (amount >= 0),
  currency varchar(10) NOT NULL DEFAULT 'INR',
  status varchar(50) NOT NULL,
  method varchar(50),
  raw_response json,
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  updated_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  invoice_path varchar(255)
);

-- order_items
CREATE TABLE public.order_items (
  order_item_id serial PRIMARY KEY,
  order_id integer NOT NULL,
  product_id integer,
  variant_id integer,
  quantity integer NOT NULL DEFAULT 1 CHECK (quantity > 0),
  unit_price numeric(10,2) NOT NULL CHECK (unit_price >= 0),
  total_price numeric(12,2) GENERATED ALWAYS AS (unit_price * quantity) STORED
);

-- registration_otps
CREATE TABLE public.registration_otps (
  id serial PRIMARY KEY,
  email varchar(100) NOT NULL,
  name varchar(100) NOT NULL,
  password_hash varchar(255) NOT NULL,
  otp_salt varchar(64) NOT NULL,
  otp_hmac varchar(128) NOT NULL,
  attempts_left smallint NOT NULL DEFAULT 5 CHECK (attempts_left >= 0),
  expires_at timestamp NOT NULL,
  created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- contact_messages
CREATE TABLE IF NOT EXISTS contact_messages (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone VARCHAR(32),
    subject VARCHAR(120),
    message TEXT NOT NULL,
    consent BOOLEAN NOT NULL DEFAULT FALSE,
    source VARCHAR(80),
    ip INET,
    user_agent TEXT,
    referer TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    created_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
    processed_at timestamp NULL
);


-- Roles table
CREATE TABLE IF NOT EXISTS roles (
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  dept VARCHAR(120),
  location VARCHAR(120),
  type VARCHAR(60),
  salary NUMERIC(12,2),
  summary TEXT,
  description TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- Applications table
CREATE TABLE IF NOT EXISTS applications (
  id SERIAL PRIMARY KEY,
  role_id INTEGER REFERENCES roles(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  phone VARCHAR(40),
  location VARCHAR(120),
  message TEXT,
  resume_key TEXT,          -- store the R2 key/path (NOT the public URL)
  ip_address INET,
  user_agent TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

CREATE TABLE IF NOT EXISTS public.bestsellers (
  variant_id    bigint      NOT NULL PRIMARY KEY,
  product_id    bigint      NOT NULL,
  title         text        NOT NULL,
  category      text,
  rating_avg    numeric(4,2) DEFAULT 0.00,
  reviews_count integer     DEFAULT 0,
  price         numeric(12,2) DEFAULT 0.00,
  size          text,
  color         text,
  variant_sku   text,
  image    text,
  refreshed_at  timestamptz DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- 1) Store Sales Executive
INSERT INTO roles (title, dept, location, type, salary, summary, description, is_active, created_at)
SELECT
  'Store Sales Executive',
  'Retail',
  'Purnia',
  'Full-time',
  12000.00,
  'Customer-facing sales role: assist shoppers with fabric selection, measure yardage, operate POS and ensure a friendly store experience.',
  E'Role overview:\nA Store Sales Executive is the primary face of the shop for walk-in customers. You will greet customers, understand their needs, recommend fabrics and yardage, explain weave and care characteristics, and complete sales via the POS. You will also keep displays tidy, help with simple packaging and ensure customer follow-up where required.\n\nKey responsibilities:\n- Greet customers and provide friendly, knowledgeable support about fabrics, sari types, suiting, linens, and yardage.\n- Take accurate measurements and cut/prepare yardage per customer requirements (or hand off to the cutter where applicable).\n- Operate point-of-sale (cash / card), issue paper receipts, and handle small daily reconciliation tasks.\n- Maintain attractive merchandise displays, label stock and rotate seasonal items.\n- Track popular items and report low stock to management; assist with simple stock counts.\n- Answer basic product queries by phone or in-person and escalate complex queries to the manager.\n\nSkills & requirements:\n- Minimum: secondary education. 1+ year retail/fabric sales experience preferred.\n- Good conversational skills in local language; basic Hindi/English useful for messages and online orders.\n- Numeracy and comfort with handling cash and small accounting tasks.\n- Honest, punctual, presentable and able to stand for store shifts.\n- Willingness to learn fabric names, weaving terms and care instructions.\n\nWork conditions & benefits:\n- Full-time, retail hours (incl. occasional weekends). Employee discount on store fabric. On-the-job training provided.',
  TRUE,
  (now() AT TIME ZONE 'Asia/Kolkata')
WHERE NOT EXISTS (
  SELECT 1 FROM roles WHERE title = 'Store Sales Executive' AND location = 'Purnia'
);

-- 2) Operations Assistant
INSERT INTO roles (title, dept, location, type, salary, summary, description, is_active, created_at)
SELECT
  'Operations Assistant',
  'Operations',
  'Purnia',
  'Full-time',
  10000.00,
  'Support operational flow: deliveries, inventory, dispatch coordination and vendor follow-ups for the shop.',
  E'Role overview:\nThe Operations Assistant keeps the shop running smoothly behind the scenes. You will be responsible for receiving shipments, checking incoming goods against invoices, organising storage, arranging local deliveries, and coordinating with suppliers and couriers.\n\nKey responsibilities:\n- Receive and inspect incoming fabric consignments; verify quantities and note any damages.\n- Update inventory records (simple stock ledger / spreadsheet) and notify manager of replenishment needs.\n- Coordinate local dispatches and deliveries (packaging, labeling, creating dispatch notes) and liaise with delivery personnel.\n- Maintain purchase invoices, petty bills and assist with vendor communications and follow-ups.\n- Help prepare daily/weekly stock reports and support end-of-day reconciliation when required.\n- Keep stockroom organized and ensure safety (stacking, storing rolls properly).\n\nSkills & requirements:\n- Minimum: basic literacy and numeracy. Retail operations or warehouse experience preferred.\n- Comfortable using simple computer tools (Excel / Google Sheets) or willing to learn.\n- Good organisational skills, attention to detail and ability to lift moderate weight (fabric rolls).\n- Reliable, timely and able to work with suppliers and delivery services.\n\nWork conditions & benefits:\n- Full-time, primarily on-site in Purnia. Close coordination with shop manager. Employee discount and small travel reimbursements where appropriate.',
  TRUE,
  (now() AT TIME ZONE 'Asia/Kolkata')
WHERE NOT EXISTS (
  SELECT 1 FROM roles WHERE title = 'Operations Assistant' AND location = 'Purnia'
);

-- Corrected INSERT using dollar-quoting so embedded quotes/newlines don't break the statement
INSERT INTO roles (title, dept, location, type, salary, summary, description, is_active, created_at)
SELECT
  'E-commerce Coordinator',
  'Digital',
  'Remote / Hybrid',
  'Part-time',
  9000.00,
  $$Part-time role to manage online listings, order support and local fulfilment coordination for the shop's web and marketplace presence.$$,
  $$Role overview:
This role helps the shop maintain an online presence and process digital orders. The E-commerce Coordinator will create product listings, keep stock levels synced, respond to customer messages for online orders and coordinate with the store for packing and dispatch.

Key responsibilities:
- Create clear product listings with accurate descriptions, measurements and simple images provided by the store; maintain consistent naming and categories.
- Update stock data and mark items as available/unavailable in the online store or marketplaces.
- Process incoming online orders, collect order details and coordinate with the store for packing and dispatch.
- Respond to customer queries (order status, product details) via email/WhatsApp/marketplace messages with a fast, courteous tone.
- Assist with simple content tasks: short product copy, tagging, and occasionally scheduling social posts.

Skills & requirements:
- Comfortable using a CMS or marketplace dashboards (basic experience with Shopify, WooCommerce, or common marketplace interfaces is a plus).
- Basic photography sense (ability to crop/resize images) or coordinate with an on-site helper for photos.
- Good written communication; ability to work independently and manage part-time hours.
- Reliable internet connection (if remote) and willingness to occasionally visit the store for coordination.

Work conditions & benefits:
- Part-time/hybrid. Remote work is possible for certain tasks; occasional on-site coordination required. Training provided for shop systems.$$,
  TRUE,
  (now() AT TIME ZONE 'Asia/Kolkata')
WHERE NOT EXISTS (
  SELECT 1 FROM roles WHERE title = 'E-commerce Coordinator' AND location = 'Remote / Hybrid'
);


-- 4) Store Manager
INSERT INTO roles (title, dept, location, type, salary, summary, description, is_active, created_at)
SELECT
  'Store Manager',
  'Retail',
  'Purnia',
  'Full-time',
  25000.00,
  'Lead store operations: supervise staff, manage inventory & procurement, ensure customer satisfaction and financial reconciliation.',
  E'Role overview:\nThe Store Manager is responsible for overall store performance, people management and customer experience. You will lead daily operations, manage staff schedules, maintain stock levels and be the primary decision-maker in the store.\n\nKey responsibilities:\n- Supervise and coach sales team; schedule rotas and ensure adequate coverage for peak hours.\n- Maintain inventory accuracy: approve purchase orders, manage vendor relationships and ensure timely restocking.\n- Oversee cash handling, POS reconciliation, and daily sales reporting; liaise with accounting/bookkeeping as required.\n- Ensure high standards of customer service, handle escalations and build strong local customer relationships.\n- Plan simple in-store promotions, merchandising and seasonal displays to boost sales.\n- Enforce store policies, safety and loss-prevention measures.\n\nSkills & requirements:\n- Proven retail experience (3+ years) with at least 1 year in a supervisory role preferred.\n- Strong people skills: coaching, conflict resolution and a customer-first mindset.\n- Comfortable with basic accounting and reconciliations; good numeracy and record-keeping.\n- Local market knowledge and ability to work flexible hours including weekends.\n\nWork conditions & benefits:\n- Full-time. Competitive salary for local market, plus performance discussions and staff discount. Leadership opportunity in a family-run traditional shop.',
  TRUE,
  (now() AT TIME ZONE 'Asia/Kolkata')
WHERE NOT EXISTS (
  SELECT 1 FROM roles WHERE title = 'Store Manager' AND location = 'Purnia'
);


-- === NOW add constraints & indexes (idempotent) ===

-- unique/indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name ON public.tags (name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_sku_idx ON public.products (sku);

-- foreign keys / constraints (apply after tables created) - add only if not exists

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_variant_product') THEN
    ALTER TABLE public.product_variants
      ADD CONSTRAINT fk_variant_product FOREIGN KEY (product_id)
        REFERENCES public.products (product_id) ON DELETE CASCADE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_image_product') THEN
    ALTER TABLE public.product_images
      ADD CONSTRAINT fk_image_product FOREIGN KEY (product_id)
        REFERENCES public.products (product_id) ON DELETE CASCADE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_image_variant') THEN
    ALTER TABLE public.product_images
      ADD CONSTRAINT fk_image_variant FOREIGN KEY (variant_id)
        REFERENCES public.product_variants (variant_id) ON DELETE CASCADE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_review_product') THEN
    ALTER TABLE public.product_reviews
      ADD CONSTRAINT fk_review_product FOREIGN KEY (product_id)
        REFERENCES public.products (product_id) ON DELETE CASCADE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_review_customer') THEN
    ALTER TABLE public.product_reviews
      ADD CONSTRAINT fk_review_customer FOREIGN KEY (customer_id)
        REFERENCES public.customers (customer_id) ON DELETE SET NULL;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_pt_product') THEN
    ALTER TABLE public.product_tags
      ADD CONSTRAINT fk_pt_product FOREIGN KEY (product_id)
        REFERENCES public.products (product_id) ON DELETE CASCADE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_pt_tag') THEN
    ALTER TABLE public.product_tags
      ADD CONSTRAINT fk_pt_tag FOREIGN KEY (tag_id)
        REFERENCES public.tags (tag_id) ON DELETE CASCADE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_address_customer') THEN
    ALTER TABLE public.addresses
      ADD CONSTRAINT fk_address_customer FOREIGN KEY (customer_id)
        REFERENCES public.customers (customer_id) ON DELETE CASCADE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_order_customer') THEN
    ALTER TABLE public.orders
      ADD CONSTRAINT fk_order_customer FOREIGN KEY (customer_id)
        REFERENCES public.customers (customer_id) ON DELETE SET NULL;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_order_shipping_address') THEN
    ALTER TABLE public.orders
      ADD CONSTRAINT fk_order_shipping_address FOREIGN KEY (shipping_address_id)
        REFERENCES public.addresses (address_id) ON DELETE SET NULL;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_payment_order') THEN
    ALTER TABLE public.payments
      ADD CONSTRAINT fk_payment_order FOREIGN KEY (order_id)
        REFERENCES public.orders (order_id) ON DELETE RESTRICT;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_item_order') THEN
    ALTER TABLE public.order_items
      ADD CONSTRAINT fk_item_order FOREIGN KEY (order_id)
        REFERENCES public.orders (order_id) ON DELETE CASCADE;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_item_product') THEN
    ALTER TABLE public.order_items
      ADD CONSTRAINT fk_item_product FOREIGN KEY (product_id)
        REFERENCES public.products (product_id) ON DELETE SET NULL;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_item_variant') THEN
    ALTER TABLE public.order_items
      ADD CONSTRAINT fk_item_variant FOREIGN KEY (variant_id)
        REFERENCES public.product_variants (variant_id) ON DELETE SET NULL;
  END IF;
END
$$;

-- 2025-09-15_create_wishlist_table.sql
CREATE TABLE public.wishlist (
  wishlist_id   serial PRIMARY KEY,
  customer_id   integer NOT NULL,
  product_id    integer NOT NULL,
  variant_id    integer NOT NULL,
  created_at    timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata'),
  CONSTRAINT fk_wishlist_customer FOREIGN KEY (customer_id) REFERENCES public.customers (customer_id) ON DELETE CASCADE,
  CONSTRAINT fk_wishlist_product FOREIGN KEY (product_id) REFERENCES public.products (product_id) ON DELETE CASCADE,
  CONSTRAINT fk_wishlist_variant FOREIGN KEY (variant_id) REFERENCES public.product_variants (variant_id) ON DELETE CASCADE,
  CONSTRAINT uq_wishlist_customer_variant UNIQUE (customer_id, variant_id)
);


DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_bestsellers_variant'
  ) THEN
    ALTER TABLE public.bestsellers
      ADD CONSTRAINT fk_bestsellers_variant
      FOREIGN KEY (variant_id)
      REFERENCES public.product_variants (variant_id)
      ON DELETE CASCADE;
  END IF;
END
$$;

-- 2) Foreign key: product_id -> products.product_id
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_bestsellers_product'
  ) THEN
    ALTER TABLE public.bestsellers
      ADD CONSTRAINT fk_bestsellers_product
      FOREIGN KEY (product_id)
      REFERENCES public.products (product_id)
      ON DELETE CASCADE;
  END IF;
END
$$;

-- 3) Add check constraint: rating_avg between 0 and 5
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_bestsellers_rating_range'
  ) THEN
    ALTER TABLE public.bestsellers
      ADD CONSTRAINT ck_bestsellers_rating_range
      CHECK (rating_avg >= 0 AND rating_avg <= 5);
  END IF;
END
$$;

-- 4) Add check constraint: reviews_count non-negative integer
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_bestsellers_reviews_nonneg'
  ) THEN
    ALTER TABLE public.bestsellers
      ADD CONSTRAINT ck_bestsellers_reviews_nonneg
      CHECK (reviews_count >= 0);
  END IF;
END
$$;

-- 5) Add check constraint: price non-negative
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'ck_bestsellers_price_nonneg'
  ) THEN
    ALTER TABLE public.bestsellers
      ADD CONSTRAINT ck_bestsellers_price_nonneg
      CHECK (price >= 0);
  END IF;
END
$$;

-- Index to look up a customer's wishlist quickly
CREATE INDEX idx_wishlist_customer_created ON public.wishlist (customer_id, created_at DESC);

-- Index to support queries by variant
CREATE INDEX idx_wishlist_variant ON public.wishlist (variant_id);
-- Indexes for contact_messages
CREATE INDEX IF NOT EXISTS idx_contact_messages_email ON contact_messages (LOWER(email));
-- Index to support queries by created_at
CREATE INDEX IF NOT EXISTS idx_contact_messages_created_at ON contact_messages (created_at);

CREATE INDEX IF NOT EXISTS idx_applications_role_id ON applications(role_id);
CREATE INDEX IF NOT EXISTS idx_roles_is_active ON roles(is_active);

CREATE INDEX IF NOT EXISTS idx_best_sellers_price ON public.bestsellers (price);
CREATE INDEX IF NOT EXISTS idx_bestsellers_product_id ON public.bestsellers (product_id);
CREATE INDEX IF NOT EXISTS idx_bestsellers_refreshed_at ON public.bestsellers (refreshed_at DESC);
CREATE INDEX IF NOT EXISTS idx_bestsellers_rating ON public.bestsellers (rating_avg DESC);


"""
# ---------- end of DDL ----------

# choose env or hardcoded DB URL (env recommended)
db_from_env = True

def get_database_url():
    if db_from_env:
        db = "postgresql://postgres.pxiezxcknjmkgnpgugmk:XJNAcJvtdoOz5JCo@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"
    else:
        db = None

    # fallback hardcoded (only used if env missing)
    if not db:
        db = "postgresql://postgres.pxiezxcknjmkgnpgugmk:XJNAcJvtdoOz5JCo@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"

    if db.startswith("postgres://"):
        db = db.replace("postgres://", "postgresql://", 1)
    return db

def mask_db_url(db_url: str) -> str:
    try:
        p = urlparse(db_url)
        user = p.username or ""
        host = p.hostname or ""
        port = p.port or ""
        path = p.path or ""
        port_str = f":{port}" if port else ""
        return f"{p.scheme}://{user}:<REDACTED>@{host}{port_str}{path}"
    except Exception:
        return "<unable to mask DATABASE_URL>"

def extract_statements(sql_text):
    """
    Robust statement extractor:
     - scans the text character-by-character
     - keeps track of single-quote, double-quote, line comments (--), block comments (/* */)
       and dollar-quoted strings ($tag$ ... $tag$)
     - returns a list of statements each ending with a semicolon (including the semicolon)
    """
    stmts = []
    buf = []
    i = 0
    n = len(sql_text)

    in_squote = False
    in_dquote = False
    in_line_comment = False
    in_block_comment = False
    in_dollar = False
    dollar_tag = None

    while i < n:
        ch = sql_text[i]
        next_ch = sql_text[i+1] if i+1 < n else ''

        # handle line comment start
        if not (in_squote or in_dquote or in_block_comment or in_dollar) and ch == '-' and next_ch == '-':
            in_line_comment = True
            buf.append(ch)
            i += 1
            buf.append(next_ch)
            i += 1
            continue

        # handle block comment start
        if not (in_squote or in_dquote or in_line_comment or in_dollar) and ch == '/' and next_ch == '*':
            in_block_comment = True
            buf.append(ch)
            i += 1
            buf.append(next_ch)
            i += 1
            continue

        # handle end of line comment
        if in_line_comment:
            buf.append(ch)
            i += 1
            if ch == '\n':
                in_line_comment = False
            continue

        # handle end of block comment
        if in_block_comment:
            buf.append(ch)
            i += 1
            if ch == '*' and next_ch == '/':
                buf.append(next_ch)
                i += 1
                in_block_comment = False
            continue

        # handle dollar-quote start/end
        if not (in_squote or in_dquote or in_line_comment or in_block_comment):
            # attempt to match $tag$
            if not in_dollar and ch == '$':
                m = re.match(r'\$[A-Za-z0-9_]*\$', sql_text[i:])
                if m:
                    tag = m.group(0)  # e.g. $$ or $tag$
                    in_dollar = True
                    dollar_tag = tag
                    # append the tag
                    buf.append(tag)
                    i += len(tag)
                    continue
            elif in_dollar:
                # check if closing tag matches
                if sql_text.startswith(dollar_tag, i):
                    buf.append(dollar_tag)
                    i += len(dollar_tag)
                    in_dollar = False
                    dollar_tag = None
                    continue
                else:
                    # inside dollar quoted body
                    buf.append(ch)
                    i += 1
                    continue

        # handle single quotes (SQL doubles '' to escape)
        if not (in_dquote or in_line_comment or in_block_comment or in_dollar) and ch == "'":
            buf.append(ch)
            i += 1
            if in_squote:
                # if next char is another single quote it's an escape: consume both and stay inside
                if i < n and sql_text[i] == "'":
                    buf.append(sql_text[i])
                    i += 1
                    # remain in_squote
                else:
                    in_squote = False
            else:
                in_squote = True
            continue

        if in_squote:
            # copy until closing handled above
            buf.append(ch)
            i += 1
            continue

        # handle double quotes (identifiers)
        if not (in_squote or in_line_comment or in_block_comment or in_dollar) and ch == '"':
            buf.append(ch)
            i += 1
            if in_dquote:
                # if next char is another double quote, it's an escape
                if i < n and sql_text[i] == '"':
                    buf.append(sql_text[i])
                    i += 1
                    # remain in_dquote
                else:
                    in_dquote = False
            else:
                in_dquote = True
            continue

        if in_dquote:
            buf.append(ch)
            i += 1
            continue

        # Normal flow: if we hit a semicolon outside quotes/comments/dollar, that's end of statement
        if ch == ';' and not (in_squote or in_dquote or in_line_comment or in_block_comment or in_dollar):
            buf.append(ch)
            statement = ''.join(buf).strip()
            if statement:
                stmts.append(statement)
            buf = []
            i += 1
            # skip any whitespace/newlines after semicolon (they'll be handled next loop)
            while i < n and sql_text[i].isspace():
                i += 1
            continue

        # Default: copy character
        buf.append(ch)
        i += 1

    # any trailing buffer (without semicolon) - include if non-empty
    trailing = ''.join(buf).strip()
    if trailing:
        stmts.append(trailing)
    return stmts

def strip_leading_comments(stmt):
    """
    Remove leading SQL comment lines (lines starting with --) and leading whitespace,
    leaving the actual SQL command at the start for classification.
    """
    return re.sub(r'^(?:\s*--[^\n]*\n)+', '', stmt, flags=re.IGNORECASE)

def categorize(statements):
    drops = []
    tables = []
    others = []
    for s in statements:
        ss = strip_leading_comments(s).lstrip().upper()
        if not ss:
            continue
        if ss.startswith('DROP TABLE') or ss.startswith('DROP INDEX'):
            drops.append(s)
        elif ss.startswith('CREATE TABLE'):
            tables.append(s)
        else:
            others.append(s)
    return drops, tables, others

def exec_statements(cursor, stmts, description):
    executed = 0
    total = len(stmts)
    if total == 0:
        print(f"No statements to run for: {description}")
        return executed
    print(f"Executing {total} statements for: {description}")
    for i, stmt in enumerate(stmts, start=1):
        try:
            cursor.execute(stmt)
            executed += 1
            print(f"[{i}/{total}] OK")
        except Exception as e:
            print(f"[{i}/{total}] ERROR executing statement (preview): {stmt[:400]!r} ...")
            print("Full statement follows:\n", stmt)
            print("Exception:", e)
            raise
    return executed

def preview_list(lst, name, n=2):
    print(f"Detected {len(lst)} {name}. Showing up to {n} previews:")
    for i, s in enumerate(lst[:n], start=1):
        preview = s.replace('\n', ' ')[:200]
        print(f"  ({i}) {preview}...")

def main():
    db_url = "postgresql://postgres.pxiezxcknjmkgnpgugmk:XJNAcJvtdoOz5JCo@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"
    print("Using DATABASE_URL:", mask_db_url(db_url))

    statements = extract_statements(DDL)
    drops, tables, others = categorize(statements)

    preview_list(drops, "DROP statements")
    preview_list(tables, "CREATE TABLE statements")
    preview_list(others, "OTHER statements (indexes/constraints)")

    conn = None
    try:
        conn = psycopg2.connect(db_url, connect_timeout=10)
        conn.autocommit = False
        cur = conn.cursor()

        # PASS 0: drops
        try:
            exec_statements(cur, drops, "DROP existing objects (if any)")
            conn.commit()
            print("PASS 0 complete: Drops committed.")
        except Exception:
            conn.rollback()
            print("PASS 0 failed; rolled back. Aborting.")
            sys.exit(2)

        # PASS 1: create tables
        try:
            if not tables:
                print("ERROR: No CREATE TABLE statements were found. Aborting before indexes.")
                sys.exit(3)
            exec_statements(cur, tables, "CREATE TABLE")
            conn.commit()
            print("PASS 1 complete: Table creation committed.")
        except Exception:
            conn.rollback()
            print("PASS 1 failed; rolled back. Aborting.")
            sys.exit(4)

        # PASS 2: indexes & constraints
        try:
            exec_statements(cur, others, "indexes & constraints")
            conn.commit()
            print("PASS 2 complete: Indexes & constraints committed.")
            print("SUCCESS: All DDL executed.")
        except Exception:
            conn.rollback()
            print("PASS 2 failed; rolled back. Aborting.")
            sys.exit(5)

    except Exception as e:
        print("FAILED to apply schema. Exception:", repr(e))
        sys.exit(6)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
