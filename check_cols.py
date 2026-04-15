import sqlite3, os
db = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db)
cols = [r[1] for r in conn.execute("PRAGMA table_info(recibo_salario)").fetchall()]
print("Colunas recibo_salario:")
for c in cols:
    print(" ", c)
conn.close()
