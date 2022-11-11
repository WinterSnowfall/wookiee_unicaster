@echo off
del wookiee_unicaster.exe
python -m nuitka --standalone --onefile --remove-output wookiee_unicaster.py
