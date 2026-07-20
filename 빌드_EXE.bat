@echo off
pushd "%~dp0"
if errorlevel 1 goto err_unc

echo.
echo [1/3] Installing PyInstaller...
python -m pip install pyinstaller --upgrade -q
if errorlevel 1 goto err_pip

echo [2/3] Building EXE...
python -m PyInstaller pdf_tool.spec --clean --noconfirm
if errorlevel 1 goto err_build

echo.
echo [3/3] Done!
echo.
if exist "dist\PDF 편집기.exe" (
    echo dist\PDF 편집기.exe
    start explorer dist
) else (
    echo EXE file not found.
)
goto end

:err_unc
echo ERROR: network path mapping failed
goto end

:err_pip
echo ERROR: pip install failed.
goto end

:err_build
echo.
echo ERROR: Build failed. Check messages above.
echo Tip: Temporarily disable antivirus and retry.

:end
popd
pause