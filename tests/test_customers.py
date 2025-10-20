# tests/test_add_owner.py
import os
import json
import traceback
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql

# Load .env from project root (adjust if your project layout differs)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

# Location for output dump (created if not exists). We append snapshots.
OUTPUT_FILE = os.path.join(BASE_DIR, "db_dump.txt")

def get_db():
    """
    Connect to PostgreSQL using a DATABASE_URL-like string.
    Returns a psycopg2 connection or None on failure.
    """
    # Keep your connection string here (you can also read from env var DATABASE_URL)
    database_url = "postgresql://my_user:8SUWSufu7kwfowzU5C74vgzUmFbciJRj@dpg-d3qvu3ili9vc73cn8kk0-a.singapore-postgres.render.com/myapp_db_dcg7"

    if not database_url:
        print("DATABASE_URL not set; cannot connect.")
        return None

    # normalize old-style prefix
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    try:
        conn = psycopg2.connect(database_url, connect_timeout=10)
        return conn
    except Exception as e:
        print(f"Error connecting to PostgreSQL using DATABASE_URL: {e}")
        return None

def format_val(val):
    """Return a readable string for a DB value."""
    if val is None:
        return "NULL"
    # JSON-like objects (psycopg2 may return dict/list for json columns)
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, default=str)
        except Exception:
            return str(val)
    if isinstance(val, (bytes, bytearray)):
        # show hex for raw bytes
        try:
            return val.decode("utf-8")
        except Exception:
            return val.hex()
    # datetimes and others: fallback to str()
    return str(val)

def get_public_tables(cursor):
    """Return list of table names in schema 'public'."""
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE'
        ORDER BY table_name;
    """)
    return [r[0] for r in cursor.fetchall()]

def get_primary_key_columns(cursor, table_name):
    """
    Return list of primary key column names for table (may be empty).
    Uses pg_index/pg_attribute to retrieve PK columns.
    """
    try:
        cursor.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary;
            """,
            (table_name,)
        )
        return [r[0] for r in cursor.fetchall()]
    except Exception:
        return []

def dump_table(cursor, table_name, file_handle):
    """Fetch all rows from table_name and write a structured section to file_handle."""
    try:
        pk_cols = get_primary_key_columns(cursor, table_name)
        if pk_cols:
            order_sql = sql.SQL("ORDER BY {} ASC").format(sql.Identifier(pk_cols[0]))
        else:
            order_sql = sql.SQL("ORDER BY 1 ASC")

        q = sql.SQL("SELECT * FROM {} {}").format(sql.Identifier(table_name), order_sql)
        cursor.execute(q)
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description] if cursor.description else []

        # Header
        file_handle.write(f"TABLE: {table_name}\n")
        file_handle.write(f"Columns: {', '.join(cols) if cols else '(none)'}\n")
        file_handle.write(f"Rows: {len(rows)}\n")
        file_handle.write("-" * 80 + "\n")

        # Rows
        if rows:
            for r in rows:
                # zip columns and values, convert values safely
                pairs = []
                for col, val in zip(cols, r):
                    pairs.append(f"{col}={format_val(val)}")
                file_handle.write(" | ".join(pairs) + "\n")
        else:
            file_handle.write("(no rows)\n")

        file_handle.write("\n\n")
    except Exception as e:
        file_handle.write(f"ERROR dumping table {table_name}: {e}\n")
        file_handle.write(traceback.format_exc() + "\n\n")

def dump_all_tables():
    conn = get_db()
    if not conn:
        print("No database connection available.")
        return

    try:
        with conn:
            with conn.cursor() as cursor:
                tables = get_public_tables(cursor)
                if not tables:
                    print("No tables found in schema 'public'.")
                    return

                # Ensure output directory exists
                os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

                # Append snapshot; create file if not exists
                with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                    run_time = datetime.utcnow().isoformat() + "Z"
                    f.write("=" * 100 + "\n")
                    f.write(f"DB DUMP SNAPSHOT: {run_time}\n")
                    f.write("=" * 100 + "\n\n")

                    # iterate tables and dump
                    for t in tables:
                        print(f"Dumping table: {t}")
                        dump_table(cursor, t, f)

                    f.write("# End of snapshot\n\n\n")

                print(f"Database dump appended to {OUTPUT_FILE}")
    except Exception as e:
        print("Error during dump_all_tables:", e)
        traceback.print_exc()
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    dump_all_tables()
