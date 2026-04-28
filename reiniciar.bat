@echo off
echo A parar servidor antigo...
taskkill /f /im python.exe 2>nul
taskkill /f /im waitress-serve.exe 2>nul
timeout /t 2 /nobreak >nul
echo A actualizar codigo...
git pull origin main
echo A iniciar servidor...
call .\venv\Scripts\activate
python run.py
