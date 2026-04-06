src = open('app.py', 'rb').read().decode('utf-8')

# Find the pedidos route and show context
idx = src.find('def pedidos()')
if idx > 0:
    print("Pedidos route found:")
    print(src[idx:idx+300])
else:
    # Try finding estado filter
    idx2 = src.find('estado_filtro')
    if idx2 > 0:
        print("estado_filtro found at:", idx2)
        print(src[max(0,idx2-200):idx2+200])
    else:
        print("Not found - searching for 'estado'...")
        for i, line in enumerate(src.splitlines()):
            if 'estado' in line and ('request.args' in line or 'filtro' in line.lower()):
                print(f"Line {i+1}: {line.strip()}")
