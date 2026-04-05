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
