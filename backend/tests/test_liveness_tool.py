import csv
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "liveness_camera_test.py"
spec = importlib.util.spec_from_file_location("liveness_camera_test", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def rows(label, run, scores):
    return [{"time": "t", "run": run, "label": label, "note": "", "score": score, "face_px": 120, "turn": 0.0, "faces_in_frame": 1} for score in scores]


def test_the_summary_counts_each_verdict_per_kind_of_sample():
    data = rows("live", "a", [0.95, 0.9, 0.6, 0.3]) + rows("screen", "b", [0.2, 0.1, 0.8, 0.55]) + rows("screen", "c", [0.05])

    summary = tool.summarize(data, 0.50, 0.70)

    assert summary["live"] == {"frames": 4, "runs": 1, "live": 0.5, "uncertain": 0.25, "spoof": 0.25, "median": 0.9, "p5": 0.3, "p95": 0.9}
    assert (summary["screen"]["frames"], summary["screen"]["runs"]) == (5, 2)
    # One of five screen frames would have been accepted by the passive check on its own.
    assert summary["screen"]["live"] == 0.2 and summary["screen"]["spoof"] == 0.6


def test_the_report_reads_what_was_recorded_and_warns_about_thin_data(tmp_path, monkeypatch, capsys):
    log = tmp_path / "liveness_test.csv"
    with log.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tool.FIELDS)
        writer.writeheader()
        writer.writerows(rows("live", "a", [0.99, 0.97, 0.91]) + rows("print", "b", [0.1, 0.72]))
    monkeypatch.setattr(tool, "LOG_FILE", log)

    tool.report(None)

    printed = capsys.readouterr().out
    assert "5 frames" in printed and "print accepted" in printed
    assert "NOT ENOUGH DATA for 'live'" in printed and "NOT ENOUGH DATA for 'video'" in printed
