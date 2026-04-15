import sqlite3, os

db = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
print(f"BD: {db}")
print(f"Existe: {os.path.exists(db)}")

conn = sqlite3.connect(db)
cur = conn.cursor()

# Check columns exist
cols = [r[1] for r in cur.execute("PRAGMA table_info(recibo_salario)").fetchall()]
print(f"\nColunas: {[c for c in cols if 'irs' in c]}")

# Update directly
cur.execute("UPDATE recibo_salario SET irs_parcela_abater=530.52, irs_taxa_efetiva=0.1792 WHERE id=1")
print(f"Rows affected: {cur.rowcount}")
conn.commit()

# Verify immediately
r = cur.execute("SELECT id, irs_parcela_abater, irs_taxa_efetiva FROM recibo_salario WHERE id=1").fetchone()
print(f"After update: {r}")
conn.close()
