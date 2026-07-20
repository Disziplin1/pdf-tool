@echo off
pushd "%~dp0"

where gh >nul 2>nul
if errorlevel 1 (
    echo ERROR: GitHub CLI 미설치.
    goto end
)

for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd.HHmm"') do set VER=%%a
echo 버전: v%VER%

echo [1/4] VERSION 업데이트...
python update_version.py %VER%
if errorlevel 1 goto err

echo [2/4] Building EXE...
taskkill /f /im "PDF 편집기.exe" >nul 2>nul
python -m PyInstaller pdf_tool.spec --clean --noconfirm
if errorlevel 1 goto err_build

echo [3/4] 소스 GitHub 푸시...
python deploy_helper.py git %VER%

echo [4/4] EXE 릴리즈 업로드...
python deploy_helper.py release %VER%
if errorlevel 1 goto err_upload

echo.
echo 완료!  v%VER%
goto end

:err
echo ERROR: VERSION 업데이트 실패
goto end

:err_build
echo ERROR: 빌드 실패
goto end

:err_upload
echo ERROR: GitHub 업로드 실패

:end
popd
pause
