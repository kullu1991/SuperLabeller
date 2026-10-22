@echo off
rem Builds dist\SuperLabeller.exe. Needs Python 3.9+ with: pip install -r requirements.txt pyinstaller
cd /d "%~dp0"
py -3 build.py || python build.py
pause
