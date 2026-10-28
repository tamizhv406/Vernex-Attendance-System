"""setup.bat uses Python 3.10 only, and never reuses an environment made with another version.

Until October 2026 it fell back to whatever "python" was installed and kept any backend\\.venv it found:
an environment made with Python 3.15 started the backend without TensorFlow, and no face could be
checked. These tests run setup.bat in its /check mode, which installs and changes nothing.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="setup.bat is for Windows")

ROOT = Path(__file__).resolve().parents[2]
CHECK_PYTHON = ROOT / "backend" / "scripts" / "check_python.bat"
VENV_PYTHON = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"


def run(*command):
    # Full paths: a shell may refuse to run a program from the current folder by its bare name.
    return subprocess.run(["cmd", "/c", *map(str, command)], cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)


def py_has(version):
    return shutil.which("py") and subprocess.run(["py", f"-{version}", "--version"], capture_output=True).returncode == 0


@pytest.mark.skipif(not py_has("3.10"), reason="Python 3.10 is not installed here")
def test_python_3_10_is_accepted():
    assert run(CHECK_PYTHON, "py", "-3.10").returncode == 0


@pytest.mark.parametrize("version", ["3.11", "3.12", "3.13", "3.14", "3.15"])
def test_another_python_is_refused(version):
    if not py_has(version):
        pytest.skip(f"Python {version} is not installed here")
    assert run(CHECK_PYTHON, "py", f"-{version}").returncode == 1


def test_a_python_that_does_not_start_is_refused():
    assert run(CHECK_PYTHON, "no-such-python-anywhere").returncode != 0


def venv_is_3_10():
    if not VENV_PYTHON.exists():
        return None
    answer = subprocess.run([str(VENV_PYTHON), "-c", "import sys; print(sys.version_info[:2] == (3, 10))"], capture_output=True, text=True)
    return answer.stdout.strip() == "True"


@pytest.mark.skipif(not py_has("3.10"), reason="Python 3.10 is not installed here")
def test_the_check_agrees_with_the_environment_and_changes_nothing():
    existed = (ROOT / "backend" / ".venv").exists()
    good = venv_is_3_10()

    answer = run(ROOT / "setup.bat", "/check")

    if good is False:
        assert answer.returncode == 1 and "is not a working Python 3.10 environment" in answer.stdout, answer.stdout
    else:
        assert answer.returncode == 0 and "[OK]" in answer.stdout, answer.stdout
    assert (ROOT / "backend" / ".venv").exists() == existed
    # The check stops before anything is installed.
    assert "Installing" not in answer.stdout
