"""The scoring of a supervised real-camera session (scripts/real_camera_report.py), on made-up records."""
import csv
import importlib.util
from datetime import date, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "real_camera_report.py"
spec = importlib.util.spec_from_file_location("real_camera_report", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

DAY = date(2026, 10, 16)


def at(text):
    return datetime.combine(DAY, datetime.strptime(text, "%H:%M:%S").time())


def attempt(number, kind, codes, start, end):
    return {"attempt": str(number), "kind": kind, "codes": codes, "start": at(start), "end": at(end), "notes": ""}


def record(code, time):
    return {"person_code": code, "marked_time": at(time)}


def test_a_session_is_scored_attempt_by_attempt():
    attempts = [
        attempt(1, "enrolled", ["A"], "10:00:00", "10:00:40"),
        attempt(2, "enrolled", ["B"], "10:01:00", "10:01:40"),
        attempt(3, "stranger", [], "10:02:00", "10:02:45"),
        attempt(4, "screen", ["C"], "10:03:00", "10:04:00"),
        attempt(5, "print", ["A"], "10:05:00", "10:05:30"),
        attempt(6, "pair", ["C", "D"], "10:06:00", "10:06:50"),
    ]
    records = [record("A", "10:00:12"), record("C", "10:06:20"), record("D", "10:06:31")]
    verdicts = [{"time": at("10:02:10"), "result": "unknown", "person_code": None}, {"time": at("10:03:05"), "result": "liveness_failed", "person_code": "C"}]

    results, totals = tool.score(attempts, records, verdicts)

    assert [(r["attempt"], r["outcome"]) for r in results] == [("1", "marked"), ("2", "not marked"), ("3", "refused"), ("4", "refused"), ("5", "not measurable"), ("6", "marked")]
    assert results[0]["seconds"] == [12.0] and results[5]["seconds"] == [20.0, 31.0]
    assert results[2]["verdicts"] == {"unknown": 1} and results[3]["verdicts"] == {"liveness_failed": 1}
    assert totals["students marked"]["hits"] == 3 and totals["students marked"]["tries"] == 4
    # With one try the "rule of three" bound says nothing: it is capped at 100%.
    assert totals["strangers marked"] == {"hits": 0, "tries": 1, "rate": 0.0, "upper_95_if_none": 1.0}
    assert totals["screen attacks marked"]["hits"] == 0 and totals["print attacks marked"]["tries"] == 0
    assert totals["not measurable"] == 1 and totals["seconds to mark (median)"] == 20.0


def test_a_stranger_or_a_picture_that_gets_a_record_is_counted_against_the_system():
    attempts = [attempt(1, "stranger", [], "09:00:00", "09:01:00"), attempt(2, "video", ["B"], "09:02:00", "09:03:00")]
    records = [record("A", "09:00:30"), record("B", "09:02:40")]

    results, totals = tool.score(attempts, records)

    assert [r["outcome"] for r in results] == ["MARKED", "MARKED"] and results[0]["wrong"] == ["A"]
    assert totals["strangers marked"]["hits"] == 1 and totals["video attacks marked"]["hits"] == 1


def test_a_student_marked_as_someone_else_is_reported():
    results, totals = tool.score([attempt(1, "enrolled", ["A"], "11:00:00", "11:01:00")], [record("B", "11:00:20")])

    assert results[0]["outcome"] == "not marked" and results[0]["wrong"] == ["B"]
    assert totals["marked as someone else"]["hits"] == 1


def test_the_attempts_file_is_checked(tmp_path):
    path = tmp_path / "attempts.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["attempt", "kind", "person_code", "start", "end", "notes"])
        writer.writerow(["1", "enrolled", "STU-1", "10:00:00", "10:00:30", ""])
        writer.writerow(["2", "pair", "STU-1; STU-2", "10:01:00", "10:01:30", ""])
    attempts = tool.read_attempts(path, DAY)
    assert [a["codes"] for a in attempts] == [["STU-1"], ["STU-1", "STU-2"]] and attempts[0]["start"] == at("10:00:00")

    for bad, message in ((["3", "selfie", "STU-1", "10:00:00", "10:00:30", ""], "kind must be one of"),
                         (["3", "screen", "", "10:00:00", "10:00:30", ""], "needs the person_code"),
                         (["3", "enrolled", "STU-1", "10:00:30", "10:00:00", ""], "end must be after start")):
        with path.open("a", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(bad)
        with pytest.raises(ValueError, match=message):
            tool.read_attempts(path, DAY)
        lines = path.read_text(encoding="utf-8").splitlines()[:-1]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_template_in_the_docs_is_a_valid_attempts_file():
    template = Path(__file__).resolve().parents[2] / "docs" / "real_camera_attempts_template.csv"

    attempts = tool.read_attempts(template, DAY)

    assert {a["kind"] for a in attempts} == set(tool.KINDS)
