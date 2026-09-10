@echo off
REM Double-click this file to start the scraper app.
REM It first clears any leftover server from a previous run (a common
REM problem: closing the window doesn't always stop the hidden Python
REM process, which then keeps serving the OLD page on port 5000), then
REM activates the local Python environment and launches a fresh server.

cd /d "%~dp0"

echo Stopping any leftover server from a previous run...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

call venv\Scripts\activate.bat

REM Make sure the headless browser Playwright needs is present. If it's
REM already installed this is near-instant; if it ever goes missing or
REM gets corrupted, this re-downloads it so scraping won't fail.
echo Checking the scraping browser is installed (first run may take a minute)...
python -m playwright install chromium

start "" http://localhost:5000
python app.py
pause
