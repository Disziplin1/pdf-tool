@echo off
pushd "%~dp0"

echo [1/4] git 초기화...
git init
git branch -M main

echo [2/4] GitHub 저장소 연결...
git remote remove origin 2>nul
git remote add origin https://github.com/Disziplin1/pdf-tool.git
gh repo create Disziplin1/pdf-tool --public --description "PDF 편집기" 2>nul

echo [3/4] 파일 업로드 준비...
git add pdf_tool.py pdf_tool.spec 빌드_EXE.bat 배포.bat .gitignore
git commit -m "초기 업로드"

echo [4/4] GitHub 에 푸시...
git push -u origin main

echo.
echo 완료! https://github.com/Disziplin1/pdf-tool
:end
popd
pause
