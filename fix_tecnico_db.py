
    # Create equipamento_documento table
    if 'equipamento_documento' not in insp.get_table_names():
        db.create_all()
        print("OK: tabela equipamento_documento criada")
    else:
        print("OK: equipamento_documento ja existe")
