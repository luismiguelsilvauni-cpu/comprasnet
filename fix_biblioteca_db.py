"""
fix_biblioteca_db.py
Adiciona colunas 'marca' e 'outras_referencias' à tabela modelo_pdf.
Executar uma vez após git pull:
    .\venv\Scripts\python.exe fix_biblioteca_db.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app, db
from sqlalchemy import text, inspect as sa_inspect

with app.app_context():
    insp = sa_inspect(db.engine)
    if 'modelo_pdf' not in insp.get_table_names():
        db.create_all()
        print("Tabela modelo_pdf criada.")
    else:
        existing = [c['name'] for c in insp.get_columns('modelo_pdf')]
        with db.engine.begin() as conn:
            for col, typ in [('marca', 'VARCHAR(150)'), ('outras_referencias', 'VARCHAR(500)')]:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE modelo_pdf ADD COLUMN {col} {typ}"))
                    print(f"  ✅ Coluna '{col}' adicionada.")
                else:
                    print(f"  ✓  Coluna '{col}' já existe.")
    print("Concluído. Reinicie o servidor.")
