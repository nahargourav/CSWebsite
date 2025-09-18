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
    # --- Local DB connection settings ---------------------------------
    # Use a local PostgreSQL instance for development.
    # Credentials: database=myapp_db, user=postgres, password=password
    # Adjust HOST/PORT if your local DB uses a different socket/port.
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=int(os.environ.get('DB_PORT', 5432)),
            database=os.environ.get('DB_NAME', 'myapp_db'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'password'),
            connect_timeout=10
        )
        return conn
    except Exception as e:
        print(f"Error connecting to local PostgreSQL: {e}")
        # Fallback (commented out): original DATABASE_URL logic kept for reference
        # database_url = os.environ.get('DATABASE_URL') or "postgresql://..."
        # if database_url and database_url.startswith("postgres://"):
        #     database_url = database_url.replace("postgres://", "postgresql://", 1)
        # try:
        #     conn = psycopg2.connect(database_url, connect_timeout=10)
        #     return conn
        # except Exception as e2:
        #     print(f"Error connecting using DATABASE_URL fallback: {e2}")
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
