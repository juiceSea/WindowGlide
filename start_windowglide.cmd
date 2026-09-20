@echo off
cd /d "%~dp0"
python main.py
if errorlevel 1 (
  echo WindowGlide failed. See the latest dated file in logs for details.
  pause
)
