import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from app.database import engine

def main():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Supabase PostgreSQL connection successful")
    except Exception as e:
        print("Supabase PostgreSQL connection failed:")
        print(e)

if __name__ == "__main__":
    main()
