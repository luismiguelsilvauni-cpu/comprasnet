src = open('app.py', 'rb').read().decode('utf-8')

old = "key=lambda x: x['stock'] / (i['vendido_12m']/12) if i['vendido_12m'] > 0 else 0,"
new = "key=lambda x: (x['stock'] / (x['vendido_12m']/12)) if x['vendido_12m'] > 0 else 0,"

if old in src:
    src = src.replace(old, new)
    open('app.py', 'wb').write(src.encode('utf-8'))
    print("FIXED: lambda bug")
else:
    print("Not found - searching...")
    for i,l in enumerate(src.splitlines()):
        if 'lambda' in l and 'vendido' in l:
            print(f"L{i+1}: {l.strip()}")
