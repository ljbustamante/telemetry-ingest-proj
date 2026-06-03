import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def list_tables():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT")
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE';
            """)
            tables = [row[0] for row in cur.fetchall()]
            for table in sorted(tables):
                print(table)
    finally:
        conn.close()

if __name__ == "__main__":
    list_tables()
