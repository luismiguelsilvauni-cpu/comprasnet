# Verifica e corrige pedidos default=aberto
src = open('app.py', 'rb').read().decode('utf-8')
idx = src.find('def pedidos()')
print("Current code:", repr(src[idx:idx+120]))

if "'estado',''" in src or '"estado",""' in src:
    src = src.replace("get('estado','')", "get('estado','aberto')")
    src = src.replace('get("estado","")', "get('estado','aberto')")
    # Also fix the filter
    src = src.replace(
        "if estado: q = q.filter_by(estado=estado)",
        "if estado and estado != 'todos': q = q.filter_by(estado=estado)"
    )
    open('app.py', 'wb').write(src.encode('utf-8'))
    print("FIXED")
elif "'estado','aberto'" in src:
    print("ALREADY FIXED")
else:
    print("PATTERN NOT FOUND - manual check needed")
    for i,l in enumerate(src.splitlines()[125:135], 126):
        print(f"L{i}: {l}")
