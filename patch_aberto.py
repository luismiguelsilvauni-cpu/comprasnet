src = open('app.py', 'rb').read().decode('utf-8')
before = src.count('aberto')
src = src.replace(
    "estado = request.args.get('estado','')",
    "estado = request.args.get('estado','aberto')"
)
open('app.py', 'wb').write(src.encode('utf-8'))
after = open('app.py', 'rb').read().decode('utf-8').count('aberto')
print('Before:', before, '/ After:', after)
print('OK' if after > before else 'FAIL - pattern not found')
