@echo off
echo ============================================
echo    ComprasNet - Acesso Externo
echo    Cloudflare Tunnel
echo ============================================
echo.

if not exist "cloudflared.exe" (
    echo ERRO: cloudflared.exe nao encontrado.
    echo Descarregue em:
    echo https://github.com/cloudflare/cloudflared/releases/download/2026.3.0/cloudflared-windows-amd64.exe
    echo Copie para esta pasta e renomeie para cloudflared.exe
    pause
    exit /b 1
)

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo [1/2] A iniciar ComprasNet em http://localhost:5000 ...
start "ComprasNet Server" cmd /k "python app.py"
echo A aguardar servidor iniciar...
timeout /t 5 /nobreak > nul

echo [2/2] A iniciar Cloudflare Tunnel...
echo.
echo O URL publico aparecera abaixo em alguns segundos.
echo Copie o URL e partilhe com quem precisar de aceder remotamente.
echo Esse URL tambem fica disponivel em: http://localhost:5000/acesso-externo
echo.
echo Prima CTRL+C para parar o tunnel (o servidor ComprasNet continua ativo).
echo.

REM Start cloudflared and capture output to detect URL
cloudflared tunnel --url http://localhost:5000 2>&1 | powershell -Command "$input | ForEach-Object { Write-Host $_; if ($_ -match 'https://[a-z0-9\-]+\.trycloudflare\.com') { $url = $matches[0]; try { Invoke-RestMethod -Uri 'http://localhost:5000/api/tunnel/url' -Method POST -Body ('{\"url\":\"' + $url + '\"}') -ContentType 'application/json' -ErrorAction SilentlyContinue } catch {} } }"

pause
