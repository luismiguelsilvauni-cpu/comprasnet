import os
# Scripts temporários a apagar
para_apagar = []
for f in os.listdir('.'):
    if f.endswith('.py') and f not in ['app.py','models.py','run.py']:
        para_apagar.append(f)
print('Scripts temporarios encontrados:')
for f in sorted(para_apagar):
    print(' ', f)
print(f'\nTotal: {len(para_apagar)} ficheiros')
