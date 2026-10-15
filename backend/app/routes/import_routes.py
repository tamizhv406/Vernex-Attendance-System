import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.import_service import PERSON_SPECS, SPECS, ImportSpec, run_import, summary_message, template_file
from app.utils.errors import safe_error_text, where_it_happened
from app.utils.spreadsheet import MAX_FILE_BYTES, ImportFileError, read_sheet

router = APIRouter(tags=["Bulk Import"])
log = logging.getLogger(__name__)

# Said instead of the database's own words, which name tables, statements and the values in them.
IMPORT_FAILED = "The import could not be completed because of a problem on the server. Check the list, then upload the file again: rows that were already saved are reported as existing."


def person_spec(person_type: str | None) -> ImportSpec:
    wanted = (person_type or "").strip().lower()
    spec = PERSON_SPECS.get("admin" if wanted == "staff" else wanted)
    if not spec:
        raise HTTPException(400, "person_type must be student, admin or member")
    return spec


def import_upload(spec: ImportSpec, file: UploadFile | None, db: Session):
    if file is None:
        raise HTTPException(400, "Attach a .xlsx or .csv file in the form field \"file\".")
    try:
        # One byte past the limit is enough to know the file is too large without reading all of it.
        sheet = read_sheet(file.filename or "", file.file.read(MAX_FILE_BYTES + 1))
        # Saved in one transaction with its row in the audit log: both, or neither.
        result = run_import(db, spec, sheet)
    except ImportFileError as error:
        db.rollback()
        raise HTTPException(error.status, str(error))
    except Exception as error:
        db.rollback()
        # What kind of error and where, as the general error handler logs it. Not the driver's whole
        # message (PostgreSQL's DETAIL line quotes the row) and not the traceback's text, which can
        # hold the names and numbers of the rows being saved.
        log.error("Bulk import of %s failed: %s | at %s", spec.key, safe_error_text(error), where_it_happened(error))
        raise HTTPException(500, IMPORT_FAILED)
    return {"success": True, "message": summary_message(result), "data": result}


def template_download(spec: ImportSpec, file_format: str):
    try:
        content, media_type, filename = template_file(spec, file_format.strip().lower())
    except ImportFileError as error:
        raise HTTPException(error.status, str(error))
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@router.post("/courses/upload")
def upload_courses(file: UploadFile | None = File(None), db: Session = Depends(get_db)):
    return import_upload(SPECS["courses"], file, db)


@router.get("/courses/upload/template")
def courses_template(file_format: str = Query("xlsx", alias="format")):
    return template_download(SPECS["courses"], file_format)


@router.post("/batches/upload")
def upload_batches(file: UploadFile | None = File(None), db: Session = Depends(get_db)):
    return import_upload(SPECS["batches"], file, db)


@router.get("/batches/upload/template")
def batches_template(file_format: str = Query("xlsx", alias="format")):
    return template_download(SPECS["batches"], file_format)


@router.post("/users/upload")
def upload_people(person_type: str | None = None, file: UploadFile | None = File(None), db: Session = Depends(get_db)):
    return import_upload(person_spec(person_type), file, db)


@router.get("/users/upload/template")
def people_template(person_type: str | None = None, file_format: str = Query("xlsx", alias="format")):
    return template_download(person_spec(person_type), file_format)
