@echo off
DEL bin\wookiee_unicaster.exe
python -m nuitka --standalone --onefile --remove-output wookiee_unicaster.py
MOVE wookiee_unicaster.exe bin\wookiee_unicaster.exe

