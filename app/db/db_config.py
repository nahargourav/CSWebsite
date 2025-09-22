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