@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check paramiko
.venv\Scripts\python.exe sunucuya_gonder.py kayit
pause
