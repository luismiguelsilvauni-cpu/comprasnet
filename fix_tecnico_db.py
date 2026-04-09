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
    tables = insp.get_table_names()
    
    # Add columns to equipamento if missing
    if 'equipamento' in tables:
        existing = [c['name'] for c in insp.get_columns('equipamento')]
        new_cols = [
            ('cliente_nome','TEXT'),('embarcacao','TEXT'),
            ('motor_modelo','TEXT'),('motor_potencia','TEXT'),
            ('caixa_modelo','TEXT'),('caixa_ratio','TEXT'),('caixa_serial','TEXT'),
        ]
        with db.engine.begin() as conn:
            for col, typ in new_cols:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}"))
                    print(f"OK: equipamento.{col} adicionado")
                else:
                    print(f"OK: {col} ja existe")

    # Add notas to backlog_item if missing
    if 'backlog_item' in tables:
        bl_cols = [c['name'] for c in insp.get_columns('backlog_item')]
        if 'notas' not in bl_cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE backlog_item ADD COLUMN notas TEXT DEFAULT ''"))
            print("OK: backlog_item.notas adicionado")

    # Check all required tables
    required = [
        'equipamento', 'equipamento_opcao', 'equipamento_consumivel',
        'equipamento_motor_aux', 'equipamento_documento',
        'changelog_entry', 'backlog_item',
        'factory_code_pdf', 'modelo_pdf',
    ]
    for tbl in required:
        if tbl in tables:
            print(f"OK: {tbl} existe")
        else:
            print(f"CRIADO: {tbl}")

    print("Concluido. Reinicie o servidor.")

    # Add tipo_motor to equipamento
    if 'equipamento' in insp.get_table_names():
        eq_cols = [c['name'] for c in insp.get_columns('equipamento')]
        if 'tipo_motor' not in eq_cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE equipamento ADD COLUMN tipo_motor TEXT DEFAULT 'principal'"))
            print("OK: equipamento.tipo_motor adicionado")
        else:
            print("OK: tipo_motor ja existe")
