"""Remove weasyprint dependency from salario_recibo_pdf route."""
with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

out = []
skip = False
for i, line in enumerate(lines):
    if 'weasyprint or return HTML for print' in line:
        skip = True
    if skip and 'from flask import make_response' in line:
        skip = False
    if not skip:
        out.append(line)

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(out)

# Verify
with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()
if 'weasyprint' not in src:
    print("OK: weasyprint removido com sucesso")
else:
    print("AINDA TEM weasyprint - fix manual necessario")
