@echo off
echo ============================================
echo    ComprasNet - Gestao de Orcamentos
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    echo Instale Python 3.10+ em https://python.org
    pause
    exit /b 1
)

REM Create venv if needed
if not exist "venv" (
    echo A criar ambiente virtual...
    python -m venv venv
)

call venv\Scripts\activate.bat

REM Install / update dependencies
echo A instalar dependencias...
pip install -r requirements.txt -q

REM Create uploads folder if missing
if not exist "uploads" mkdir uploads
if not exist "instance" mkdir instance

REM Claude API key (optional - configure in Admin > Provedor IA)
REM set ANTHROPIC_API_KEY=sk-ant-api03-...

echo.
echo A iniciar servidor...
echo.
echo  Acesso local  : http://localhost:5000
echo  Acesso na rede: http://%COMPUTERNAME%:5000
echo.
echo  Login: admin / admin123
echo  (altere a password apos o primeiro login)
echo.
echo  Prima CTRL+C para parar.
echo.

python app.py
pause
