@echo off
:: Remover ComprasNet como servico Windows
:: Executar como Administrador!

echo ============================================
echo    ComprasNet - Remover Servico Windows
echo ============================================
echo.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERRO: Execute como Administrador!
    pause
    exit /b 1
)

set "DIR=%~dp0"
set "NSSM=%DIR%nssm.exe"
set "SVC_NAME=ComprasNet"

if not exist "%NSSM%" (
    echo NSSM nao encontrado. Servico pode nao estar instalado.
    pause
    exit /b 1
)

echo A parar servico...
"%NSSM%" stop "%SVC_NAME%" >nul 2>&1

echo A remover servico...
"%NSSM%" remove "%SVC_NAME%" confirm

echo.
echo Servico removido. O ComprasNet ja nao arranca automaticamente.
echo Para usar manualmente, execute iniciar.bat
echo.
pause
