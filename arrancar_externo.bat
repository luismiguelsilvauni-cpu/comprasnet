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

REM Clear old tunnel log
if exist tunnel.log del tunnel.log

echo [1/2] A iniciar ComprasNet em http://localhost:5000 ...
start "ComprasNet Server" cmd /k "python app.py"
echo A aguardar servidor iniciar...
timeout /t 5 /nobreak > nul

echo [2/2] A iniciar Cloudflare Tunnel...
echo O URL publico aparecera abaixo em alguns segundos.
echo Fica disponivel em: http://localhost:5000/acesso-externo
echo.

cloudflared tunnel --url http://localhost:5000 2>&1 | powershell -NoProfile -Command "$input | ForEach-Object { $_ | Out-File -Append -FilePath 'tunnel.log' -Encoding utf8; Write-Host $_; if ($_ -match 'https://[a-z0-9-]+\.trycloudflare\.com') { $url = $matches[0]; Write-Host ''; Write-Host ('>>> URL ACTIVO: ' + $url) -ForegroundColor Green; Write-Host ''; try { $body = '{\"url\":\"' + $url + '\"}'; Invoke-RestMethod -Uri 'http://localhost:5000/api/tunnel/url' -Method POST -Body $body -ContentType 'application/json' -ErrorAction SilentlyContinue | Out-Null } catch {} } }"

pause
