import sys
sys.path.insert(0, '.')
from app import app, db
from sqlalchemy import text, inspect as sa_inspect

with app.app_context():
    uri = app.config.get('SQLALCHEMY_DATABASE_URI','')
    print("BD:", uri.replace('sqlite:///',''))
    
    db.create_all()
    
    insp = sa_inspect(db.engine)
    tbls = insp.get_table_names()
    
    # equipamento new columns
    if 'equipamento' in tbls:
        cols = [c['name'] for c in insp.get_columns('equipamento')]
        print("Colunas actuais:", cols)
        new_cols = [
            ('cliente_nome','TEXT'),('embarcacao','TEXT'),
            ('motor_modelo','TEXT'),('motor_potencia','TEXT'),
            ('caixa_modelo','TEXT'),('caixa_ratio','TEXT'),('caixa_serial','TEXT'),
        ]
        with db.engine.begin() as conn:
            for col, typ in new_cols:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}"))
                    print(f"OK: equipamento.{col} adicionado")
                else:
                    print(f"OK: {col} ja existe")
    
    # Create missing tables
    db.create_all()
    tbls2 = sa_inspect(db.engine).get_table_names()
    for t in ['equipamento','equipamento_opcao','equipamento_consumivel','backlog_item','changelog_entry']:
        print(f"{'OK' if t in tbls2 else 'MISSING'}: {t}")

print("Concluido. Reinicie o servidor.")
