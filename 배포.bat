@echo off
pushd "%~dp0"

where gh >nul 2>nul
if errorlevel 1 (
    echo ERROR: GitHub CLI(gh) 가 설치되어 있지 않습니다.
    echo https://cli.github.com 에서 설치 후 gh auth login 실행해 주세요.
    goto end
)

for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd.HHmm"') do set VER=%%a

echo [1/4] VERSION 업데이트 (v%VER%)...
python -c "import re; f=open('pdf_tool.py','r',encoding='utf-8'); c=f.read(); f.close(); c=re.sub(r\"VERSION\\s*=\\s*'[^']*'\",\"VERSION = '%VER%'\",c); f=open('pdf_tool.py','w',encoding='utf-8'); f.write(c); f.close()"

echo [2/4] Building EXE...
python -m PyInstaller pdf_tool.spec --clean --noconfirm
if errorlevel 1 goto err_build

echo [3/4] 소스 파일 GitHub 푸시...
git add pdf_tool.py pdf_tool.spec 빌드_EXE.bat 배포.bat
git commit -m "v%VER%"
git push origin main

echo [4/4] EXE 릴리즈 업로드...
gh release delete "v%VER%" --yes 2>nul
gh release create "v%VER%" "dist\PDF 편집기.exe" --title "PDF 편집기 v%VER%" --notes "자동 배포"
if errorlevel 1 goto err_upload

echo.
echo 완료!  v%VER%
goto end

:err_build
echo ERROR: 빌드 실패
goto end

:err_upload
echo ERROR: GitHub 업로드 실패 (gh auth login 으로 로그인 확인)

:end
popd
pause
