"""Remove entradas que sao clientes e nao fornecedores reais.
Fornecedores reais estao na tabela 'fo' do PHC, clientes na 'cl'.
Como nao temos acesso directo aqui, vamos identificar pelo NIF:
- Fornecedores geralmente tem NIF preenchido
- Mas o melhor e limpar e ressincronizar via botao na app
"""
import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

total = cur.execute("SELECT COUNT(*) FROM fornecedores_phc").fetchone()[0]
print(f"Total fornecedores_phc: {total}")

# Show sample
rows = cur.execute("SELECT numero, nome, nif, localidade FROM fornecedores_phc ORDER BY nome LIMIT 20").fetchall()
for r in rows:
    print(f"  {r[0]:6} | {r[1][:40]:<40} | {r[2] or '':<15} | {r[3] or ''}")

conn.close()
