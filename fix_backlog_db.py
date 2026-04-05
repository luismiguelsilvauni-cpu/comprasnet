import sqlite3, os

# Flask usa instance/compras.db com sqlite:///
paths = ['instance/compras.db', 'compras.db']
db_path = None
for p in paths:
    if os.path.exists(p):
        db_path = p
        break

if not db_path:
    print("ERRO: BD nao encontrada em", paths)
    exit(1)

print("BD encontrada:", db_path)
conn = sqlite3.connect(db_path)
conn.execute("""CREATE TABLE IF NOT EXISTS backlog_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descricao TEXT DEFAULT '',
    tipo TEXT DEFAULT 'medium',
    estado TEXT DEFAULT 'pending',
    prioridade INTEGER DEFAULT 10,
    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()
n = conn.execute('SELECT COUNT(*) FROM backlog_item').fetchone()[0]
print('OK. Items na BD:', n)
conn.close()
