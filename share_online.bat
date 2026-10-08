@echo off
setlocal
echo ==============================================================================
echo   PrivacyShield — Tao Duong Dan Public Online (Cloudflare Tunnel)
echo   Ho tro chia se web app cho thay co, ban be truy cap qua Internet / 4G
echo ==============================================================================
echo.

cd /d "%~dp0"

if not exist "cloudflared.exe" (
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
    echo [OK] Tai thanh cong cloudflared.exe!
) else (
    echo [OK] Da co san cloudflared.exe.
)

:: 2. Kiem tra xem backend localhost:5000 co dang chay khong
echo.
echo [2/2] Kiem tra server local http://localhost:5000...
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:5000/api/info' -TimeoutSec 2; exit 0 } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo [THONG BAO] Server backend chua bat. Dang tu dong khoi dong backend...
    start /min "" cmd /c "%~dp0run.bat"
    timeout /t 5 >nul
)

echo.
echo ==============================================================================
echo   DANG KHOI TAO DUONG DAN TRUY CAP INTERNET...
echo   Hay tim dong chu: https://xxxx.trycloudflare.com o ben duoi.
echo   Do chinh la duong link de gui cho nguoi khac truy cap!
echo ==============================================================================
echo.

cloudflared.exe tunnel --url http://localhost:5000

pause
