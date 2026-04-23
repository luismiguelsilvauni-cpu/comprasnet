import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS ferias_periodos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL,
    ano INTEGER NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    tipo VARCHAR(20) DEFAULT 'ferias',
    notas VARCHAR(200) DEFAULT '',
    cor VARCHAR(7) DEFAULT '',
    criado_por INTEGER,
    criado_em DATETIME)""")

cur.execute("""CREATE TABLE IF NOT EXISTS ferias_feriados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ano INTEGER NOT NULL,
    data DATE NOT NULL UNIQUE,
    nome VARCHAR(100) NOT NULL,
    tipo VARCHAR(20) DEFAULT 'nacional')""")

cur.execute("""CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    last_seen DATETIME)""")

conn.commit()
conn.close()
print("OK: tabelas ferias e user_sessions criadas")
