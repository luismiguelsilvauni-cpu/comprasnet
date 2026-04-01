"""
health_check.py
───────────────
Startup agent that tests all core functions and auto-fixes common issues.
Run before starting the server, or on demand via /admin/health.
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

CHECKS = []
FIXES  = []


def check(name):
    """Decorator to register a health check."""
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


def fix(name):
    """Decorator to register an auto-fix."""
    def decorator(fn):
        FIXES.append((name, fn))
        return fn
    return decorator


# ── Checks ────────────────────────────────────────────────────────────────────

@check("Base de dados acessível")
def check_db(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return False, f"BD não encontrada em {db_path}"
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()
        size = os.path.getsize(db_path) // 1024
        return True, f"OK ({size} KB)"
    except Exception as e:
        return False, str(e)


@check("Tabelas da base de dados")
def check_tables(app):
    required = ['users', 'pedidos_compra', 'artigos_phc', 'config_ia',
                 'config_geral', 'clientes', 'embarcacoes', 'eventos_calendario']
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
            return False, f"Tabelas em falta: {', '.join(missing)}"
        return True, f"{len(existing)} tabelas OK"
    except Exception as e:
        return False, str(e)


@check("Colunas críticas da config_geral")
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
        needed = {'dashboard_layouts', 'empresa_logo_path', 'cor_accent', 'cor_bg', 'cor_surface'}
        missing = needed - cols
        if missing:
            return False, f"Colunas em falta: {', '.join(missing)}"
        return True, "Todas as colunas presentes"
    except Exception as e:
        return False, str(e)


@check("Utilizador admin")
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


@check("Pasta de uploads")
def check_uploads(app):
    path = app.config.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(app.root_path), path)
    if not os.path.exists(path):
        return False, f"Pasta não existe: {path}"
    return True, path


@check("Templates críticos")
def check_templates(app):
    templates = ['base.html', 'dashboard.html', 'login.html',
                 'pedidos.html', 'clientes.html', 'stock.html',
                 'admin_config.html', 'admin_ia.html']
    tdir = os.path.join(app.root_path, 'templates')
    missing = [t for t in templates if not os.path.exists(os.path.join(tdir, t))]
    if missing:
        return False, f"Templates em falta: {', '.join(missing)}"
    return True, f"{len(templates)} templates OK"


@check("ai_provider.py funcional")
def check_ai_provider(app):
    try:
        import ai_provider
        if not hasattr(ai_provider, '_get_best_gemini_model'):
            return False, "Função _get_best_gemini_model não encontrada — ficheiro desactualizado"
        if not hasattr(ai_provider, 'analyze_pdf'):
            return False, "Função analyze_pdf não encontrada"
        return True, "OK"
    except Exception as e:
        return False, str(e)


@check("backup_manager.py funcional")
def check_backup_manager(app):
    try:
        import backup_manager
        if not hasattr(backup_manager, 'fazer_backup'):
            return False, "Função fazer_backup não encontrada"
        return True, "OK"
    except Exception as e:
        return False, str(e)


@check("Actualizações do GitHub")
def check_github_updates(app):
    """Check if there are newer commits on GitHub."""
    import subprocess
    cwd = os.path.dirname(os.path.abspath(app.root_path + "/.."))
    cwd = app.root_path  # Use app root

    git_dir = os.path.join(cwd, '.git')
    if not os.path.exists(git_dir):
        return False, "Sem repositório Git — use o menu Actualizar Software"

    try:
        # Fetch silently
        r = subprocess.run(['git', 'fetch', 'origin', 'main', '--quiet'],
                          capture_output=True, text=True, timeout=15, cwd=cwd)
        if r.returncode != 0:
            return False, f"Sem acesso ao GitHub: {r.stderr[:80]}"

        # Compare
        local  = subprocess.run(['git', 'rev-parse', 'HEAD'],
                               capture_output=True, text=True, cwd=cwd).stdout.strip()
        remote = subprocess.run(['git', 'rev-parse', 'origin/main'],
                               capture_output=True, text=True, cwd=cwd).stdout.strip()

        if local == remote:
            return True, "Versão mais recente instalada ✅"
        
        # Count pending commits
        log = subprocess.run(['git', 'log', 'HEAD..origin/main', '--oneline'],
                            capture_output=True, text=True, cwd=cwd).stdout.strip()
        n = len([l for l in log.split('\n') if l])
        return False, f"{n} actualização(ões) disponível(eis) — vá a Actualizar Software"
    except Exception as e:
        return False, f"Erro: {e}"


@fix("Aplicar actualizações do GitHub")
def fix_github_updates(app):
    """Auto-apply updates if available."""
    import subprocess
    cwd = app.root_path

    git_dir = os.path.join(cwd, '.git')
    if not os.path.exists(git_dir):
        # Init git
        subprocess.run(['git', 'init'], cwd=cwd, capture_output=True)
        subprocess.run(['git', 'remote', 'add', 'origin',
                       'https://github.com/luismiguelsilvauni-cpu/comprasnet.git'],
                      cwd=cwd, capture_output=True)

    # Fetch
    r = subprocess.run(['git', 'fetch', 'origin', 'main', '--quiet'],
                       capture_output=True, text=True, timeout=20, cwd=cwd)
    if r.returncode != 0:
        return False, f"Sem acesso ao GitHub: {r.stderr[:80]}"

    # Check if updates needed
    local  = subprocess.run(['git', 'rev-parse', 'HEAD'],
                           capture_output=True, text=True, cwd=cwd).stdout.strip()
    remote = subprocess.run(['git', 'rev-parse', 'origin/main'],
                           capture_output=True, text=True, cwd=cwd).stdout.strip()

    if local == remote:
        return True, "Já na versão mais recente"

    # Apply updates
    r2 = subprocess.run(['git', 'checkout', 'origin/main', '--', '.'],
                        capture_output=True, text=True, timeout=30, cwd=cwd)
    if r2.returncode != 0:
        return False, f"Erro ao aplicar: {r2.stderr[:100]}"

    return True, f"✅ Actualizações aplicadas (local={local[:8]} → remoto={remote[:8]})"


# ── Auto-fixes ─────────────────────────────────────────────────────────────────

@fix("Criar pasta de uploads")
def fix_uploads(app):
    path = app.config.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(app.root_path), path)
    os.makedirs(path, exist_ok=True)
    return True, f"Pasta criada: {path}"


@fix("Adicionar colunas em falta à config_geral")
def fix_config_geral_columns(app):
    db_path = os.path.join(app.instance_path, 'compras.db')
    if not os.path.exists(db_path):
        return True, "BD não existe ainda — nada a fazer"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(config_geral)")
        existing = {r[1] for r in cursor.fetchall()}

        added = []
        cols_to_add = [
            ('dashboard_layouts', 'TEXT DEFAULT "{}"'),
            ('empresa_logo_path', 'VARCHAR(300)'),
            ('cor_accent',        "VARCHAR(7) DEFAULT '#3b6ef0'"),
            ('cor_bg',            "VARCHAR(7) DEFAULT '#0f1117'"),
            ('cor_surface',       "VARCHAR(7) DEFAULT '#171b25'"),
            ('backup_auto_ativo', 'BOOLEAN DEFAULT 1'),
            ('claude_chat_ativo', 'BOOLEAN DEFAULT 1'),
        ]
        for col, typ in cols_to_add:
            if col not in existing:
                cursor.execute(f"ALTER TABLE config_geral ADD COLUMN {col} {typ}")
                added.append(col)

        conn.commit()
        conn.close()
        if added:
            return True, f"Adicionadas: {', '.join(added)}"
        return True, "Sem colunas em falta"
    except Exception as e:
        return False, str(e)


@fix("Criar utilizador admin se não existir")
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


# ── Main runner ───────────────────────────────────────────────────────────────

def run_checks(app) -> list[dict]:
    """Run all checks and return results."""
    results = []
    for name, fn in CHECKS:
        try:
            ok, msg = fn(app)
        except Exception as e:
            ok, msg = False, f"Excepção: {e}"
        results.append({'check': name, 'ok': ok, 'msg': msg})
        level = logging.INFO if ok else logging.WARNING
        logger.log(level, f"{'✅' if ok else '❌'} {name}: {msg}")
    return results


def run_fixes(app) -> list[dict]:
    """Run all auto-fixes and return results."""
    results = []
    for name, fn in FIXES:
        try:
            ok, msg = fn(app)
        except Exception as e:
            ok, msg = False, f"Excepção: {e}"
        results.append({'fix': name, 'ok': ok, 'msg': msg})
        logger.info(f"🔧 Fix '{name}': {'OK' if ok else 'FALHOU'} — {msg}")
    return results


def startup_check(app, auto_fix=True) -> dict:
    """
    Run at startup: checks + optional auto-fixes.
    Returns summary dict.
    """
    logger.info("=" * 50)
    logger.info("ComprasNet — Health Check de arranque")
    logger.info("=" * 50)

    if auto_fix:
        logger.info("A aplicar correcções automáticas...")
        fix_results = run_fixes(app)
    else:
        fix_results = []

    logger.info("A verificar estado do sistema...")
    check_results = run_checks(app)

    errors   = [r for r in check_results if not r['ok']]
    warnings = []

    if errors:
        logger.warning(f"⚠️  {len(errors)} problema(s) detectado(s):")
        for e in errors:
            logger.warning(f"   • {e['check']}: {e['msg']}")
    else:
        logger.info("✅ Sistema OK — todos os checks passaram")

    logger.info("=" * 50)

    return {
        'ok':       len(errors) == 0,
        'checks':   check_results,
        'fixes':    fix_results,
        'errors':   errors,
        'warnings': warnings,
        'timestamp': datetime.utcnow().isoformat(),
    }
