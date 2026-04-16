"""Create entradas tables directly."""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(__file__))

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS entradas_equipamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero INTEGER NOT NULL UNIQUE,
    data_rececao DATE NOT NULL,
    cliente_nome VARCHAR(200) NOT NULL,
    marca VARCHAR(100),
    modelo VARCHAR(100),
    num_serie VARCHAR(100),
    observacoes TEXT DEFAULT '',
    status VARCHAR(50) DEFAULT 'rececionado',
    data_status DATETIME,
    criado_por INTEGER REFERENCES users(id),
    criado_em DATETIME,
    atualizado_em DATETIME
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS entrada_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entrada_id INTEGER NOT NULL REFERENCES entradas_equipamento(id),
    status_ant VARCHAR(50),
    status_novo VARCHAR(50) NOT NULL,
    user_id INTEGER REFERENCES users(id),
    user_nome VARCHAR(120),
    notas VARCHAR(400) DEFAULT '',
    criado_em DATETIME
)
""")

conn.commit()
conn.close()
print("OK: tabelas entradas_equipamento e entrada_historico criadas")
