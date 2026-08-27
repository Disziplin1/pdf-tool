@echo off
chcp 65001 >nul
goto :main

:main
pushd "%~dp0"

where gh >nul 2>nul
if errorlevel 1 (
    echo ERROR: GitHub CLI 미설치.
    goto end
)

echo [1/8] 이전 실패한 배포의 잔재 정리...
python deploy_helper.py clean_stale_version
if errorlevel 1 goto err_dirty

echo [2/8] GitHub 최신 코드 받기...
git pull origin main
if errorlevel 1 goto err_pull

for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd.HHmm"') do set VER=%%a
echo 버전: v%VER%

echo [3/8] VERSION 업데이트...
python update_version.py %VER%
if errorlevel 1 goto err

echo [4/8] 실행기(launcher) 빌드...
taskkill /f /im "PDF 편집기.exe" >nul 2>nul
python -m PyInstaller launcher.spec --clean --noconfirm
if errorlevel 1 goto err_build

echo [5/8] 프로그램 빌드(onedir)...
python -m PyInstaller pdf_tool.spec --clean --noconfirm
if errorlevel 1 goto err_build

echo [6/8] 배포 패키지 생성...
python deploy_helper.py package %VER%
if errorlevel 1 goto err_build

echo [7/8] 소스 GitHub 푸시...
python deploy_helper.py git %VER%

echo [8/8] GitHub 릴리즈 업로드...
python deploy_helper.py release %VER%
if errorlevel 1 goto err_upload

echo.
echo 완료!  v%VER%
goto end

:err_dirty
echo ERROR: pdf_tool.py 에 VERSION 외의 미커밋 변경이 있습니다.
echo        실수로 지워지면 안 되는 작업 내용일 수 있으니, git diff pdf_tool.py 로
echo        직접 확인 후 커밋하거나 되돌린 다음 다시 실행하세요.
goto end

:err_pull
echo ERROR: git pull 실패 (충돌 등). 수동으로 확인 후 다시 실행하세요.
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
