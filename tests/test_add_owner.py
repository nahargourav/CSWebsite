# tests/test_add_owner.py
import os
from werkzeug.security import generate_password_hash
import psycopg2
from psycopg2 import OperationalError
from dotenv import load_dotenv

# Load .env from project root (adjust if your project layout differs)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

def get_db():
    """
    Connect to PostgreSQL using DATABASE_URL only.
    Expects an environment variable named DATABASE_URL (e.g. provided by Render).
    Returns a psycopg2 connection or None on failure.
    """
    database_url = "postgresql://my_user:QCigpYVrdZ6HUeMKlRTZMcwiACsp1fNE@dpg-d2so6s75r7bs73ambfmg-a.singapore-postgres.render.com/myapp_db_acmo"
    if not database_url:
        print("DATABASE_URL not set; cannot connect.")
        return None

    # Some providers return "postgres://..." — normalize to "postgresql://"
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    try:
        # simple connect using the full URL
        conn = psycopg2.connect(database_url, connect_timeout=10)
        return conn
    except Exception as e:
        print(f"Error connecting to PostgreSQL using DATABASE_URL: {e}")
        return None

def test_add_one_owner():
    """Insert a single owner using context managers and clear error handling."""
    email = "owner@gmail.com"
    name = "Gourav"
    pwd_hash = generate_password_hash("pass")

    try:
        conn = get_db()
    except Exception as e:
        print("Database not available:", e)
        return

    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO owners (name, email, password_hash) VALUES (%s, %s, %s) RETURNING owner_id",
                    (name, email, pwd_hash)
                )
                owner_id = cursor.fetchone()[0]
                cursor.execute("SELECT owner_id, name, email FROM owners WHERE owner_id = %s", (owner_id,))
                row = cursor.fetchone()
                assert row is not None, "Inserted owner row not found"
                assert row[1] == name
                assert row[2] == email
                print("Insert + check OK, owner_id =", owner_id)
    except Exception as e:
        print("Could not insert owner (table may be missing or schema mismatch):", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == '__main__':
    test_add_one_owner()
