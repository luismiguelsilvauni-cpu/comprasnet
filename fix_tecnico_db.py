import sys
sys.path.insert(0, '.')
from app import app, db
from sqlalchemy import text, inspect as sa_inspect

with app.app_context():
    db.create_all()
    insp = sa_inspect(db.engine)
    
    # Add new columns to equipamento
    existing = [c['name'] for c in insp.get_columns('equipamento')] if 'equipamento' in insp.get_table_names() else []
    print("Existing cols:", existing)
    
    new_cols = [
        ('cliente_nome', 'TEXT'), ('embarcacao', 'TEXT'),
        ('motor_modelo', 'TEXT'), ('motor_potencia', 'TEXT'),
        ('caixa_modelo', 'TEXT'), ('caixa_ratio', 'TEXT'), ('caixa_serial', 'TEXT'),
    ]
    
    with db.engine.connect() as conn:
        for col, typ in new_cols:
            if col not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}"))
                    conn.commit()
                    print(f"OK: {col} adicionado")
                except Exception as e:
                    print(f"Erro {col}: {e}")
            else:
                print(f"OK: {col} ja existe")
        
        db.create_all()
        conn.commit()

print("Concluido. Reinicie o servidor.")
