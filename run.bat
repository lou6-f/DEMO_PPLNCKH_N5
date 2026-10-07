@echo off
echo ============================================================
echo  PrivacyShield — Anti-DreamBooth & JPEG-aware Perturbation
echo  De tai NCKH: Bao ve anh truoc mo hinh sinh DreamBooth
echo ============================================================
echo.

cd /d "%~dp0backend"

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python khong tim thay! Vui long cai Python 3.10+.
    pause
    exit /b 1
)

echo [OK] Dang kiem tra dependencies...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [WARNING] Co loi khi cai dependencies. Thu tiep tuc chay...
)

echo.
echo ============================================================
echo [OK] May chu Backend & Web App dang chay tai:
echo      http://localhost:5000
echo ============================================================
echo.
echo Nhan Ctrl+C de dung server bat cu luc nao.
echo.

:: Launch browser pointing to local web server
start "" "http://localhost:5000"

:: Start Flask server
python app.py

pause
