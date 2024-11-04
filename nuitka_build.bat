@echo off

SET nuitka_compile_flags=--standalone --onefile --remove-output --no-deployment-flag=self-execution --assume-yes-for-downloads

DEL bin\blank.tmp 2>nul
DEL bin\wookiee_unicaster.exe 2>nul
python -m nuitka %nuitka_compile_flags% wookiee_unicaster.py
MOVE wookiee_unicaster.exe bin\wookiee_unicaster.exe

