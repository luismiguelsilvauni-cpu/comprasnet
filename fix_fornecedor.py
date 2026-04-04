"""fix_fornecedor.py - Corrige a query de fornecedores"""

with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

fixes = 0

# Fix 1: remove cursor.timeout
if 'cursor.timeout = 30' in src:
    src = src.replace(
        'cursor = conn.cursor()\n            cursor.timeout = 30',
        'cursor = conn.cursor()'
    )
    fixes += 1
    print("OK Fix 1: cursor.timeout removido")
else:
    print("Fix 1: ja ok")

# Fix 2: ensure correct SQL
if 'FROM fi' in src and 'SQL_FORN_SIMPLES' in src:
    src = src.replace(
        '"SELECT fi.ref, fo.nome, fo.no"'
        '" FROM fi"'
        '" INNER JOIN fo ON fo.fostamp = fi.ftstamp"',
        '"SELECT fn.ref, fo.nome, fo.no"'
        '" FROM fn"'
        '" INNER JOIN fo ON fo.fostamp = fn.fostamp"'
    )
    fixes += 1
    print("OK Fix 2: query corrigida para fn")
else:
    # Check current state
    idx = src.find('SQL_FORN_SIMPLES')
    if idx > 0:
        print("Fix 2: query actual =", src[idx:idx+150])

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(src)

print(f"\nFeito ({fixes} fixes). Reinicie o servidor.")
