src = open('app.py', 'rb').read().decode('utf-8')
idx = src.find('def pedidos()')
if idx > 0:
    print(repr(src[idx:idx+400]))
else:
    print("pedidos() not found")
    # Search for estado in routes
    for i,l in enumerate(src.splitlines()):
        if 'estado' in l and 'request' in l:
            print(f"L{i+1}: {l.strip()}")
