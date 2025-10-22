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
  short_description varchar(255),
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

-- Index to look up a customer's wishlist quickly
CREATE INDEX idx_wishlist_customer_created ON public.wishlist (customer_id, created_at DESC);

-- Index to support queries by variant
CREATE INDEX idx_wishlist_variant ON public.wishlist (variant_id);



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
