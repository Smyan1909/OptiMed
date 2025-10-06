@echo off
REM OptiMed PDF Generator - Simple method using Chrome
REM This method works on ANY Windows machine with Chrome installed

cd /d %~dp0..

echo.
echo Running PowerShell PDF generator...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0generate_pdf_simple.ps1"

pause
