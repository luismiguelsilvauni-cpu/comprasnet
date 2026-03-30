@echo off
echo ============================================
echo    ComprasNet - Acesso Externo
echo    Cloudflare Tunnel
echo ============================================
echo.

REM Check cloudflared exists
if not exist "cloudflared.exe" (
    echo ERRO: cloudflared.exe nao encontrado.
    echo Descarregue em: https://github.com/cloudflare/cloudflared/releases/latest
    echo Copie o ficheiro cloudflared-windows-amd64.exe para esta pasta
    echo e renomeie para cloudflared.exe
    echo.
    pause
    exit /b 1
)

REM Activate venv and start ComprasNet in background
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo [1/2] A iniciar ComprasNet em http://localhost:5000 ...
start "ComprasNet Server" cmd /k "python app.py"

echo A aguardar servidor iniciar...
timeout /t 4 /nobreak > nul

echo [2/2] A iniciar Cloudflare Tunnel...
echo.
echo O URL publico aparecera abaixo em alguns segundos.
echo Partilhe esse URL com quem precisar de aceder externamente.
echo.
echo Para parar: feche esta janela (o servidor ComprasNet continua ativo).
echo.

cloudflared tunnel --url http://localhost:5000

pause
