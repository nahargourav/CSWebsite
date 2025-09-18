# app/db/db_config.py
import os
import psycopg2
from dotenv import load_dotenv

# Load .env from project root (optional for local dev)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dotenv_path = os.path.join(BASE_DIR, ".env")
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
