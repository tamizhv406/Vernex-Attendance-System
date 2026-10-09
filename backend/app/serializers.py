from datetime import date, datetime, time


def iso(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


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
