@echo off
rem Is the Python that this command starts the supported one (3.10)? Exit code 0 when it is, 1 when it
rem is another version, anything else when it does not start at all. Used by setup.bat, e.g.
rem     call backend\scripts\check_python.bat py -3.10
rem TensorFlow and DeepFace, pinned in backend\requirements.txt, install and were measured on 3.10 only.
%* -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 1)" >nul 2>&1
exit /b %errorlevel%
