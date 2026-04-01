"""
health_check.py
───────────────
Startup agent that tests ALL ComprasNet functions and auto-fixes issues.
Runs at startup and on demand via /admin/health.
"""

import os
import sys
import json
import sqlite3
import logging
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

CHECKS = []
FIXES  = []


def check(name, category="Sistema"):
    def decorator(fn):
        CHECKS.append((name, category, fn))
        return fn
    return decorator


def fix(name):
    def decorator(fn):
        FIXES.append((name, fn))
        return fn
    return decorator


# ══════════════════════════════════════════════════════════════
#  CATEGORIA: BASE DE DADOS
# ══════════════════════════════════════════════════════════════

@check("Base de dados acessível", "Base de Dados")
def check_db(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return False, f"BD não encontrada em {db_path}"
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()
        size = os.path.getsize(db_path) // 1024
        return True, f"{size} KB"
    except Exception as e:
        return False, str(e)


@check("Tabelas obrigatórias", "Base de Dados")
def check_tables(app):
    required = ['users', 'pedidos_compra', 'linhas_pedido', 'orcamentos',
                 'items_orcamento', 'artigos_phc', 'aliases_artigo',
                 'config_ia', 'config_geral', 'clientes', 'embarcacoes',
                 'componentes_embarcacao', 'pending_matches', 'notas_artigo',
                 'eventos_calendario', 'config_reposicao']
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return False, "BD não encontrada"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing = {r[0] for r in cursor.fetchall()}
        conn.close()
        missing = [t for t in required if t not in existing]
        if missing:
            return False, f"Em falta: {', '.join(missing)}"
        return True, f"{len(existing)} tabelas presentes"
    except Exception as e:
        return False, str(e)


@check("Colunas da config_geral", "Base de Dados")
def check_config_geral_columns(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return True, "BD não existe ainda"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(config_geral)")
        cols = {r[1] for r in cursor.fetchall()}
        conn.close()
        needed = {'dashboard_layouts', 'empresa_logo_path', 'cor_accent',
                  'cor_bg', 'cor_surface', 'backup_auto_ativo', 'claude_chat_ativo'}
        missing = needed - cols
        if missing:
            return False, f"Colunas em falta: {', '.join(missing)}"
        return True, "Todas as colunas presentes"
    except Exception as e:
        return False, str(e)


@check("Utilizador admin existe", "Base de Dados")
def check_admin(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return True, "BD não existe ainda"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
        count = cursor.fetchone()[0]
        conn.close()
        if count == 0:
            return False, "Sem utilizadores admin"
        return True, f"{count} admin(s)"
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════
#  CATEGORIA: FICHEIROS
# ══════════════════════════════════════════════════════════════

@check("Pasta de uploads", "Ficheiros")
def check_uploads(app):
    path = app.config.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.isabs(path):
        path = os.path.join(app.root_path, path)
    if not os.path.exists(path):
        return False, f"Pasta não existe: {path}"
    return True, path


@check("Templates críticos", "Ficheiros")
def check_templates(app):
    templates = [
        'base.html', 'dashboard.html', 'login.html',
        'pedidos.html', 'pedido_detalhe.html', 'clientes.html',
        'cliente_detalhe.html', 'stock.html', 'stock_artigo.html',
        'admin_config.html', 'admin_ia.html', 'admin_update.html',
        'admin_health.html', 'changelog.html', 'chat_claude.html',
        'pendentes.html', 'reposicao.html', 'acesso_externo.html',
        'mobile/base.html', 'mobile/home.html', 'mobile/artigos.html',
    ]
    tdir = os.path.join(app.root_path, 'templates')
    missing = [t for t in templates if not os.path.exists(os.path.join(tdir, t))]
    if missing:
        return False, f"Em falta: {', '.join(missing)}"
    return True, f"{len(templates)} templates OK"


@check("Módulos Python críticos", "Ficheiros")
def check_modules(app):
    modules = ['ai_provider', 'alias_matcher', 'backup_manager',
               'health_check', 'reposicao', 'phc_sync']
    missing = []
    for m in modules:
        path = os.path.join(app.root_path, f'{m}.py')
        if not os.path.exists(path):
            missing.append(m)
    if missing:
        return False, f"Em falta: {', '.join(missing)}"
    return True, f"{len(modules)} módulos OK"


@check("ai_provider.py actualizado", "Ficheiros")
def check_ai_provider(app):
    try:
        import ai_provider
        fns = ['_get_best_gemini_model', 'analyze_pdf', 'test_provider', '_call_gemini']
        missing = [f for f in fns if not hasattr(ai_provider, f)]
        if missing:
            return False, f"Funções em falta: {', '.join(missing)} — execute atualizar_direto.ps1"
        return True, "OK"
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════
#  CATEGORIA: ROTAS WEB
# ══════════════════════════════════════════════════════════════

def _test_route(app, route, method='GET', data=None, login=True):
    """Helper to test a route."""
    with app.test_client() as c:
        if login:
            c.post('/login', data={'username': 'admin', 'password': 'admin123'})
        if method == 'GET':
            r = c.get(route, follow_redirects=True)
        else:
            r = c.post(route, json=data or {}, follow_redirects=True)
        return r.status_code


@check("Dashboard", "Rotas")
def check_route_dashboard(app):
    try:
        code = _test_route(app, '/')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Pedidos de Compra", "Rotas")
def check_route_pedidos(app):
    try:
        code = _test_route(app, '/pedidos')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Clientes", "Rotas")
def check_route_clientes(app):
    try:
        code = _test_route(app, '/clientes')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Stock", "Rotas")
def check_route_stock(app):
    try:
        code = _test_route(app, '/stock')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Reposição de Stock", "Rotas")
def check_route_reposicao(app):
    try:
        code = _test_route(app, '/reposicao')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Associações Pendentes", "Rotas")
def check_route_pendentes(app):
    try:
        code = _test_route(app, '/pendentes')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Chat IA", "Rotas")
def check_route_chat(app):
    try:
        code = _test_route(app, '/chat')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Admin — Configurações", "Rotas")
def check_route_admin_config(app):
    try:
        code = _test_route(app, '/admin/config')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Admin — Provedor IA", "Rotas")
def check_route_admin_ia(app):
    try:
        code = _test_route(app, '/admin/ia')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("Admin — Actualizar Software", "Rotas")
def check_route_admin_update(app):
    try:
        code = _test_route(app, '/admin/update')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("App Mobile", "Rotas")
def check_route_mobile(app):
    try:
        code = _test_route(app, '/mobile')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("API Artigos PHC", "Rotas")
def check_api_artigos(app):
    try:
        code = _test_route(app, '/api/artigos?q=teste')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("API Calendário", "Rotas")
def check_api_calendario(app):
    try:
        code = _test_route(app, '/api/calendario/eventos?ano=2026&mes=1')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("API Dashboard Layout", "Rotas")
def check_api_dashboard(app):
    try:
        code = _test_route(app, '/api/dashboard/layout')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


@check("API Pendentes Count", "Rotas")
def check_api_pendentes(app):
    try:
        code = _test_route(app, '/api/pendentes/count')
        return code == 200, f"HTTP {code}"
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════
#  CATEGORIA: INTEGRAÇÕES
# ══════════════════════════════════════════════════════════════

@check("Configuração de IA", "Integrações")
def check_ia_config(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return False, "BD não existe"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT provider, gemini_api_key, claude_api_key, lm_host FROM config_ia LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return False, "Sem configuração de IA — configure em Admin → Provedor IA"
        provider = row[0]
        if provider == 'gemini' and not row[1]:
            return False, "Gemini seleccionado mas sem chave API"
        if provider == 'claude' and not row[2]:
            return False, "Claude seleccionado mas sem chave API"
        if provider in ('lmstudio', 'ollama'):
            return True, f"Provedor: {provider} em {row[3]} (verificação de ligação não automática)"
        return True, f"Provedor: {provider} — chave API configurada ✅"
    except Exception as e:
        return False, str(e)


@check("PHC CS — Ligação", "Integrações")
def check_phc(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return False, "BD não existe"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT ultima_sync, servidor FROM config_phc LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row or not row[0]:
            return False, "PHC não sincronizado — configure em Admin → PHC CS"
        artigos = sqlite3.connect(db_path).execute(
            "SELECT COUNT(*) FROM artigos_phc").fetchone()[0]
        return True, f"Última sync: {row[0][:10]} — {artigos} artigos"
    except Exception as e:
        return False, f"PHC não configurado ({e.__class__.__name__})"


@check("Backup automático", "Integrações")
def check_backup(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return True, "BD não existe ainda"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT backup_auto_ativo, backup_local_path, ultimo_backup FROM config_geral LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return False, "Config geral não encontrada"
        ativo = row[0]
        path  = row[1] or 'backups'
        ultimo = row[2]
        if not ativo:
            return False, "Backup automático desactivado — active em Admin → Configurações"
        msg = f"Activo — pasta: {path}"
        if ultimo:
            msg += f" — último: {ultimo[:10]}"
        return True, msg
    except Exception as e:
        return False, str(e)


@check("Actualizações do GitHub", "Integrações")
def check_github_updates(app):
    cwd = app.root_path
    git_dir = os.path.join(cwd, '.git')
    if not os.path.exists(git_dir):
        return False, "Sem repositório Git — use o menu Actualizar Software"
    try:
        r = subprocess.run(['git', 'fetch', 'origin', 'main', '--quiet'],
                          capture_output=True, text=True, timeout=15, cwd=cwd)
        if r.returncode != 0:
            return False, f"Sem acesso ao GitHub"
        local  = subprocess.run(['git', 'rev-parse', 'HEAD'],
                               capture_output=True, text=True, cwd=cwd).stdout.strip()
        remote = subprocess.run(['git', 'rev-parse', 'origin/main'],
                               capture_output=True, text=True, cwd=cwd).stdout.strip()
        if local == remote:
            return True, f"Versão actual: {local[:8]} ✅"
        log = subprocess.run(['git', 'log', 'HEAD..origin/main', '--oneline'],
                            capture_output=True, text=True, cwd=cwd).stdout.strip()
        n = len([l for l in log.split('\n') if l])
        return False, f"{n} actualização(ões) disponível(eis)"
    except Exception as e:
        return False, f"Erro: {e}"


# ══════════════════════════════════════════════════════════════
#  AUTO-FIXES
# ══════════════════════════════════════════════════════════════

@fix("Criar pasta de uploads")
def fix_uploads(app):
    path = app.config.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.isabs(path):
        path = os.path.join(app.root_path, path)
    os.makedirs(path, exist_ok=True)
    return True, f"OK: {path}"


@fix("Adicionar colunas em falta à config_geral")
def fix_config_geral_columns(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return True, "BD não existe ainda"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(config_geral)")
        existing = {r[1] for r in cursor.fetchall()}
        added = []
        cols = [
            ('dashboard_layouts', "TEXT DEFAULT '{}'"),
            ('empresa_logo_path', 'VARCHAR(300)'),
            ('cor_accent',        "VARCHAR(7) DEFAULT '#3b6ef0'"),
            ('cor_bg',            "VARCHAR(7) DEFAULT '#0f1117'"),
            ('cor_surface',       "VARCHAR(7) DEFAULT '#171b25'"),
            ('backup_auto_ativo', 'BOOLEAN DEFAULT 1'),
            ('claude_chat_ativo', 'BOOLEAN DEFAULT 1'),
            ('claude_chat_sistema', 'TEXT'),
        ]
        for col, typ in cols:
            if col not in existing:
                cursor.execute(f"ALTER TABLE config_geral ADD COLUMN {col} {typ}")
                added.append(col)
        conn.commit()
        conn.close()
        return True, f"Adicionadas: {', '.join(added)}" if added else "Sem colunas em falta"
    except Exception as e:
        return False, str(e)


@fix("Criar utilizador admin se necessário")
def fix_admin_user(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return True, "BD não existe ainda"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
        if cursor.fetchone()[0] == 0:
            from werkzeug.security import generate_password_hash
            cursor.execute(
                "INSERT INTO users (username, password_hash, nome, is_admin) VALUES (?,?,?,?)",
                ('admin', generate_password_hash('admin123'), 'Administrador', 1)
            )
            conn.commit()
            conn.close()
            return True, "Admin criado (admin/admin123)"
        conn.close()
        return True, "Admin já existe"
    except Exception as e:
        return False, str(e)


@fix("Aplicar actualizações do GitHub")
def fix_github_updates(app):
    cwd = app.root_path
    git_dir = os.path.join(cwd, '.git')
    if not os.path.exists(git_dir):
        subprocess.run(['git', 'init'], cwd=cwd, capture_output=True)
        subprocess.run(['git', 'remote', 'add', 'origin',
                       'https://github.com/luismiguelsilvauni-cpu/comprasnet.git'],
                      cwd=cwd, capture_output=True)
    r = subprocess.run(['git', 'fetch', 'origin', 'main', '--quiet'],
                       capture_output=True, text=True, timeout=20, cwd=cwd)
    if r.returncode != 0:
        return False, f"Sem acesso ao GitHub"
    local  = subprocess.run(['git', 'rev-parse', 'HEAD'],
                           capture_output=True, text=True, cwd=cwd).stdout.strip()
    remote = subprocess.run(['git', 'rev-parse', 'origin/main'],
                           capture_output=True, text=True, cwd=cwd).stdout.strip()
    if local == remote:
        return True, "Já na versão mais recente"
    r2 = subprocess.run(['git', 'checkout', 'origin/main', '--', '.'],
                        capture_output=True, text=True, timeout=30, cwd=cwd)
    if r2.returncode != 0:
        return False, f"Erro: {r2.stderr[:100]}"
    return True, f"✅ Actualizado ({local[:8]} → {remote[:8]})"


# ══════════════════════════════════════════════════════════════
#  RUNNER
# ══════════════════════════════════════════════════════════════

def run_checks(app) -> list[dict]:
    results = []
    for name, category, fn in CHECKS:
        try:
            ok, msg = fn(app)
        except Exception as e:
            ok, msg = False, f"Excepção: {e}"
        results.append({'check': name, 'category': category, 'ok': ok, 'msg': msg})
        logger.log(logging.INFO if ok else logging.WARNING,
                   f"{'✅' if ok else '❌'} [{category}] {name}: {msg}")
    return results


def run_fixes(app) -> list[dict]:
    results = []
    for name, fn in FIXES:
        try:
            ok, msg = fn(app)
        except Exception as e:
            ok, msg = False, f"Excepção: {e}"
        results.append({'fix': name, 'ok': ok, 'msg': msg})
        logger.info(f"🔧 {name}: {'OK' if ok else 'FALHOU'} — {msg}")
    return results


def startup_check(app, auto_fix=True) -> dict:
    logger.info("=" * 55)
    logger.info("ComprasNet — Health Check")
    logger.info("=" * 55)
    fix_results = run_fixes(app) if auto_fix else []
    check_results = run_checks(app)
    errors = [r for r in check_results if not r['ok']]
    if errors:
        logger.warning(f"⚠️  {len(errors)} problema(s):")
        for e in errors:
            logger.warning(f"   • [{e['category']}] {e['check']}: {e['msg']}")
    else:
        logger.info("✅ Sistema OK")
    logger.info("=" * 55)
    return {
        'ok':        len(errors) == 0,
        'checks':    check_results,
        'fixes':     fix_results,
        'errors':    errors,
        'timestamp': datetime.utcnow().isoformat(),
    }
