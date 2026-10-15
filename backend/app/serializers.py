from datetime import date, datetime, time


def iso(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


def utc_iso(value):
    # The login tables and the audit log hold UTC without a time zone. Said so with a "Z", so that a
    # browser shows the time in its own zone instead of taking it for local time.
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat() + "Z"
    return iso(value)


def admin_account_data(account):
    # What the console may know about a login account. Never the password hash, and not the
    # failed-login count or the lock time either, which would tell a guesser how far along they are.
    return {
        "id": account.id,
        "email": account.email,
        "full_name": account.full_name,
        "role": account.role,
        "status": account.status,
        "must_change_password": bool(account.must_change_password),
        "last_login_at": utc_iso(account.last_login_at),
        "created_at": utc_iso(account.created_at),
        "updated_at": utc_iso(account.updated_at),
    }


def managed_account_data(account, now):
    # What a super admin sees of an account they manage: the above, whether it is locked out now,
    # when its temporary password stops working, and who created it. Still never the hash, and not
    # the count of wrong passwords.
    locked = bool(account.locked_until and account.locked_until > now)
    expires = account.temporary_password_expires_at if account.must_change_password else None
    return dict(
        admin_account_data(account),
        locked=locked,
        locked_until=utc_iso(account.locked_until) if locked else None,
        temporary_password_expires_at=utc_iso(expires),
        temporary_password_expired=bool(expires and now >= expires),
        # Its password is reset on the server only (it is or has been a super admin).
        has_been_super_admin=bool(account.has_been_super_admin or account.role == "super_admin"),
        created_by=account.created_by,
    )


def _person(account):
    # Who wrote, reported or was given an issue: a name to show, and nothing about the account itself.
    return {"id": account.id, "full_name": account.full_name, "role": account.role} if account else None


def issue_comment_data(comment):
    return {"id": comment.id, "body": comment.body, "created_at": utc_iso(comment.created_at), "author": _person(comment.author)}


def issue_row_data(issue, for_reporter=False):
    """One line of a list of issues: enough to recognise it, without its description or its thread.
    For its reporter (My reports) who it is assigned to is left out."""
    data = {
        "id": issue.id,
        "title": issue.title,
        "category": issue.category,
        "severity": issue.severity,
        "status": issue.status,
        "created_at": utc_iso(issue.created_at),
        "updated_at": utc_iso(issue.updated_at),
        "resolved_at": utc_iso(issue.resolved_at),
    }
    if not for_reporter:
        data["reporter"] = dict(_person(issue.reporter), email=issue.reporter.email)
        data["assigned_to"] = issue.assigned_to
        data["assignee"] = _person(issue.assignee)
    return data


def issue_data(issue, comments=(), for_reporter=False):
    """The page of one issue, with its thread (oldest first). Its reporter sees the resolution note
    only while it applies, once the issue has been resolved. A super admin also sees the note that an
    issue opened again still keeps, to start from when resolving it once more."""
    return dict(
        issue_row_data(issue, for_reporter),
        description=issue.description,
        page_url=issue.page_url,
        device_info=issue.device_info or {},
        resolution_note=issue.resolution_note if issue.resolved_at or not for_reporter else None,
        comments=[issue_comment_data(comment) for comment in comments],
    )


def audit_log_data(entry, actor=None, target_label=None, action_label=None):
    return {
        "id": entry.id,
        "created_at": utc_iso(entry.created_at),
        "action": entry.action,
        "action_label": action_label or entry.action,
        "actor": {"id": actor.id, "email": actor.email, "full_name": actor.full_name} if actor else None,
        "actor_id": entry.actor_id,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "target_label": target_label,
        "details": entry.details or {},
        "ip": entry.ip,
        "user_agent": entry.user_agent,
    }


def course_data(course):
    return {
        "id": course.id,
        "course_code": course.course_code,
        "course_name": course.course_name,
        "description": course.description,
        "status": course.status,
        "created_at": iso(course.created_at),
        "updated_at": iso(course.updated_at),
    }


def batch_data(batch):
    return {
        "id": batch.id,
        "course_id": batch.course_id,
        "batch_name": batch.batch_name,
        "batch_level": batch.batch_level,
        "timing_id": batch.timing_id,
        "status": batch.status,
        "course_name": batch.course.course_name if getattr(batch, "course", None) else None,
        "created_at": iso(batch.created_at),
        "updated_at": iso(batch.updated_at),
    }


def person_data(person, course=None, batch=None):
    return {
        "id": person.id,
        "person_code": person.person_code,
        "full_name": person.full_name,
        "phone": person.phone,
        "email": person.email,
        "person_type": person.person_type,
        "gender": person.gender,
        "guardian_name": person.guardian_name,
        "guardian_phone": person.guardian_phone,
        "course_id": person.course_id,
        "batch_id": person.batch_id,
        "course_code": course.course_code if course else None,
        "course_name": course.course_name if course else person.category_program,
        "batch_name": batch.batch_name if batch else person.batch_name,
        "batch_level": batch.batch_level if batch else None,
        "category_program": person.category_program,
        "level_class": person.level_class,
        "designation": person.designation,
        "department": person.department,
        "membership_type": person.membership_type,
        "plan_name": person.plan_name,
        "timing_id": person.timing_id,
        "joining_date": iso(person.joining_date),
        "status": person.status,
        "face_enrollment_status": person.face_enrollment_status,
        "notes": person.notes,
        "created_at": iso(person.created_at),
        "updated_at": iso(person.updated_at),
    }


def timing_data(timing):
    return {
        "id": timing.id,
        "name": timing.name,
        "timing_type": timing.timing_type,
        "category_program": timing.category_program,
        "batch_name": timing.batch_name,
        "start_time": iso(timing.start_time),
        "grace_time": iso(timing.grace_time),
        "end_time": iso(timing.end_time),
        "late_after_time": iso(timing.late_after_time),
        "auto_absent_after_time": iso(timing.auto_absent_after_time),
        "working_days": timing.working_days,
        "status": timing.status,
        "created_at": iso(timing.created_at),
        "updated_at": iso(timing.updated_at),
    }


def attendance_session_data(session):
    return {
        "id": session.id,
        "session_name": session.session_name,
        "session_type": session.session_type,
        "course_id": session.course_id,
        "batch_id": session.batch_id,
        "category_program": session.category_program,
        "batch_name": session.batch_name,
        "timing_id": session.timing_id,
        "session_date": iso(session.session_date),
        "start_time": iso(session.start_time),
        "grace_time": iso(session.grace_time),
        "end_time": iso(session.end_time),
        "status": session.status,
        "created_at": iso(session.created_at),
        "updated_at": iso(session.updated_at),
    }


def attendance_record_data(record):
    return {
        "id": record.id,
        "session_id": record.session_id,
        "person_id": record.person_id,
        "person_code": record.person_code,
        "person_name": record.person_name,
        "person_type": record.person_type,
        "course_id": record.course_id,
        "batch_id": record.batch_id,
        "category_program": record.category_program,
        "batch_name": record.batch_name,
        "level_class": record.level_class,
        "attendance_date": iso(record.attendance_date),
        "marked_time": iso(record.marked_time),
        "status": record.status,
        "confidence_score": record.confidence_score,
        "recognition_method": record.recognition_method,
        "device_name": record.device_name,
        "marked_by": record.marked_by,
        "duplicate_flag": record.duplicate_flag,
        "sync_status": record.sync_status,
        "notes": record.notes,
        "created_at": iso(record.created_at),
        "updated_at": iso(record.updated_at),
    }


def face_enrollment_data(enrollment):
    if not enrollment:
        return None
    return {
        "id": enrollment.id,
        "person_id": enrollment.person_id,
        "enrollment_status": enrollment.enrollment_status,
        "current_step": enrollment.current_step,
        "total_steps": enrollment.total_steps,
        "completed_steps": enrollment.completed_steps,
        "quality_score": enrollment.quality_score,
        "has_specs_reference": enrollment.has_specs_reference,
        "started_at": iso(enrollment.started_at),
        "completed_at": iso(enrollment.completed_at),
        "created_at": iso(enrollment.created_at),
        "updated_at": iso(enrollment.updated_at),
    }
