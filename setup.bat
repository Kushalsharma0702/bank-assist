@echo off
REM Quick Start Script for Banking Voice Assistant (Windows)

setlocal enabledelayedexpansion

echo.
echo ================================
echo.   Banking Voice Assistant Setup
echo ================================
echo.

REM Check prerequisites
echo Checking prerequisites...

where python >nul 2>nul
if errorlevel 1 (
    echo Error: Python is not installed
    exit /b 1
)
echo [OK] Python found

where node >nul 2>nul
if errorlevel 1 (
    echo Error: Node.js is not installed
    exit /b 1
)
echo [OK] Node.js found

REM Setup backend
echo.
echo Setting up backend...

if not exist "backend\venv" (
    cd backend
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    cd ..
    echo [OK] Backend dependencies installed
) else (
    echo [OK] Backend environment already exists
)

REM Setup frontend
echo.
echo Setting up frontend...

if not exist "frontend\node_modules" (
    cd frontend
    call npm install
    cd ..
    echo [OK] Frontend dependencies installed
) else (
    echo [OK] Frontend dependencies already installed
)

REM Check .env file
echo.
echo Checking environment configuration...

if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env
        echo [!] Created .env from template
        echo [!] Please edit .env with your credentials!
    ) else (
        echo Error: .env file not found
        exit /b 1
    )
) else (
    echo [OK] .env file exists
)

REM Display next steps
echo.
echo ================================
echo [OK] Setup Complete!
echo ================================
echo.
echo Next steps:
echo.
echo 1. Edit .env with your credentials
echo    notepad .env
echo.
echo 2. Start backend (CMD 1):
echo    cd backend
echo    venv\Scripts\activate.bat
echo    python main.py
echo.
echo 3. Start frontend (CMD 2):
echo    cd frontend
echo    npm run dev
echo.
echo 4. Open browser:
echo    http://localhost:5173
echo.
echo Or use Docker:
echo    docker-compose up --build
echo.

pause
