import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cols = [r[1] for r in cur.execute("PRAGMA table_info(linhas_pedido)").fetchall()]
if 'fornecedores_json' not in cols:
    cur.execute("ALTER TABLE linhas_pedido ADD COLUMN fornecedores_json TEXT DEFAULT '[]'")
    print("OK: linhas_pedido.fornecedores_json")
else:
    print("ok: ja existe")
conn.commit(); conn.close()
print("Concluido.")
