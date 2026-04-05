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
