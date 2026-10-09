import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from app.database import Base, engine

# import all models so SQLAlchemy registers tables
from app.models.person import Person
from app.models.course import Course, CourseBatch
from app.models.timing import Timing
from app.models.face_embedding import FaceEnrollment, FaceEmbedding
from app.models.attendance import AttendanceSession, AttendanceRecord
from app.models.sync_log import SheetSyncLog

def main():
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")

if __name__ == "__main__":
    main()
