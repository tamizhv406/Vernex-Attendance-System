import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schema import init_database_schema

def main():
    # Creates what is missing and runs the repair statements of app/schema.py, also on PostgreSQL,
    # where the backend itself only checks the schema when it starts. Needs an account that owns the tables.
    init_database_schema(upgrade=True)
    print("Database schema is ready")

if __name__ == "__main__":
    main()
