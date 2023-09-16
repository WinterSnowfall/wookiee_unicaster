@echo off

SET nuitka_compile_flags=--standalone --onefile --remove-output --no-deployment-flag=self-execution

DEL bin\wookiee_unicaster.exe
python -m nuitka %nuitka_compile_flags% wookiee_unicaster.py
MOVE wookiee_unicaster.exe bin\wookiee_unicaster.exe

