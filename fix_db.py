"""
fix_db.py — Corrige a BD directamente sem migrações
"""
import sqlite3, os

db_path = os.path.join('instance', 'compras.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Get existing columns
def get_cols(table):
    c.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in c.fetchall()]

fixes = 0

# config_phc.driver
if 'driver' not in get_cols('config_phc'):
    c.execute("ALTER TABLE config_phc ADD COLUMN driver VARCHAR(100) DEFAULT 'ODBC Driver 17 for SQL Server'")
    print("✅ config_phc.driver adicionado")
    fixes += 1
else:
    print("✅ config_phc.driver já existe")

# config_geral.dashboard_layouts
if 'dashboard_layouts' not in get_cols('config_geral'):
    c.execute("ALTER TABLE config_geral ADD COLUMN dashboard_layouts TEXT DEFAULT '{}'")
    print("✅ config_geral.dashboard_layouts adicionado")
    fixes += 1
else:
    print("✅ config_geral.dashboard_layouts já existe")

# Mark all migrations as done
c.execute("DELETE FROM alembic_version")
c.execute("INSERT INTO alembic_version VALUES ('0011')")
print("✅ Migrações marcadas como completas (head=0011)")

conn.commit()
conn.close()
print(f"\n✅ BD corrigida ({fixes} alterações). Reinicie o servidor.")
