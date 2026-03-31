@echo off
:: Instalar ComprasNet como servico Windows
:: Executar como Administrador!

echo ============================================
echo    ComprasNet - Instalar como Servico Windows
echo ============================================
echo.

:: Check admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERRO: Execute este script como Administrador!
    echo Clique direito no ficheiro -> "Executar como administrador"
    pause
    exit /b 1
)

set "DIR=%~dp0"
set "VENV=%DIR%venv\Scripts\python.exe"
set "APP=%DIR%app.py"
set "SVC_NAME=ComprasNet"
set "SVC_DISPLAY=ComprasNet - Gestao de Compras"
set "NSSM=%DIR%nssm.exe"

:: Download NSSM if not present
if not exist "%NSSM%" (
    echo A descarregar NSSM (gestor de servicos)...
    powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile '%DIR%nssm.zip'"
    powershell -Command "Expand-Archive -Path '%DIR%nssm.zip' -DestinationPath '%DIR%nssm_tmp' -Force"
    powershell -Command "Copy-Item '%DIR%nssm_tmp\nssm-2.24\win64\nssm.exe' '%NSSM%'"
    rmdir /s /q "%DIR%nssm_tmp"
    del "%DIR%nssm.zip"
    echo NSSM descarregado.
)

:: Remove existing service if present
"%NSSM%" status "%SVC_NAME%" >nul 2>&1
if %errorLevel% equ 0 (
    echo A remover servico existente...
    "%NSSM%" stop "%SVC_NAME%" >nul 2>&1
    "%NSSM%" remove "%SVC_NAME%" confirm >nul 2>&1
)

:: Install service
echo A instalar servico...
"%NSSM%" install "%SVC_NAME%" "%VENV%" "%APP%"
"%NSSM%" set "%SVC_NAME%" DisplayName "%SVC_DISPLAY%"
"%NSSM%" set "%SVC_NAME%" Description "ComprasNet - Sistema de Gestao de Compras com integracao PHC"
"%NSSM%" set "%SVC_NAME%" AppDirectory "%DIR%"
"%NSSM%" set "%SVC_NAME%" Start SERVICE_AUTO_START
"%NSSM%" set "%SVC_NAME%" AppStdout "%DIR%logs\comprasnet.log"
"%NSSM%" set "%SVC_NAME%" AppStderr "%DIR%logs\comprasnet_error.log"
"%NSSM%" set "%SVC_NAME%" AppRotateFiles 1
"%NSSM%" set "%SVC_NAME%" AppRotateBytes 1048576

:: Create logs folder
if not exist "%DIR%logs" mkdir "%DIR%logs"

:: Start service
echo A iniciar servico...
"%NSSM%" start "%SVC_NAME%"
timeout /t 3 /nobreak >nul

:: Check status
"%NSSM%" status "%SVC_NAME%"

echo.
echo ============================================
echo    Servico instalado com sucesso!
echo ============================================
echo.
echo O ComprasNet arranca automaticamente:
echo   - Quando o Windows iniciar
echo   - Se o servidor crashar (reinicio automatico)
echo.
echo Para gerir o servico:
echo   - Parar:    nssm stop ComprasNet
echo   - Iniciar:  nssm start ComprasNet
echo   - Remover:  instalar_servico.bat (corre o desinstalar)
echo.
echo Logs em: %DIR%logs\
echo.
pause
