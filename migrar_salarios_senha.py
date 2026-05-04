"""Run this once to add salarios_senha column."""
import sqlite3, os, glob

# Find the database
candidates = [
    'instance/compras.db',
    '../instance/compras.db',
]
db_path = None
for c in candidates:
    if os.path.exists(c):
        db_path = c
        break

if not db_path:
    found = glob.glob('**/compras.db', recursive=True)
    if found: db_path = found[0]

if db_path:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE config_geral ADD COLUMN salarios_senha VARCHAR(50)")
        conn.commit()
        print(f"Column added to {db_path}")
    except Exception as e:
        print(f"Already exists or error: {e}")
    conn.close()
else:
    print("Database not found")
