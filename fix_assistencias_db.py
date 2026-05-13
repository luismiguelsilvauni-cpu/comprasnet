import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS assistencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero INTEGER NOT NULL UNIQUE,
    requerente_nome VARCHAR(200) NOT NULL,
    requerente_nif VARCHAR(30) DEFAULT '',
    num_requisicao VARCHAR(100) DEFAULT '',
    local_obra VARCHAR(300) DEFAULT '',
    observacoes TEXT DEFAULT '',
    status VARCHAR(30) DEFAULT 'rececionado',
    data_rececionado DATE, data_em_execucao DATE,
    data_obra_concluida DATE, data_comunicado DATE, data_faturado DATE,
    dias_recepcao_conclusao INTEGER, dias_conclusao_faturado INTEGER,
    criado_por INTEGER, criado_em DATETIME, atualizado_em DATETIME)""")

cur.execute("""CREATE TABLE IF NOT EXISTS assistencia_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assist_id INTEGER NOT NULL,
    status_ant VARCHAR(30), status_novo VARCHAR(30) NOT NULL,
    data_real DATE, user_nome VARCHAR(120),
    notas VARCHAR(400) DEFAULT '', criado_em DATETIME)""")

cur.execute("""CREATE TABLE IF NOT EXISTS assistencia_documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assist_id INTEGER NOT NULL, tipo VARCHAR(20) DEFAULT 'documento',
    nome_original VARCHAR(255) NOT NULL, nome_ficheiro VARCHAR(255) NOT NULL,
    descricao VARCHAR(400) DEFAULT '', tamanho INTEGER DEFAULT 0,
    mime VARCHAR(100) DEFAULT '', criado_por INTEGER, criado_em DATETIME)""")

# Add new column if missing
cols = [r[1] for r in cur.execute("PRAGMA table_info(assistencias)").fetchall()]
if 'dias_conclusao_comunicado' not in cols:
    cur.execute("ALTER TABLE assistencias ADD COLUMN dias_conclusao_comunicado INTEGER")
    print("OK: dias_conclusao_comunicado added")
conn.commit()
conn.close()
print("OK: tabelas assistencias criadas")
