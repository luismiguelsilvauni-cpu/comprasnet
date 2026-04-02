@echo off
echo ============================================
echo    ComprasNet - Gestao de Orcamentos
echo ============================================
echo.

REM Try to find Python in common locations
set PYTHON=
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
    goto :found_python
)
python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=python
    goto :found_python
)
py --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=py
    goto :found_python
)
if exist "C:\Python312\python.exe" set PYTHON=C:\Python312\python.exe
if exist "C:\Python311\python.exe" set PYTHON=C:\Python311\python.exe
if exist "C:\Python310\python.exe" set PYTHON=C:\Python310\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe
if defined PYTHON goto :found_python

echo ERRO: Python nao encontrado.
echo Instale Python 3.10+ em https://python.org
pause
exit /b 1

:found_python
echo Python encontrado: %PYTHON%

REM Create venv if needed
if not exist "venv" (
    echo A criar ambiente virtual...
    %PYTHON% -m venv venv
)

REM Use venv python
set PYTHON=venv\Scripts\python.exe

REM Install / update dependencies
echo A instalar dependencias...
venv\Scripts\pip.exe install -r requirements.txt -q

REM Create folders if missing
if not exist "uploads" mkdir uploads
if not exist "instance" mkdir instance

echo.
echo  Acesso local  : http://localhost:5000
echo  Acesso na rede: http://%COMPUTERNAME%:5000
echo.
echo  Login: admin / admin123
echo.
echo  Prima CTRL+C para parar.
echo.

REM Start SQL Server Express if not running
echo A verificar SQL Server Express...
sc query MSSQL$SQLEXPRESS | find "RUNNING" >nul 2>&1
if errorlevel 1 (
    echo A iniciar SQL Server Express...
    net start MSSQL$SQLEXPRESS >nul 2>&1
    if errorlevel 1 (
        echo AVISO: Nao foi possivel iniciar o SQL Server automaticamente.
        echo Execute manualmente: net start MSSQL$SQLEXPRESS
    ) else (
        echo SQL Server iniciado com sucesso.
        timeout /t 2 /nobreak >nul
    )
) else (
    echo SQL Server ja esta a correr.
)
echo.

venv\Scripts\python.exe app.py
pause
