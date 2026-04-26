import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# equipamento table
eq_cols = [r[1] for r in cur.execute("PRAGMA table_info(equipamento)").fetchall()]
for col, typ in [
    ('motor_marca', 'VARCHAR(100)'),
    ('catalogo',    'VARCHAR(100)'),
    ('base_code',   'VARCHAR(100)'),
]:
    if col not in eq_cols:
        cur.execute(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}")
        print(f"OK: equipamento.{col}")
    else:
        print(f"ok: {col} ja existe")

# componentes_embarcacao table
ce_cols = [r[1] for r in cur.execute("PRAGMA table_info(componentes_embarcacao)").fetchall()]
for col, typ in [
    ('potencia',  'VARCHAR(50)'),
    ('catalogo',  'VARCHAR(100)'),
    ('base_code', 'VARCHAR(100)'),
]:
    if col not in ce_cols:
        cur.execute(f"ALTER TABLE componentes_embarcacao ADD COLUMN {col} {typ}")
        print(f"OK: componentes_embarcacao.{col}")
    else:
        print(f"ok: {col} ja existe")

conn.commit()
conn.close()
print("Concluido.")
