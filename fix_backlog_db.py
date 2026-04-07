import sys, os
sys.path.insert(0, '.')

from app import app, db

with app.app_context():
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    print("BD encontrada:", uri.replace('sqlite:///', ''))
    
    db.create_all()
    
    from sqlalchemy import text, inspect
    insp = inspect(db.engine)
    cols = [c['name'] for c in insp.get_columns('backlog_item')]
    print("Colunas actuais:", cols)
    
    with db.engine.connect() as conn:
        if 'notas' not in cols:
            conn.execute(text("ALTER TABLE backlog_item ADD COLUMN notas TEXT DEFAULT ''"))
            conn.commit()
            print("OK: coluna notas adicionada")
        else:
            print("OK: notas ja existe")
        
        n = conn.execute(text("SELECT COUNT(*) FROM backlog_item")).fetchone()[0]
        print("Total items:", n)
    
    # Create changelog_entry table
    if 'changelog_entry' not in insp.get_table_names():
        conn.execute(text("""CREATE TABLE IF NOT EXISTS changelog_entry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            versao TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            tipo TEXT DEFAULT 'feat',
            commit_msg TEXT DEFAULT '',
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )"""))
        conn.commit()
        print("OK: tabela changelog_entry criada")
    else:
        print("OK: changelog_entry ja existe")

    # Add new columns to equipamento if missing
    eq_cols = [c['name'] for c in insp.get_columns('equipamento')] if 'equipamento' in insp.get_table_names() else []
    new_cols = [
        ('cliente_nome', 'TEXT'), ('embarcacao', 'TEXT'), ('motor_modelo', 'TEXT'),
        ('motor_potencia', 'TEXT'), ('caixa_modelo', 'TEXT'), ('caixa_ratio', 'TEXT'), ('caixa_serial', 'TEXT'),
    ]
    for col, typ in new_cols:
        if col not in eq_cols:
            try:
                conn.execute(text(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}"))
                conn.commit()
                print(f"OK: equipamento.{col} adicionado")
            except Exception as e:
                print(f"equipamento.{col}: {e}")
