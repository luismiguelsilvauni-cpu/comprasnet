"""Migration completa para tabelas de entradas."""
import sqlite3, os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Create tables if missing
cur.execute("""CREATE TABLE IF NOT EXISTS entradas_equipamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero INTEGER NOT NULL UNIQUE,
    data_rececao DATE NOT NULL,
    cliente_nome VARCHAR(200) NOT NULL,
    marca VARCHAR(100), modelo VARCHAR(100), num_serie VARCHAR(100),
    observacoes TEXT DEFAULT '', status VARCHAR(50) DEFAULT 'rececionado',
    data_status DATETIME, criado_por INTEGER, criado_em DATETIME, atualizado_em DATETIME)""")

cur.execute("""CREATE TABLE IF NOT EXISTS entrada_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entrada_id INTEGER NOT NULL, status_ant VARCHAR(50),
    status_novo VARCHAR(50) NOT NULL, user_id INTEGER,
    user_nome VARCHAR(120), notas VARCHAR(400) DEFAULT '',
    data_real DATE, criado_em DATETIME)""")

cur.execute("""CREATE TABLE IF NOT EXISTS entrada_documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entrada_id INTEGER NOT NULL, nome_original VARCHAR(255) NOT NULL,
    nome_ficheiro VARCHAR(255) NOT NULL, descricao VARCHAR(300) DEFAULT '',
    tamanho INTEGER DEFAULT 0, mime VARCHAR(100) DEFAULT '',
    criado_por INTEGER, criado_em DATETIME)""")

# ALL columns that should exist
COLS = [
    ('data_status_real',        'DATE'),
    ('data_orcamento',          'DATE'),
    ('data_pre_orcamento',      'DATE'),
    ('data_material_pedido',    'DATE'),
    ('data_material_stock',     'DATE'),
    ('data_em_reparacao',       'DATE'),
    ('data_reparacao_concluida','DATE'),
    ('data_faturado',           'DATE'),
    ('data_fecho',              'DATE'),
    ('dias_total',              'INTEGER'),
    ('dias_rec_orcamento',      'INTEGER'),
    ('dias_rec_faturado',       'INTEGER'),
    ('dias_orc_reparacao',      'INTEGER'),
    ('dias_mat_reparacao',      'INTEGER'),
    ('dias_mat_stock',          'INTEGER'),
    ('dias_stock_reparacao',    'INTEGER'),
    ('dias_reparacao_concluida','INTEGER'),
    ('dias_reparacao_fat',      'INTEGER'),
    ('marca_grupo',             'VARCHAR(100)'),
    ('modelo_grupo',            'VARCHAR(100)'),
    ('num_serie_grupo',         'VARCHAR(100)'),
]

existing = [r[1] for r in cur.execute("PRAGMA table_info(entradas_equipamento)").fetchall()]
for col, typ in COLS:
    if col not in existing:
        cur.execute(f"ALTER TABLE entradas_equipamento ADD COLUMN {col} {typ}")
        print(f"OK: adicionado {col}")
    else:
        print(f"ok: {col} ja existe")

# entrada_historico
hist_cols = [r[1] for r in cur.execute("PRAGMA table_info(entrada_historico)").fetchall()]
if 'data_real' not in hist_cols:
    cur.execute("ALTER TABLE entrada_historico ADD COLUMN data_real DATE")
    print("OK: entrada_historico.data_real")

conn.commit()
conn.close()
print("\nConcluido.")
