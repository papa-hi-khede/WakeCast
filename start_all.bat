@echo off
rem Starts everything: Chrome (for X), the WakeCast server, and the alarm page.
rem Keep this file in the SAME folder as tweet_server.py, tweet_button.py,
rem start_chrome.bat, tweets.txt and alarm_snooze.html.

cd /d "%~dp0"

rem 1) Open Chrome with the debug port (log in to X in it once, then leave it open)
call start_chrome.bat

rem 2) Give Chrome a few seconds to start
timeout /t 5 /nobreak >nul

rem 3) Start the server. It also opens the alarm page in your default browser.
rem    Keep this window open.
python tweet_server.py

pause
