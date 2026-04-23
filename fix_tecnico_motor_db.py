import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

for col, typ in [
    ('motor_marca', 'VARCHAR(100)'),
    ('catalogo',    'VARCHAR(100)'),
]:
    cols = [r[1] for r in cur.execute("PRAGMA table_info(equipamento)").fetchall()]
    if col not in cols:
        cur.execute(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}")
        print(f"OK: equipamento.{col}")
    else:
        print(f"ok: {col} já existe")

# componentes_embarcacao
for col, typ in [
    ('potencia',  'VARCHAR(50)'),
    ('catalogo',  'VARCHAR(100)'),
    ('base_code', 'VARCHAR(100)'),
]:
    cols = [r[1] for r in cur.execute("PRAGMA table_info(componentes_embarcacao)").fetchall()]
    if col not in cols:
        cur.execute(f"ALTER TABLE componentes_embarcacao ADD COLUMN {col} {typ}")
        print(f"OK: componentes_embarcacao.{col}")
    else:
        print(f"ok: {col} já existe")

# embarcacoes
cols = [r[1] for r in cur.execute("PRAGMA table_info(embarcacoes)").fetchall()]
if 'foto_path' not in cols:
    cur.execute("ALTER TABLE embarcacoes ADD COLUMN foto_path VARCHAR(300)")
    print("OK: embarcacoes.foto_path")

conn.commit()
conn.close()
print("Concluído.")
