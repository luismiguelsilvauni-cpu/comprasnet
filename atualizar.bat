@echo off
echo ============================================
echo    ComprasNet - Atualizacao de Versao
echo ============================================
echo.
echo Este script atualiza o ComprasNet preservando
echo todos os dados existentes (pedidos, orcamentos, etc.)
echo.

REM Activate venv
if not exist "venv\Scripts\activate.bat" (
    echo ERRO: Ambiente virtual nao encontrado.
    echo Execute primeiro o iniciar.bat para configurar.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

REM ── 1. Backup da base de dados ──────────────────────────────────────────────
echo [1/4] A fazer backup da base de dados...
set BACKUP_DATE=%date:~6,4%-%date:~3,2%-%date:~0,2%_%time:~0,2%-%time:~3,2%
set BACKUP_DATE=%BACKUP_DATE: =0%
set BACKUP_FILE=backups\compras_backup_%BACKUP_DATE%.db

if not exist "backups" mkdir backups

if exist "instance\compras.db" (
    copy "instance\compras.db" "%BACKUP_FILE%" >nul
    echo    Backup guardado em: %BACKUP_FILE%
) else (
    echo    (Sem base de dados existente - instalacao nova)
)

REM ── 2. Instalar/atualizar dependencias ──────────────────────────────────────
echo [2/4] A atualizar dependencias Python...
pip install -r requirements.txt -q --upgrade
if errorlevel 1 (
    echo ERRO nas dependencias. A restaurar backup...
    goto :restore
)

REM ── 3. Migrar a base de dados ───────────────────────────────────────────────
echo [3/4] A migrar base de dados (preserva todos os dados)...
flask db upgrade
if errorlevel 1 (
    echo ERRO na migracao. A restaurar backup...
    goto :restore
)
echo    Migracao concluida com sucesso.

REM ── 4. Iniciar servidor ─────────────────────────────────────────────────────
echo [4/4] A iniciar servidor...
echo.
echo ============================================
echo    Atualizacao concluida com sucesso!
echo    Backup guardado em: %BACKUP_FILE%
echo ============================================
echo.
echo A iniciar ComprasNet em http://0.0.0.0:5000
echo Prima CTRL+C para parar o servidor.
echo.
python app.py
goto :end

:restore
echo.
echo ============================================
echo    ERRO NA ATUALIZACAO
echo ============================================
if exist "%BACKUP_FILE%" (
    echo A restaurar base de dados anterior...
    copy "%BACKUP_FILE%" "instance\compras.db" >nul
    echo Base de dados restaurada. Os dados estao seguros.
) else (
    echo Nenhum backup disponivel para restaurar.
)
echo.
echo Contacte o suporte com o erro acima.
pause
exit /b 1

:end
pause
