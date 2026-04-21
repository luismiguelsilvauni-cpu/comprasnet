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
    data_status DATETIME, data_status_real DATE, data_orcamento DATE,
    data_material_pedido DATE, data_em_reparacao DATE, data_faturado DATE,
    data_fecho DATE, dias_total INTEGER,
    dias_rec_faturado INTEGER, dias_mat_reparacao INTEGER, dias_reparacao_fat INTEGER,
    criado_por INTEGER, criado_em DATETIME, atualizado_em DATETIME)""")

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

# Add all missing columns in one pass
all_cols = {
    'entradas_equipamento': [
        ('data_status_real',   'DATE'),
        ('data_orcamento',     'DATE'),
        ('data_material_pedido','DATE'),
        ('data_em_reparacao',  'DATE'),
        ('data_faturado',      'DATE'),
        ('data_fecho',         'DATE'),
        ('dias_total',         'INTEGER'),
        ('dias_rec_orcamento',  'INTEGER'),
        ('dias_orc_reparacao',  'INTEGER'),
        ('dias_rec_faturado',  'INTEGER'),
        ('dias_mat_reparacao', 'INTEGER'),
        ('dias_reparacao_fat', 'INTEGER'),
    ],
    'entrada_historico': [
        ('data_real', 'DATE'),
    ],
}

for tbl, cols in all_cols.items():
    existing = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})").fetchall()]
    for col, typ in cols:
        if col not in existing:
            cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
            print(f"OK: {tbl}.{col} adicionado")
        else:
            print(f"ok: {tbl}.{col} já existe")

conn.commit()
conn.close()
print("\nConcluído.")
