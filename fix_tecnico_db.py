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

    # Populate ModeloPDF library from existing EquipamentoDocumento records
    try:
        docs = db.session.execute(text("""
            SELECT ed.id, ed.componente, ed.titulo, ed.pdf_filename, ed.pdf_path,
                   e.caixa_modelo, e.motor_modelo
            FROM equipamento_documento ed
            JOIN equipamento e ON e.id = ed.equipamento_id
        """)).fetchall()
        added_lib = 0
        for d in docs:
            comp, titulo, fname, fpath, caixa_m, motor_m = d[1], d[2], d[3], d[4], d[5], d[6]
            tipo_comp = None
            modelo_val = None
            if comp == 'caixa' and caixa_m:
                tipo_comp, modelo_val = 'caixa', caixa_m.strip()
            elif comp == 'motor' and motor_m:
                tipo_comp, modelo_val = 'motor', motor_m.strip()
            if tipo_comp and modelo_val and titulo and fpath:
                exists = db.session.execute(text(
                    "SELECT id FROM modelo_pdf WHERE tipo_componente=:t AND modelo_codigo=:m AND titulo=:ti"
                ), {'t': tipo_comp, 'm': modelo_val, 'ti': titulo}).fetchone()
                if not exists:
                    db.session.execute(text(
                        "INSERT INTO modelo_pdf (tipo_componente, modelo_codigo, titulo, pdf_filename, pdf_path, criado_em) VALUES (:t,:m,:ti,:fn,:fp, datetime('now'))"
                    ), {'t': tipo_comp, 'm': modelo_val, 'ti': titulo, 'fn': fname, 'fp': fpath})
                    added_lib += 1
        db.session.commit()
        if added_lib:
            print(f"OK: {added_lib} documentos existentes adicionados à biblioteca partilhada")
        else:
            print("OK: biblioteca partilhada ja actualizada")
    except Exception as ex:
        print(f"Biblioteca: {ex}")

    # Add thumb_path to modelo_pdf
    if 'modelo_pdf' in insp.get_table_names():
        mp_cols = [c['name'] for c in insp.get_columns('modelo_pdf')]
        if 'thumb_path' not in mp_cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE modelo_pdf ADD COLUMN thumb_path TEXT"))
            print("OK: modelo_pdf.thumb_path adicionado")

    # Add ativo column to equipamento
    if 'equipamento' in insp.get_table_names():
        eq_cols = [c['name'] for c in insp.get_columns('equipamento')]
        if 'ativo' not in eq_cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE equipamento ADD COLUMN ativo BOOLEAN DEFAULT 1"))
            print("OK: equipamento.ativo adicionado")
        else:
            print("OK: ativo ja existe")

    # Add new motor fields to equipamento
    if 'equipamento' in insp.get_table_names():
        eq_cols = [c['name'] for c in insp.get_columns('equipamento')]
        new_cols = [
            ('manufacturing_date', 'TEXT'),
            ('base_engine_pt', 'TEXT'),
            ('base_engine_eng', 'TEXT'),
            ('fuel_system_pt', 'TEXT'),
            ('fuel_system_eng', 'TEXT'),
        ]
        with db.engine.begin() as conn:
            for col, typ in new_cols:
                if col not in eq_cols:
                    conn.execute(text(f"ALTER TABLE equipamento ADD COLUMN {col} {typ}"))
                    print(f"OK: equipamento.{col} adicionado")

    # Create campo_tecnico_modelo table
    if 'campo_tecnico_modelo' not in insp.get_table_names():
        db.create_all()
        print("OK: tabela campo_tecnico_modelo criada")
    else:
        print("OK: campo_tecnico_modelo ja existe")

    # Add pdf fields to campo_tecnico_modelo
    if 'campo_tecnico_modelo' in insp.get_table_names():
        ct_cols = [c['name'] for c in insp.get_columns('campo_tecnico_modelo')]
        for col in ['pdf_filename', 'pdf_path']:
            if col not in ct_cols:
                with db.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE campo_tecnico_modelo ADD COLUMN {col} TEXT"))
                print(f"OK: campo_tecnico_modelo.{col} adicionado")

    # Add catalogo to equipamento
    if 'equipamento' in insp.get_table_names():
        eq_cols = [c['name'] for c in insp.get_columns('equipamento')]
        if 'catalogo' not in eq_cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE equipamento ADD COLUMN catalogo TEXT"))
            print("OK: equipamento.catalogo adicionado")
        else:
            print("OK: catalogo ja existe")
