import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./vernex_attendance.db")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    face_detector: str = os.getenv("FACE_DETECTOR", "yolov8n")
    face_model: str = os.getenv("FACE_MODEL", "Facenet512")
    # Pixel scaling applied before the model. Facenet2018 is what Facenet512 was trained with.
    face_normalization: str = os.getenv("FACE_NORMALIZATION", "Facenet2018")
    # How a detected face is cut out for the model. "v2" is the measured-better crop; "legacy" is the
    # original DeepFace one. Vectors from one are not matched against the other (see model_label).
    face_pipeline: str = os.getenv("FACE_PIPELINE", "v2")
    face_detection_confidence: float = float(os.getenv("FACE_DETECTION_CONFIDENCE", "0.50"))
    # Cosine similarity needed to accept a match, and how far the best person must lead the runner-up.
    face_match_threshold: float = float(os.getenv("FACE_MATCH_THRESHOLD", "0.60"))
    face_match_margin: float = float(os.getenv("FACE_MATCH_MARGIN", "0.05"))
    # "centroid": each person is matched as the average of their enrollment vectors.
    # "individual": every stored vector is compared on its own and the best one counts (the original way).
    # Best-of-five gives a stranger five chances to resemble someone: measured on LFW it names 11.2% of
    # unknown faces on a single frame where the average names 7.4%, and recognizes no more enrolled faces.
    face_gallery: str = os.getenv("FACE_GALLERY", "centroid")
    # Separate observations of one face, in a row, in which a person must be matched before attendance
    # is written, and the average score those observations must reach.
    # 0.75 comes from scripts/evaluate_recognition.py (section 5) on LFW, classes of 30: against 0.70 it
    # halves how often someone who is not in the class gets marked when the frames are nearly identical,
    # as video frames are (0.74% -> 0.37%), and members are still marked in 93-96% of attempts. 0.80
    # turns away about one member in seven, which is too many to be usable.
    face_confirm_frames: int = int(os.getenv("FACE_CONFIRM_FRAMES", "3"))
    face_confirm_score: float = float(os.getenv("FACE_CONFIRM_SCORE", "0.75"))
    # Reject photos and screens held up to the camera. The score is the model's "real face" probability.
    face_liveness: bool = os.getenv("FACE_LIVENESS", "true").lower() == "true"
    face_liveness_threshold: float = float(os.getenv("FACE_LIVENESS_THRESHOLD", "0.50"))
    # Below face_liveness_threshold a face is a photo or a screen. From there up to this score the
    # model is not sure, and an unsure face is never counted or stored. Only at or above it is a
    # face "live". These two numbers have NOT been validated on your camera: record real faces and
    # real attacks with scripts/liveness_camera_test.py and set them from its report.
    face_liveness_confident: float = float(os.getenv("FACE_LIVENESS_CONFIDENT", "0.70"))
    # "always": before attendance is written every face must also answer a head-turn instruction
    # (left or right, picked at random per student and session) on the same tracked face.
    # "off": passive liveness only. A photo held still can never answer the instruction; the
    # passive model alone passed 91% of plain image files in our check, so "off" is much weaker.
    face_challenge: str = os.getenv("FACE_CHALLENGE", "always").lower()
    # How a face is enrolled when the client does not say: "quick" captures only the poses in
    # face_enroll_quick_steps, "guided" captures all five (front, left, right, close, far).
    # The quick poses come from scripts/compare_enrollment.py: three different views (front, left,
    # right) recognize nearly as well as five photos, the same view at other sizes (close, far) adds
    # nothing, and "front" alone, the fastest, gets a class member marked in about 67% of attempts
    # where three views get 93%. Set FACE_ENROLL_QUICK_STEPS=front only if you accept that.
    face_enroll_mode: str = os.getenv("FACE_ENROLL_MODE", "quick").lower()
    face_enroll_quick_steps: list = [step.strip().lower() for step in os.getenv("FACE_ENROLL_QUICK_STEPS", "front,left,right").split(",") if step.strip()]
    # Good frames in a row a pose is taken from (the best one is kept). 1 saves the first good frame.
    face_enroll_burst_frames: int = max(1, int(os.getenv("FACE_ENROLL_BURST_FRAMES", "3")))
    # Enrollment only: reference faces are held to a stricter standard than faces seen while scanning.
    face_enroll_detection_confidence: float = float(os.getenv("FACE_ENROLL_DETECTION_CONFIDENCE", "0.60"))
    # Every pose must look at least this much like the front capture, or it is someone else's face.
    face_enroll_same_person: float = float(os.getenv("FACE_ENROLL_SAME_PERSON", "0.60"))
    # A finished enrollment whose average face looks this much like ANOTHER enrolled person's average
    # face is refused: the same face under two names is how proxy attendance gets set up.
    # Set above 1 to switch the check off (identical twins in one school, for example).
    # 0.85 from scripts/evaluate_recognition.py (section 6) on LFW: it caught 98% of faces enrolled a
    # second time and refused none of 158 different people. At 0.70 it would have refused 4% of them.
    face_enroll_duplicate_score: float = float(os.getenv("FACE_ENROLL_DUPLICATE_SCORE", "0.85"))
    # Length of one stored vector for face_model. Anything else is never saved.
    face_embedding_size: int = int(os.getenv("FACE_EMBEDDING_SIZE", "512"))
    # Write scanner decisions (who, score, runner-up, why refused) to logs/recognition.log.
    # Numbers and ids only: no camera frames and no face vectors.
    face_scan_log: bool = os.getenv("FACE_SCAN_LOG", "true").lower() == "true"
    google_script_url: str = os.getenv("GOOGLE_SCRIPT_URL", "")
    default_timezone: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")


settings = Settings()
