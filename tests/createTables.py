#!/usr/bin/env python3
"""
tests/createTables.py

Robust DDL applier (fixed):
  - Extracts statements via regex (keeps multiline statements intact)
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
-- ========== DROP PREVIOUS STRUCTURES (safe) ==========
-- Drop tables (CASCADE will remove dependent objects like indexes/constraints)
DROP TABLE IF EXISTS
  public.product_tags,
  public.product_images,
  public.product_reviews,
  public.order_items,
  public.product_variants,
  public.products,
  public.tags,
  public.payments,
  public.orders,
  public.addresses,
  public.registration_otps,
  public.customers,
  public.owners
CASCADE;

-- If you had standalone indexes (uncommon when table is dropped) you can drop them explicitly:
DROP INDEX IF EXISTS idx_customers_email;
DROP INDEX IF EXISTS idx_products_category;
DROP INDEX IF EXISTS idx_products_name;
DROP INDEX IF EXISTS uq_products_sku;
DROP INDEX IF EXISTS uk_product_variant_sku;
DROP INDEX IF EXISTS idx_prodimg_position;
DROP INDEX IF EXISTS idx_reviews_customer;
DROP INDEX IF EXISTS idx_reviews_order;
DROP INDEX IF EXISTS idx_reviews_product;
DROP INDEX IF EXISTS idx_orderitems_order;
DROP INDEX IF EXISTS idx_orderitems_product;
DROP INDEX IF EXISTS idx_orders_customer;
DROP INDEX IF EXISTS idx_orders_status;
DROP INDEX IF EXISTS idx_owners_email;
DROP INDEX IF EXISTS idx_payments_gateway;
DROP INDEX IF EXISTS idx_payments_status;
DROP INDEX IF EXISTS idx_tags_name;
DROP INDEX IF EXISTS idx_registration_otps_email;
DROP INDEX IF EXISTS ft_products_search;

-- ========== CREATE TABLES ==========
CREATE TABLE public.customers (
  customer_id serial PRIMARY KEY,
  name varchar(100) NOT NULL,
  email varchar(100) NOT NULL,
  password_hash varchar(255) NOT NULL,
  phone varchar(20),
  is_active smallint NOT NULL DEFAULT 1,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- owners
CREATE TABLE public.owners (
  owner_id serial PRIMARY KEY,
  name varchar(100) NOT NULL,
  email varchar(100) NOT NULL,
  password_hash varchar(255) NOT NULL,
  phone varchar(20),
  is_active smallint NOT NULL DEFAULT 1,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- products
CREATE TABLE public.products (
  product_id serial PRIMARY KEY,
  name varchar(200) NOT NULL,
  brand varchar(100),
  sku varchar(64),
  category varchar(150),
  short_description varchar(255),
  description text,
  image_path varchar(255),
  currency varchar(10) NOT NULL DEFAULT 'INR',
  stock_count integer NOT NULL DEFAULT 0,
  weight numeric(8,3),
  material varchar(255),
  fit varchar(50),
  care_instructions text,
  pattern varchar(50),
  occasion varchar(50),
  season varchar(50),
  sustainability varchar(255),
  rating_avg numeric(3,2) NOT NULL DEFAULT 0.00,
  reviews_count integer NOT NULL DEFAULT 0,
  is_returnable smallint NOT NULL DEFAULT 1,
  is_active smallint NOT NULL DEFAULT 1,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- product_variants
CREATE TABLE public.product_variants (
  variant_id serial PRIMARY KEY,
  product_id integer NOT NULL,
  sku varchar(64),
  size varchar(50),
  color varchar(100),
  price numeric(10,2) NOT NULL DEFAULT 0.00,
  color_hex varchar(7),
  stock_count integer NOT NULL DEFAULT 0,
  is_default smallint NOT NULL DEFAULT 0,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- product_images
CREATE TABLE public.product_images (
  image_id serial PRIMARY KEY,
  product_id integer NOT NULL,
  variant_id integer,
  path varchar(255) NOT NULL,
  alt_text varchar(255),
  position integer NOT NULL DEFAULT 0,
  is_primary smallint NOT NULL DEFAULT 0,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- product_reviews
CREATE TABLE public.product_reviews (
  review_id serial PRIMARY KEY,
  product_id integer NOT NULL,
  customer_id integer NOT NULL,
  order_id integer,
  rating smallint NOT NULL,
  title varchar(255),
  body text,
  is_verified_purchase smallint NOT NULL DEFAULT 0,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
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
  is_default smallint NOT NULL DEFAULT 0,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- orders
CREATE TABLE public.orders (
  order_id serial PRIMARY KEY,
  customer_id integer,
  order_date timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  total_amount numeric(10,2) NOT NULL DEFAULT 0.00,
  currency varchar(10) NOT NULL DEFAULT 'INR',
  payment_status varchar(50) NOT NULL DEFAULT 'pending',
  payment_gateway varchar(50),
  shipping_address_id integer,
  shipping_cost numeric(10,2) NOT NULL DEFAULT 0.00,
  status varchar(50) NOT NULL DEFAULT 'waiting to be accepted',
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_payment_id integer
);

-- payments
CREATE TABLE public.payments (
  id serial PRIMARY KEY,
  order_id integer NOT NULL,
  gateway_payment_id varchar(255),
  gateway_signature varchar(255),
  amount numeric(10,2) NOT NULL,
  currency varchar(10) NOT NULL DEFAULT 'INR',
  status varchar(50) NOT NULL,
  method varchar(50),
  raw_response json,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
  invoice_path varchar(255)
);

-- order_items
CREATE TABLE public.order_items (
  order_item_id serial PRIMARY KEY,
  order_id integer NOT NULL,
  product_id integer NOT NULL,
  variant_id integer,
  quantity integer NOT NULL DEFAULT 1,
  unit_price numeric(10,2) NOT NULL,
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
  attempts_left smallint NOT NULL DEFAULT 5,
  expires_at timestamp without time zone NOT NULL,
  created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ========== INDEXES & UNIQUE CONSTRAINTS ==========
CREATE INDEX idx_customers_email ON public.customers (email);

CREATE INDEX idx_products_category ON public.products (category);
CREATE INDEX idx_products_name ON public.products (name);
CREATE UNIQUE INDEX uq_products_sku ON public.products (sku);

CREATE UNIQUE INDEX uk_product_variant_sku ON public.product_variants (product_id, sku);

CREATE INDEX idx_prodimg_position ON public.product_images (product_id, position);

CREATE INDEX idx_reviews_customer ON public.product_reviews (customer_id);
CREATE INDEX idx_reviews_order ON public.product_reviews (order_id);
CREATE INDEX idx_reviews_product ON public.product_reviews (product_id);
ALTER TABLE public.product_reviews ADD CONSTRAINT uq_review_product_customer_order UNIQUE (product_id, customer_id, order_id);

CREATE INDEX idx_orderitems_order ON public.order_items (order_id);
CREATE INDEX idx_orderitems_product ON public.order_items (product_id);

CREATE INDEX idx_orders_customer ON public.orders (customer_id);
CREATE INDEX idx_orders_status ON public.orders (status);

CREATE INDEX idx_owners_email ON public.owners (email);

CREATE INDEX idx_payments_gateway ON public.payments (gateway_payment_id);
CREATE INDEX idx_payments_status ON public.payments (status);

CREATE INDEX idx_tags_name ON public.tags (name);

CREATE INDEX idx_registration_otps_email ON public.registration_otps (email);

CREATE INDEX ft_products_search ON public.products USING gin (
  to_tsvector('english', coalesce(name,'') || ' ' || coalesce(short_description,'') || ' ' || coalesce(description,''))
);

-- ========== FOREIGN KEYS (ON UPDATE set to CASCADE) ==========
ALTER TABLE public.addresses
  ADD CONSTRAINT fk_addresses_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE public.orders
  ADD CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE public.orders
  ADD CONSTRAINT fk_orders_shipping_address FOREIGN KEY (shipping_address_id) REFERENCES public.addresses(address_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE public.orders
  ADD CONSTRAINT fk_orders_last_payment FOREIGN KEY (last_payment_id) REFERENCES public.payments(id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE public.payments
  ADD CONSTRAINT fk_payments_order FOREIGN KEY (order_id) REFERENCES public.orders(order_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE public.order_items
  ADD CONSTRAINT fk_orderitems_order FOREIGN KEY (order_id) REFERENCES public.orders(order_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE public.order_items
  ADD CONSTRAINT fk_orderitems_product FOREIGN KEY (product_id) REFERENCES public.products(product_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE public.order_items
  ADD CONSTRAINT fk_orderitems_variant FOREIGN KEY (variant_id) REFERENCES public.product_variants(variant_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE public.product_variants
  ADD CONSTRAINT fk_variant_product FOREIGN KEY (product_id) REFERENCES public.products(product_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE public.product_images
  ADD CONSTRAINT fk_prodimg_product FOREIGN KEY (product_id) REFERENCES public.products(product_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE public.product_images
  ADD CONSTRAINT fk_prodimg_variant FOREIGN KEY (variant_id) REFERENCES public.product_variants(variant_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE public.product_reviews
  ADD CONSTRAINT fk_review_product FOREIGN KEY (product_id) REFERENCES public.products(product_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE public.product_reviews
  ADD CONSTRAINT fk_review_customer FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE public.product_reviews
  ADD CONSTRAINT fk_review_order FOREIGN KEY (order_id) REFERENCES public.orders(order_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE public.product_tags
  ADD CONSTRAINT fk_pt_product FOREIGN KEY (product_id) REFERENCES public.products(product_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE public.product_tags
  ADD CONSTRAINT fk_pt_tag FOREIGN KEY (tag_id) REFERENCES public.tags(tag_id) ON DELETE CASCADE ON UPDATE CASCADE;
"""
# ---------- end of DDL ----------

# choose env or hardcoded DB URL (env recommended)
db_from_env = True

def get_database_url():
    if db_from_env:
        db = "postgresql://my_user:QCigpYVrdZ6HUeMKlRTZMcwiACsp1fNE@dpg-d2so6s75r7bs73ambfmg-a.singapore-postgres.render.com/myapp_db_acmo"
    else:
        db = None

    # fallback hardcoded (only used if env missing)
    if not db:
        db = "postgresql://my_user:QCigpYVrdZ6HUeMKlRTZMcwiACsp1fNE@dpg-d2so6s75r7bs73ambfmg-a.singapore-postgres.render.com/myapp_db_acmo"

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
    """Use regex to extract all statements ending with a semicolon. Keeps multiline blocks intact."""
    pattern = re.compile(r'(?s)([^;]+;)\s*')
    matches = pattern.findall(sql_text)
    stmts = [m.strip() for m in matches if m.strip()]
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
    db_url = "postgresql://my_user:QCigpYVrdZ6HUeMKlRTZMcwiACsp1fNE@dpg-d2so6s75r7bs73ambfmg-a.singapore-postgres.render.com/myapp_db_acmo"
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
