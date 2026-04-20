import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

for tbl, col, typ in [
    ('funcionario',           'cc_validade',          'DATE'),
    ('funcionario',           'passaporte_validade',   'DATE'),
    ('funcionario_documento', 'data_validade',         'DATE'),
]:
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})").fetchall()]
    if col not in cols:
        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
        print(f"OK: {tbl}.{col}")
    else:
        print(f"já existe: {tbl}.{col}")

conn.commit()
conn.close()
print("Concluído.")
