@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto kurulum_yok
echo Hazirlaniyor...
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check paramiko
if errorlevel 1 goto hata
.venv\Scripts\python.exe sunucuya_gonder.py
echo.
pause
exit /b 0

:kurulum_yok
echo Once kurulum.bat calistirilmali. Bu dosyayi yorum-kanali klasorunde calistir.
pause
exit /b 1

:hata
echo.
echo Bir sorun cikti. Bu pencerenin ekran goruntusunu gonder.
pause
exit /b 1
