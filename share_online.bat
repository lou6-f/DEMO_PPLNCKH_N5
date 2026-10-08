@echo off
setlocal
title PrivacyShield - Cloudflare Online Tunnel

echo ==============================================================================
echo   PrivacyShield - Tao Duong Dan Public Online (Cloudflare Tunnel)
echo   Ho tro chia se web app cho thay co, ban be truy cap qua Internet / 4G
echo ==============================================================================
echo.

cd /d "%~dp0"

:: 1. Kiem tra cloudflared.exe
if exist "cloudflared.exe" goto has_cloudflared

echo [1/2] Dang tai cong cu tao tunnel Cloudflare (cloudflared.exe ~50MB)...
curl.exe -L -o cloudflared.exe "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
if not exist "cloudflared.exe" (
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe', 'cloudflared.exe')"
)
if not exist "cloudflared.exe" (
    echo [ERROR] Khong the tu dong tai cloudflared.exe. Vui long kiem tra ket noi mang.
    pause
    exit /b 1
)

:has_cloudflared
echo [OK] Da co san cloudflared.exe.
echo.

:: 2. Tu dong bat backend server neu chua bat
echo [2/2] Khoi dong may chu Backend...
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:5000/api/info' -TimeoutSec 2; exit 0 } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo [THONG BAO] Dang bat Backend server trong cua so rieng...
    start "PrivacyShield Backend" cmd /c "cd /d "%~dp0backend" && python app.py"
    timeout /t 5 >nul
) else (
    echo [OK] Backend server da dang chay san sang!
)

echo.
echo ==============================================================================
echo   DANG KHOI TAO DUONG DAN TRUY CAP INTERNET...
echo   Hay tim dong chu: https://xxxx.trycloudflare.com o ben duoi.
echo   Do chinh la duong link de gui cho thay co va ban be truy cap!
echo ==============================================================================
echo.

cloudflared.exe tunnel --url http://localhost:5000

echo.
pause
