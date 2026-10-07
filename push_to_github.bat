@echo off
setlocal
echo ==============================================================================
echo   PrivacyShield — Ho tro day code len GitHub de Deploy Render / Railway
echo ==============================================================================
echo.

cd /d "%~dp0"

:: 1. Kiem tra Git
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git chua duoc cai dat tren may tinh!
    echo Vui long cai Git tai: https://git-scm.com/downloads
    pause
    exit /b 1
)

:: 2. Khoi tao Git repo neu chua co
if not exist ".git" (
    echo [1/4] Khoi tao Git repository...
    git init
    git branch -M main
) else (
    echo [1/4] Da co san Git repo.
)

:: 3. Them file va commit
echo.
echo [2/4] Dang chuan bi cac file ma nguon...
git add .
git commit -m "Deploy PrivacyShield: Anti-DreamBooth & JPEG-aware Web App" >nul 2>&1

:: 4. Hoi URL repo GitHub
echo.
echo [3/4] Ban can tao 1 repository moi tren GitHub (https://github.com/new).
echo       Chon loai "Public" va KHONG tich vao "Add README".
echo.
set /p REPO_URL="Dan duong link GitHub repo cua ban vao day (vi du: https://github.com/username/ten-repo.git): "

if "%REPO_URL%"=="" (
    echo [ERROR] Ban chua nhap duong link GitHub repo.
    pause
    exit /b 1
)

:: 5. Set remote va push
echo.
echo [4/4] Dang day code len GitHub...
git remote remove origin >nul 2>&1
git remote add origin %REPO_URL%
git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo ==============================================================================
    echo [THANH CONG!] Code da duoc day len GitHub thanh cong.
    echo Gio ban hay mo https://dashboard.render.com/ de lien ket repo va deploy!
    echo ==============================================================================
) else (
    echo.
    echo [CHU Y] Co the can xac thuc tai khoan GitHub (Personal Access Token hoac dang nhap).
)

echo.
pause
