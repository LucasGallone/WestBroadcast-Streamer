@echo off
chcp 65001 >nul
title WestBroadcast Streamer - Launcher

set "IS_FR=0"
for /f "tokens=3" %%A in ('reg query "HKCU\Control Panel\International" /v LocaleName 2^>nul') do (
    set "USER_LOCALE=%%A"
)
if defined USER_LOCALE (
    if /i "%USER_LOCALE:~0,2%"=="fr" set "IS_FR=1"
) else (
    for /f "tokens=3" %%A in ('reg query "HKCU\Control Panel\International" /v sLanguage 2^>nul') do (
        set "USER_SLANG=%%A"
    )
    if defined USER_SLANG (
        if /i "%USER_SLANG:~0,2%"=="fr" set "IS_FR=1"
    )
)

if "%IS_FR%"=="1" (
    echo =====================================================
    echo    PRÉPARATION DU DÉCODEUR ET VÉRIFICATION REQUISE
    echo =====================================================
    echo.
    echo Vérification des fichiers requis... et si manquants, installation des dépendances.
    echo ^(Cette étape peut prendre quelques instants lors du tout premier lancement.^)
    echo.
) else (
    echo ======================================================
    echo    PREPARING THE DECODER AND VERIFYING REQUIREMENTS
    echo ======================================================
    echo.
    echo Verification of required files... and if missing, installation of dependencies.
    echo ^(This step may take a few moments when launching for the first time.^)
    echo.
)

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    if "%IS_FR%"=="1" (
        echo [ERREUR] Python n'est pas installé ou est manquant au PATH Windows.
        echo Veuillez installer ^(Version 3.10 ou supérieure^) en vous assurant de cocher "Add Python to PATH" lors de l'installation.
    ) else (
        echo [ERROR] Python is not installed or not added to the Windows PATH.
        echo Please install Python ^(Version 3.10 or newer^) and make sure to check "Add Python to PATH" in the setup wizard.
    )
    echo.
    pause
    exit /b
)

python -c "import flask, flask_socketio, numpy, sounddevice" >nul 2>&1
if errorlevel 1 (
    python -m pip install --quiet flask "flask-socketio>=5.3.6,<6.0.0" numpy sounddevice psutil
)

if "%IS_FR%"=="1" (
    echo.
    echo ===========================================================
    echo    LANCEMENT DU DÉCODEUR EN COURS... VEUILLEZ PATIENTEZ.
    echo ===========================================================
    echo.
    echo IMPORTANT : Vous devez garder ce terminal ouvert, sinon le logiciel se fermera !
    echo.
) else (
    echo.
    echo ================================================
    echo    DECODER LAUNCH IN PROGRESS... PLEASE WAIT.
    echo ================================================
    echo.
    echo IMPORTANT: You must keep this terminal open, otherwise the software will close!
    echo.
)

python app.py

echo.
pause