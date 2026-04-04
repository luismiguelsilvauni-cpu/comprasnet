"""fix_db.py - Corrige BD e app.py sem necessidade de migrações"""
import sqlite3, os, re

# ── Fix BD ────────────────────────────────────────────────────
db_path = os.path.join('instance', 'compras.db')
if not os.path.exists(db_path):
    print("❌ BD não encontrada em instance/compras.db")
else:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    def get_cols(table):
        try:
            c.execute(f"PRAGMA table_info({table})")
            return [r[1] for r in c.fetchall()]
        except:
            return []

    all_cols = [
        ('config_phc',   'driver',               "VARCHAR(100) DEFAULT 'ODBC Driver 17 for SQL Server'"),
        ('config_geral', 'dashboard_layouts',    "TEXT DEFAULT '{}'"),
        ('config_geral', 'empresa_logo_path',    'VARCHAR(300)'),
        ('config_geral', 'cor_accent',           "VARCHAR(7) DEFAULT '#3b6ef0'"),
        ('config_geral', 'cor_bg',               "VARCHAR(7) DEFAULT '#0f1117'"),
        ('config_geral', 'cor_surface',          "VARCHAR(7) DEFAULT '#171b25'"),
        ('config_geral', 'backup_auto_ativo',    'BOOLEAN DEFAULT 1'),
        ('config_geral', 'claude_chat_ativo',    'BOOLEAN DEFAULT 1'),
        ('config_geral', 'claude_chat_sistema',  'TEXT'),
        ('config_geral', 'logo_altura',          'INTEGER DEFAULT 48'),
        ('config_geral', 'logo_largura',         'INTEGER DEFAULT 180'),
        ('config_geral', 'logo_filtro',          "VARCHAR(100) DEFAULT ''"),
        ('artigos_phc',  'pvp',                  'REAL DEFAULT 0'),
        ('artigos_phc',  'ultimo_preco_entrada', 'REAL DEFAULT 0'),
        ('config_reposicao', 'min_anos_historico',         'FLOAT DEFAULT 2.0'),
        ('config_reposicao', 'min_meses_com_venda',        'INTEGER DEFAULT 3'),
        ('config_reposicao', 'min_total_vendido',          'FLOAT DEFAULT 3.0'),
        ('config_reposicao', 'ignorar_sem_movimento_anos', 'FLOAT DEFAULT 3.0'),
        ('config_reposicao', 'min_facturas_sugerir',       'INTEGER DEFAULT 8'),
    ]

    fixed = 0
    for table, col, typ in all_cols:
        existing = get_cols(table)
        if existing and col not in existing:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                print(f"✅ {table}.{col} adicionado")
                fixed += 1
            except Exception as e:
                print(f"⚠️  {table}.{col}: {e}")
        elif col in existing:
            pass  # already exists

    conn.commit()
    c.execute("DELETE FROM alembic_version")
    c.execute("INSERT INTO alembic_version VALUES ('0014')")
    conn.commit()
    conn.close()
    print(f"✅ BD corrigida ({fixed} colunas novas). Versão: 0013")

# ── Fix app.py ────────────────────────────────────────────────
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        src = f.read()

    fixes = 0

    # Fix session import
    if 'send_from_directory, session' not in src and 'send_from_directory' in src:
        src = src.replace(
            'from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory',
            'from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session'
        )
        fixes += 1
        print("✅ session importado")

    # Remove before_request session
    bad = '@app.before_request\ndef make_session_permanent():\n    session.permanent = True\n\n'
    if bad in src:
        src = src.replace(bad, '')
        fixes += 1
        print("✅ before_request removido")

    # Fix logger in ensure_sqlserver_running
    for old, new in [
        ('            logger.info("✅ SQL Server já está a correr")',   '            print("SQL Server a correr")'),
        ('            logger.info("🔄 A iniciar SQL Server Express...")', '            print("A iniciar SQL Server...")'),
        ('                logger.info("✅ SQL Server iniciado com sucesso")', '                print("SQL Server iniciado")'),
        ('                logger.warning(f"⚠️  Não foi possível iniciar SQL Server: {start.stdout}")', '                print(f"Aviso SQL: {start.stdout}")'),
        ('        logger.warning(f"⚠️  Erro ao verificar SQL Server: {e}")', '        print(f"Erro SQL: {e}")'),
    ]:
        if old in src:
            src = src.replace(old, new)
            fixes += 1

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"✅ app.py corrigido ({fixes} alterações)")
except Exception as e:
    print(f"⚠️  Erro ao corrigir app.py: {e}")

print("\n✅ Concluído. Reinicie o servidor com: .\\iniciar.bat")
