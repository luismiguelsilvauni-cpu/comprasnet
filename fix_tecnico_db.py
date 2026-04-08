
    # Create equipamento_documento table
    if 'equipamento_documento' not in insp.get_table_names():
        db.create_all()
        print("OK: tabela equipamento_documento criada")
    else:
        print("OK: equipamento_documento ja existe")

    # Create factory_code_pdf table
    if 'factory_code_pdf' not in insp.get_table_names():
        db.create_all()
        print("OK: tabela factory_code_pdf criada")
    else:
        print("OK: factory_code_pdf ja existe")

    # Create modelo_pdf table
    if 'modelo_pdf' not in insp.get_table_names():
        db.create_all()
        print("OK: tabela modelo_pdf criada")
    else:
        print("OK: modelo_pdf ja existe")
