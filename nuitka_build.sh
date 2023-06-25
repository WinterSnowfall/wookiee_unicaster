#!/bin/bash

rm bin/wookiee_unicaster
nuitka3 wookiee_unicaster.py --standalone --onefile --remove-output
chmod +x wookiee_unicaster.bin
mv wookiee_unicaster.bin bin/wookiee_unicaster

