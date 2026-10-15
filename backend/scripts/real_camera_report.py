"""Turn a supervised real-camera session into numbers (docs/REAL_CAMERA_TEST.md has the protocol).

    python scripts/real_camera_report.py attempts.csv --session 12

attempts.csv is filled in by hand during the test, one row per attempt (the template is
docs/real_camera_attempts_template.csv):

    attempt  kind      person_code  start     end       notes
    1        enrolled  STU-001      10:02:05  10:02:40  normal light
    2        stranger               10:03:00  10:03:45  visitor, never enrolled
    3        screen    STU-002      10:04:10  10:05:10  phone photo of STU-002, full brightness

kind is one of enrolled (that student, live), stranger (a person who is not enrolled), print,
screen or video (a picture or recording of the student in person_code), pair (two students
together; person_code "STU-001;STU-002"). start and end are the clock times of the attempt, on the
session's day.

What it reads, without changing anything: the session's attendance records made by the scanner
(recognition_method face_ai; marks by hand do not count) and, if present, logs/recognition.log for
what the scanner said meanwhile. What it prints: for each attempt whether the right student was
marked and how long it took, and in total how often enrolled students were marked, how often a
stranger or a picture was marked, and how often anyone was marked as someone else.

An attempt for a student who was already marked before it started cannot show anything (there is one
record per student and session) and is reported as not measurable: give each spoof attempt a student
who has not been marked yet, or start a new session.
"""
import argparse
import csv
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KINDS = ("enrolled", "stranger", "print", "screen", "video", "pair")
SPOOFS = ("print", "screen", "video")
LOG_FILE = ROOT / "logs" / "recognition.log"


def clock(day, text):
    return datetime.combine(day, datetime.strptime(text.strip(), "%H:%M:%S").time())


def read_attempts(path, day):
    attempts = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            kind = (row.get("kind") or "").strip().lower()
            if kind not in KINDS:
                raise ValueError(f"line {number}: kind must be one of {', '.join(KINDS)}, not {kind!r}")
            codes = [code.strip() for code in (row.get("person_code") or "").split(";") if code.strip()]
            if kind != "stranger" and not codes:
                raise ValueError(f"line {number}: a {kind} attempt needs the person_code of the student it shows")
            start, end = clock(day, row["start"]), clock(day, row["end"])
            if end <= start:
                raise ValueError(f"line {number}: end must be after start")
            attempts.append({"attempt": (row.get("attempt") or str(number - 1)).strip(), "kind": kind, "codes": codes,
                             "start": start, "end": end, "notes": (row.get("notes") or "").strip()})
    return attempts


def score(attempts, records, verdicts=()):
    """attempts: from read_attempts. records: the scanner's records of the session, each
    {"person_code", "marked_time"}. verdicts: scanner log lines {"time", "result", "person_code"}.
    Returns (one result per attempt, totals)."""
    results = []
    for attempt in attempts:
        inside = [record for record in records if attempt["start"] <= record["marked_time"] <= attempt["end"]]
        before = {record["person_code"] for record in records if record["marked_time"] < attempt["start"]}
        said = [item["result"] for item in verdicts if attempt["start"] <= item["time"] <= attempt["end"]]
        result = {**attempt, "verdicts": {name: said.count(name) for name in sorted(set(said))}}
        if attempt["kind"] != "stranger" and all(code in before for code in attempt["codes"]):
            result.update(outcome="not measurable", detail="already marked before the attempt")
        elif attempt["kind"] in ("enrolled", "pair"):
            right = {code: next((r for r in inside if r["person_code"] == code), None) for code in attempt["codes"] if code not in before}
            wrong = [r["person_code"] for r in inside if r["person_code"] not in attempt["codes"]]
            seconds = [(r["marked_time"] - attempt["start"]).total_seconds() for r in right.values() if r]
            result.update(outcome="marked" if all(right.values()) else "not marked", marked=sum(1 for r in right.values() if r),
                          expected=len(right), wrong=wrong, seconds=seconds)
        else:
            result.update(outcome="refused" if not inside else "MARKED", wrong=[r["person_code"] for r in inside])
        results.append(result)

    def rate(hits, tries):
        # With no failure in n tries, the true rate is below 3/n with 95% confidence (rule of three).
        return {"hits": hits, "tries": tries, "rate": hits / tries if tries else None, "upper_95_if_none": (min(1.0, 3 / tries) if tries and not hits else None)}

    genuine = [r for r in results if r["kind"] in ("enrolled", "pair") and r["outcome"] != "not measurable"]
    strangers = [r for r in results if r["kind"] == "stranger"]
    times = [s for r in genuine for s in r.get("seconds", [])]
    totals = {
        "students marked": rate(sum(r["marked"] for r in genuine), sum(r["expected"] for r in genuine)),
        "marked as someone else": rate(sum(len(r["wrong"]) for r in genuine), len(genuine)),
        "strangers marked": rate(sum(1 for r in strangers if r["outcome"] == "MARKED"), len(strangers)),
        "seconds to mark (median)": round(statistics.median(times), 1) if times else None,
        "seconds to mark (slowest)": round(max(times), 1) if times else None,
        "not measurable": sum(1 for r in results if r["outcome"] == "not measurable"),
    }
    for kind in SPOOFS:
        tried = [r for r in results if r["kind"] == kind and r["outcome"] != "not measurable"]
        totals[f"{kind} attacks marked"] = rate(sum(1 for r in tried if r["outcome"] == "MARKED"), len(tried))
    return results, totals


