# db/db_config.py

import mysql.connector
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_db():
    try:
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', 'password'),
            database=os.getenv('DB_NAME', 'CS_db')
        )
        print("Database connected successfully")
        return connection
    except mysql.connector.Error as err:
        print(f"Database connection failed: {err}")
        raise
