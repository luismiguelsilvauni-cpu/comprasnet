"""Diagnose recibo values in DB."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db

with app.app_context():
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    rows = cur.execute("SELECT * FROM recibo_salario ORDER BY id DESC LIMIT 3").fetchall()
    cols = [d[0] for d in cur.description]
    
    for r in rows:
        print(f"\n=== Recibo ID {r['id']} | Func {r['funcionario_id']} | {r['mes_label']} {r['ano']} ===")
        for col in cols:
            v = r[col]
            if col not in ('dados_json','pdf_filename','pdf_path','criado_em','atualizado_em'):
                print(f"  {col}: {repr(v)}")
    conn.close()
