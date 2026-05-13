src = open('app.py', 'rb').read().decode('utf-8')

old = "estado = request.args.get('estado','')"
new = "estado = request.args.get('estado','aberto')"

if old in src:
    src = src.replace(old, new)
    open('app.py', 'wb').write(src.encode('utf-8'))
    print("FIXED: pedidos default=aberto")
else:
    print("ERROR: padrao nao encontrado")
    # Show all estado lines
    for i,l in enumerate(src.splitlines()):
        if 'estado' in l and 'request' in l:
            print(f"L{i+1}: {repr(l.strip())}")
