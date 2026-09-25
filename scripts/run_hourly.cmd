@echo off
rem Task Scheduler launcher: fixes the working directory (so .env and the DB resolve)
rem and calls uv by full path, since scheduled tasks do not see the user's PATH.
cd /d "%~dp0.."
"%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe" run python -m jobscout.hourly
