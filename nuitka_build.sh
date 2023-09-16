#!/bin/bash

NUITKA_COMPILE_FLAGS="--standalone --onefile --remove-output --no-deployment-flag=self-execution"

rm bin/wookiee_unicaster
nuitka3 wookiee_unicaster.py $NUITKA_COMPILE_FLAGS
chmod +x wookiee_unicaster.bin
mv wookiee_unicaster.bin bin/wookiee_unicaster

