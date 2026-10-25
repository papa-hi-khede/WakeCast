@echo off
rem Opens a normal Chrome window that the tweet button app can attach to.
rem Log in to X in this window once, then leave it open.

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not exist %CHROME% set CHROME="C:\Program Files\Microsoft\Edge\Application\msedge.exe"

start "" %CHROME% --remote-debugging-port=9222 --user-data-dir="%~dp0chrome_profile" https://x.com/login
