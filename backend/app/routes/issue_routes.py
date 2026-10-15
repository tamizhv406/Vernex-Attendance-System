"""Reporting a problem and following it (IR-02): for anyone who is logged in, admin or super admin.

Every route answers about the caller's own issues only. Someone else's issue is "not found", the same
answer as an issue that does not exist, so its number tells nothing. A super admin reads and manages
every issue in the portal (app/routes/super_admin_routes.py). app/main.py includes this router behind
require_admin; every handler also names the actor itself.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.paging import PageNumber, PageSize
from app.schemas.issue_schema import LARGEST_ID, CommentCreate, IssueCreate
from app.security import require_admin
from app.serializers import issue_comment_data, issue_data, issue_row_data
from app.services import issue_service
from app.services.auth_service import Actor
from app.services.issue_service import IssueError

router = APIRouter(prefix="/issues", tags=["Issues"])
# An issue's number in an address: 1 up to the largest id the database holds.
IssueId = Annotated[int, Path(ge=1, le=LARGEST_ID)]


def ok(message, data=None):
    return {"success": True, "message": message, "data": data}


def refuse_issue(error: IssueError) -> HTTPException:
    # A value that cannot be accepted is answered like FastAPI's own checks are (a list naming the
    # field), so the console can put the words next to it. Nothing that was sent is repeated.
    if error.field:
        return HTTPException(error.status, [{"type": "value_error", "loc": ["body", error.field], "msg": error.message}])
    return HTTPException(error.status, error.message)


@router.post("")
def report_issue(payload: IssueCreate, actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    fields = payload.model_dump()
    try:
        issue = issue_service.report(db, actor, **fields)
    except IssueError as error:
        raise refuse_issue(error)
    return ok("Issue reported", issue_data(issue, for_reporter=True))


@router.get("")
def my_issues(status: str | None = None, page: PageNumber = 1, page_size: PageSize = 25,
              actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        rows, total = issue_service.own_issues(db, actor, status, page, page_size)
    except IssueError as error:
        raise refuse_issue(error)
    return ok("Issues fetched", {"items": [issue_row_data(issue, for_reporter=True) for issue in rows], "total": total, "page": page, "page_size": page_size})


@router.get("/{issue_id}")
def my_issue(issue_id: IssueId, actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        issue = issue_service.own_issue(db, actor, issue_id)
    except IssueError as error:
        raise refuse_issue(error)
    return ok("Issue fetched", issue_data(issue, issue_service.comments_of(db, issue), for_reporter=True))


@router.post("/{issue_id}/comments")
def comment_on_my_issue(issue_id: IssueId, payload: CommentCreate, actor: Actor = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        comment = issue_service.comment_on_own(db, actor, issue_id, payload.body)
    except IssueError as error:
        raise refuse_issue(error)
    return ok("Comment added", issue_comment_data(comment))
