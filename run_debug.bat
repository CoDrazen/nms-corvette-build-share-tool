@echo off
setlocal
cd /d "%~dp0"
set "NMS_CORVETTE_DEBUG_PAIRING=1"
python\python.exe ship_viewer.py
pause
