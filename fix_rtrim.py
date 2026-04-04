"""fix_rtrim.py - Adds RTRIM to fn.ref query"""

with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

old = '"SELECT fn.ref, fo.nome, fo.no"'
new = '"SELECT RTRIM(fn.ref) AS ref, fo.nome, fo.no"'

if old in src:
    src = src.replace(old, new)
    print("OK: RTRIM added to SELECT")
else:
    print("Already has RTRIM or query not found")
    idx = src.find('SQL_FORN_SIMPLES')
    if idx > 0:
        print("Current:", repr(src[idx:idx+150]))

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(src)
print("Done. Restart server.")
