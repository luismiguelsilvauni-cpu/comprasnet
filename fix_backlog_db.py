import sqlite3
conn = sqlite3.connect('compras.db')
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
print('OK. Items:', n)
conn.close()
