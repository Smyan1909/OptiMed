@echo off
REM Generate PDF documentation for OptiMed (CLARA)
REM Windows batch script for PDF generation

echo === OptiMed Documentation PDF Generator ===
echo.

REM Check if mkdocs-with-pdf is installed
python -c "import mkdocs_with_pdf" 2>nul
if errorlevel 1 (
    echo Installing mkdocs-with-pdf...
    pip install mkdocs-with-pdf
)

REM Create PDF output directory
if not exist pdf mkdir pdf

echo Building complete documentation PDF...
set ENABLE_PDF_EXPORT=1
mkdocs build

echo.
echo ✅ PDF generated successfully!
echo 📄 Location: pdf\optimed-documentation-complete.pdf
echo.
echo You can find the PDF in the 'pdf' directory.
pause
