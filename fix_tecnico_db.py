import sys
sys.path.insert(0, '.')
from app import app, db
from sqlalchemy import text, inspect as sa_inspect

with app.app_context():
    uri = app.config.get('SQLALCHEMY_DATABASE_URI','')
    print("BD:", uri)
    
    db.create_all()
    print("db.create_all() OK")
    
    insp = sa_inspect(db.engine)
    
    # Add columns to equipamento
    if 'equipamento' in insp.get_table_names():
        existing = [c['name'] for c in insp.get_columns('equipamento')]
        print("Colunas actuais:", existing)
        new_cols = [
            ('cliente_nome','TEXT'),('embarcacao','TEXT'),
            ('motor_modelo','TEXT'),('motor_potencia','TEXT'),
            ('caixa_modelo','TEXT'),('caixa_ratio','TEXT'),('caixa_serial','TEXT'),
        ]
        with db.engine.begin() as conn:
            for col, typ in new_cols:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}"))
                    print(f"OK: {col} adicionado")
                else:
                    print(f"OK: {col} ja existe")
    else:
        print("Tabela equipamento nao existe - a criar...")
        db.create_all()
    
    print("Concluido. Reinicie o servidor.")

    # Create equipamento_motor_aux table
    if 'equipamento_motor_aux' not in insp.get_table_names():
        db.create_all()
        print("OK: tabela equipamento_motor_aux criada")
    else:
        print("OK: equipamento_motor_aux ja existe")

    # Create equipamento_documento table
    if 'equipamento_documento' not in insp.get_table_names():
        db.create_all()
        print("OK: tabela equipamento_documento criada")
    else:
        print("OK: equipamento_documento ja existe")
