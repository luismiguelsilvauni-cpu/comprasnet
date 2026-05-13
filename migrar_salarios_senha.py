import sqlite3, os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'compras.db')
print(f"DB: {db_path}")
conn = sqlite3.connect(db_path)
try:
    conn.execute("ALTER TABLE config_geral ADD COLUMN salarios_senha VARCHAR(50)")
    conn.commit()
    print("Column salarios_senha added OK")
except Exception as e:
    print(f"Note: {e}")
row = conn.execute("SELECT id, salarios_senha FROM config_geral LIMIT 1").fetchone()
print(f"Current value: {row}")
conn.close()
