#!/bin/bash

NUITKA_COMPILE_FLAGS="--standalone --onefile --remove-output --no-deployment-flag=self-execution --assume-yes-for-downloads"

rm bin/blank.tmp 2>/dev/null
rm bin/wookiee_unicaster 2>/dev/null
python3 -m nuitka wookiee_unicaster.py $NUITKA_COMPILE_FLAGS
chmod +x wookiee_unicaster.bin
mv wookiee_unicaster.bin bin/wookiee_unicaster

