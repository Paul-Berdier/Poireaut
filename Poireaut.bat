@echo off
title Poireaut
cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python non trouve. Installer Python 3.11+ depuis python.org
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creation de l environnement virtuel...
    python -m venv .venv
)

if not exist ".venv\.ready" (
    echo.
    echo Installation des dependances...
    echo Cela peut prendre quelques minutes.
    echo.
    .venv\Scripts\pip install --upgrade pip -q
    .venv\Scripts\pip install pywebview Pillow imagehash httpx pydantic typer rich structlog phonenumbers -q
    .venv\Scripts\pip install -e . -q
    .venv\Scripts\pip install maigret -q 2>nul
    .venv\Scripts\pip install holehe -q 2>nul
    echo OK > ".venv\.ready"
    echo Installation terminee.
    echo.
)

echo Lancement de Poireaut...
.venv\Scripts\python -m osint_core.app.main
if %errorlevel% neq 0 (
    echo.
    echo Erreur. Appuyez sur une touche.
    pause
)
