import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cols = [r[1] for r in cur.execute("PRAGMA table_info(fornecedores_phc)").fetchall()]
if 'marcas' not in cols:
    cur.execute("ALTER TABLE fornecedores_phc ADD COLUMN marcas TEXT DEFAULT ''")
    print("OK: fornecedores_phc.marcas adicionado")
else:
    print("ok: marcas ja existe")
conn.commit(); conn.close()
print("Concluido.")
