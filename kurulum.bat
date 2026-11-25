@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Yorum Kanali kurulumu ===
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python bulunamadi. Once python.org'dan Python 3.12 kur ve kurulumda
  echo "Add python.exe to PATH" kutusunu isaretle. Sonra bu dosyayi tekrar calistir.
  pause
  exit /b
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo ffmpeg kuruluyor...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  echo ffmpeg kuruldu. Bu pencereyi kapatip kurulum.bat'i bir kez daha calistir.
  pause
  exit /b
)
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.ornek .env >nul
echo.
echo Kurulum bitti. Simdi acilan Not Defteri'nde anahtarlarini yapistir ve kaydet.
notepad .env
echo Sonra demo.bat ile test videosu uret, baslat.bat ile botu ac.
pause
