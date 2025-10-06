@echo off
REM Setup script for PDF generation with Mermaid diagram support

echo === OptiMed PDF Generation Setup ===
echo.

echo Step 1: Installing Python dependencies...
pip install mkdocs-with-pdf pymdown-extensions pillow cairosvg

echo.
echo Step 2: Checking for Chrome/Chromium...
where chrome >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Chrome found!
    goto :pdf_test
)

where chromium >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ Chromium found!
    goto :pdf_test
)

echo ⚠️  Chrome/Chromium not found in PATH
echo.
echo To render Mermaid diagrams, you need Chrome or Chromium installed.
echo.
echo Option 1 - Install Chrome:
echo   Download from: https://www.google.com/chrome/
echo.
echo Option 2 - Install Chromium via Chocolatey:
echo   choco install chromium
echo.
echo Option 3 - Use Playwright (automatic):
echo   pip install playwright
echo   playwright install chromium
echo.

choice /C YN /M "Do you want to install Chromium via Playwright now"
if errorlevel 2 goto :pdf_test
if errorlevel 1 goto :install_playwright

:install_playwright
echo Installing Playwright and Chromium...
pip install playwright
playwright install chromium
echo ✅ Playwright Chromium installed!

:pdf_test
echo.
echo Step 3: Testing PDF generation...
set ENABLE_PDF_EXPORT=1
mkdocs build --clean

if exist pdf\optimed-documentation-complete.pdf (
    echo.
    echo ✅ SUCCESS! PDF generated successfully with Mermaid diagrams!
    echo 📄 Location: pdf\optimed-documentation-complete.pdf
    echo.
    echo Opening PDF preview...
    start pdf\optimed-documentation-complete.pdf
) else (
    echo.
    echo ❌ PDF generation failed. Check the error messages above.
    echo.
    echo Common issues:
    echo - Missing Chrome/Chromium: Install Chrome or run with Playwright
    echo - Mermaid syntax errors: Check your .md files
    echo - Plugin conflicts: Check mkdocs.yml
)

echo.
pause
