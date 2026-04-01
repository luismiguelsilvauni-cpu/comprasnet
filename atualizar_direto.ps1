# atualizar_direto.ps1
# Descarrega os ficheiros mais recentes directamente do GitHub
# Sem precisar de git pull nem resolver conflitos

$base = "https://raw.githubusercontent.com/luismiguelsilvauni-cpu/comprasnet/main"
$dest = $PSScriptRoot

$ficheiros = @(
    "app.py",
    "ai_provider.py",
    "backup_manager.py",
    "models.py",
    "alias_matcher.py",
    "arrancar_externo.bat",
    "instalar_servico.bat",
    "remover_servico.bat",
    "templates/base.html",
    "templates/admin_config.html",
    "templates/admin_ia.html",
    "templates/admin_update.html",
    "templates/acesso_externo.html",
    "templates/changelog.html",
    "templates/chat_claude.html",
    "templates/clientes.html",
    "templates/cliente_detalhe.html",
    "templates/cliente_form.html",
    "templates/embarcacao_detalhe.html",
    "templates/embarcacao_form.html",
    "templates/pendentes.html",
    "templates/reposicao.html",
    "templates/pedido_detalhe.html",
    "templates/pedidos.html",
    "templates/comparacao.html",
    "templates/dashboard.html",
    "templates/mobile/base.html",
    "templates/mobile/home.html",
    "templates/mobile/artigos.html",
    "templates/mobile/artigo_detalhe.html",
    "templates/mobile/pedidos.html",
    "templates/mobile/clientes.html",
    "templates/mobile/cliente_detalhe.html",
    "templates/mobile/chat.html",
    "migrations/versions/0007_gemini_api_fields.py",
    "migrations/versions/0008_notas_artigo.py",
    "migrations/versions/0009_dashboard_layouts.py",
    "migrations/versions/0010_evento_calendario.py",
    "health_check.py",
    "templates/admin_health.html",
    "templates/stock.html",
    "templates/stock_artigo.html"
)

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   ComprasNet - Actualizacao Directa" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$ok = 0
$err = 0

foreach ($f in $ficheiros) {
    $url     = "$base/$f"
    $destino = Join-Path $dest $f
    $pasta   = Split-Path $destino -Parent

    if (-not (Test-Path $pasta)) {
        New-Item -ItemType Directory -Path $pasta -Force | Out-Null
    }

    try {
        Invoke-WebRequest -Uri $url -OutFile $destino -ErrorAction Stop
        Write-Host "  OK  $f" -ForegroundColor Green
        $ok++
    } catch {
        Write-Host "  ERRO $f : $_" -ForegroundColor Red
        $err++
    }
}

Write-Host ""
Write-Host "Resultado: $ok ficheiros actualizados, $err erros" -ForegroundColor Cyan
Write-Host ""

if ($err -eq 0) {
    Write-Host "A executar migracoes da base de dados..." -ForegroundColor Yellow
    & "$dest\venv\Scripts\python.exe" -m flask db upgrade 2>&1 | ForEach-Object { Write-Host "  $_" }
    Write-Host ""
    Write-Host "Actualizacao concluida!" -ForegroundColor Green
    Write-Host "Execute iniciar.bat para reiniciar o servidor." -ForegroundColor Yellow
} else {
    Write-Host "Alguns ficheiros falharam. Verifique a ligacao a internet." -ForegroundColor Red
}

Write-Host ""
Read-Host "Prima Enter para sair"
