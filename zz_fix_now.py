src = open('app.py', 'rb').read().decode('utf-8')
old = "estado = request.args.get('estado','')"
new = "estado = request.args.get('estado','aberto')"
if old in src:
    open('app.py', 'wb').write(src.replace(old, new).encode('utf-8'))
    print("OK: pedidos=aberto")
else:
    print("NAO ENCONTRADO:", repr(old))