def read_records(session_id):
    # The scanner's records of the session, read in a READ ONLY transaction (PostgreSQL) or from a
    # file opened read-only (SQLite). Returns (session day, records).
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.config import settings
    from app.database import clean_database_url, connection_options

    raw = clean_database_url(settings.database_url)
    url = make_url(raw)
    if url.get_backend_name() == "sqlite":
        path = Path(url.database).resolve()
        engine = create_engine(f"sqlite:///file:{path.as_posix()}?mode=ro&uri=true")
    else:
        engine = create_engine(url, hide_parameters=True, **connection_options(raw))
    with engine.connect() as connection:
        if url.get_backend_name() == "postgresql":
            connection.execute(text("SET TRANSACTION READ ONLY"))
        day = connection.execute(text("SELECT session_date FROM attendance_sessions WHERE id = :id"), {"id": session_id}).scalar()
        if day is None:
            raise ValueError(f"There is no session {session_id}.")
        rows = connection.execute(text(
            "SELECT person_code, person_id, marked_time FROM attendance_records "
            "WHERE session_id = :id AND recognition_method = 'face_ai'"), {"id": session_id}).all()
        codes = dict(connection.execute(text("SELECT id, person_code FROM user_management")).all())
        connection.rollback()
    engine.dispose()
    day = day if not isinstance(day, str) else datetime.strptime(day, "%Y-%m-%d").date()
    records = [{"person_code": row.person_code, "marked_time": row.marked_time if isinstance(row.marked_time, datetime) else datetime.fromisoformat(str(row.marked_time))} for row in rows]
    return day, records, codes


def read_verdicts(session_id, codes, path=LOG_FILE):
    verdicts = []
    if not path.exists():
        return verdicts
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("event") == "scan" and item.get("session_id") == session_id:
            verdicts.append({"time": datetime.fromisoformat(item["time"]).replace(tzinfo=None), "result": item.get("result"), "person_code": codes.get(item.get("person_id"))})
    return verdicts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("attempts", type=Path)
    parser.add_argument("--session", type=int, required=True, help="the attendance session the test ran in")
    parser.add_argument("--json", type=Path, help="also write the results here")
    args = parser.parse_args()

    day, records, codes = read_records(args.session)
    results, totals = score(read_attempts(args.attempts, day), records, read_verdicts(args.session, codes))
    print(f"Session {args.session} on {day}: {len(records)} records made by the scanner\n")
    print(f"{'#':>3}  {'kind':9s} {'students':22s} {'outcome':15s} {'seconds':>8s}  what the scanner said")
    for r in results:
        seconds = ", ".join(f"{s:.0f}" for s in r.get("seconds", [])) or "-"
        extra = f"  WRONG: {', '.join(r['wrong'])}" if r.get("wrong") else ""
        said = ", ".join(f"{k} {v}" for k, v in r["verdicts"].items()) or "-"
        print(f"{r['attempt']:>3}  {r['kind']:9s} {';'.join(r['codes']) or '-':22s} {r['outcome']:15s} {seconds:>8s}  {said}{extra}")
    print("\nTotals")
    for name, value in totals.items():
        if isinstance(value, dict):
            shown = f"{value['hits']} of {value['tries']}" + (f" ({100 * value['rate']:.1f}%)" if value["rate"] is not None else "")
            if value["upper_95_if_none"]:
                shown += f"; none seen, so below {100 * value['upper_95_if_none']:.0f}% with 95% confidence"
            print(f"  {name:28s} {shown}")
        else:
            print(f"  {name:28s} {value if value is not None else '-'}")
    if args.json:
        args.json.write_text(json.dumps({"session": args.session, "results": results, "totals": totals}, default=str, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
