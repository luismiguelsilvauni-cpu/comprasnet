import sys
sys.path.insert(0, '.')
from app import app, db
from sqlalchemy import text, inspect as sa_inspect

with app.app_context():
    insp = sa_inspect(db.engine)
    eq_cols = [c['name'] for c in insp.get_columns('equipamento')]
    print("Colunas actuais:", eq_cols)
    
    new_cols = [
        ('manufacturing_date', 'TEXT'),
        ('base_engine_pt', 'TEXT'),
        ('base_engine_eng', 'TEXT'),
        ('fuel_system_pt', 'TEXT'),
        ('fuel_system_eng', 'TEXT'),
        ('material', 'TEXT'),
    ]
    with db.engine.begin() as conn:
        for col, typ in new_cols:
            if col not in eq_cols:
                conn.execute(text(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}"))
                print(f"CRIADO: {col}")
            else:
                print(f"OK: {col} ja existe")
    print("Concluido.")
