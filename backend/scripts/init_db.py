import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schema import init_database_schema

def main():
    init_database_schema()
    print("Database schema is ready")

if __name__ == "__main__":
    main()
