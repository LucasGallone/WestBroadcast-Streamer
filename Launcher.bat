@echo off
title WestBroadcast Streamer - Launcher
echo ======================================================
echo    PREPARING THE DECODER AND VERIFYING REQUIREMENTS
echo ======================================================
echo.
echo Verification of required files... and if missing, installation of dependencies.
echo (This step may take a few moments when launching for the first time.)
echo.

pip install --quiet flask flask-socketio numpy sounddevice

echo.
echo ================================================
echo    DECODER LAUNCH IN PROGRESS... PLEASE WAIT.
echo ================================================
echo.
echo IMPORTANT: You must keep this terminal open, otherwise the software will close!
echo.

python app.py

echo.
pause