@echo off
setlocal
title PrivacyShield Local Server
echo ============================================================
echo   PrivacyShield - Anti-DreamBooth and JPEG-aware
echo   De tai NCKH: Bao ve anh truoc mo hinh sinh DreamBooth
echo ============================================================
echo.

cd /d "%~dp0backend"

:: Kiem tra Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Khong tim thay Python! Vui long cai Python 3.10 tro len.
    pause
    exit /b 1
)

echo ============================================================
echo [OK] May chu Backend va Web App dang chay tai:
echo      http://localhost:5000
echo ============================================================
echo.
echo Nhan Ctrl+C de dung server bat cu luc nao.
echo.

:: Tu dong mo trinh duyet
start "" "http://localhost:5000"

:: Chay backend
python app.py

pause
