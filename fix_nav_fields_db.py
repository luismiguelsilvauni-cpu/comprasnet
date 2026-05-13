import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# FornecedorPHC NAV fields
forn_cols = [r[1] for r in cur.execute("PRAGMA table_info(fornecedores_phc)").fetchall()]
for col, typ in [
    ('nav_telefone', 'VARCHAR(50)'),
    ('nav_email',    'VARCHAR(150)'),
    ('nav_morada',   'VARCHAR(300)'),
    ('nav_notas',    'TEXT'),
]:
    if col not in forn_cols:
        cur.execute(f"ALTER TABLE fornecedores_phc ADD COLUMN {col} {typ} DEFAULT ''")
        print(f"OK: fornecedores_phc.{col}")
    else:
        print(f"ok: {col} ja existe")

# Cliente NAV fields
cli_cols = [r[1] for r in cur.execute("PRAGMA table_info(clientes)").fetchall()]
for col, typ in [
    ('nav_telefone', 'VARCHAR(50)'),
    ('nav_email',    'VARCHAR(150)'),
    ('nav_notas',    'TEXT'),
]:
    if col not in cli_cols:
        cur.execute(f"ALTER TABLE clientes ADD COLUMN {col} {typ} DEFAULT ''")
        print(f"OK: clientes.{col}")
    else:
        print(f"ok: {col} ja existe")

conn.commit()
conn.close()
print("Concluido.")
