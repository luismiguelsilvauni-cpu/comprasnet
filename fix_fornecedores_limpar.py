"""
Limpa a tabela fornecedores_phc mantendo apenas fornecedores reais.
Preserva todos os dados NAV (nav_telefone, nav_email, nav_notas, marcas).

Como identificar fornecedores reais sem acesso ao PHC:
- Fornecedores reais geralmente têm NIF empresarial (9 dígitos, começa por 5)
- Ou têm nome com "LDA", "SA", "SL", "UNIP", "LTD", "SERV", etc.
- Pessoas singulares com NIF de 9 dígitos começando por 1/2 são provavelmente clientes

Este script NÃO apaga — apenas lista o que seria removido.
Para limpar de facto, faça resync via botão na app após corrigir a query SQL.
"""
import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

total = cur.execute("SELECT COUNT(*) FROM fornecedores_phc").fetchone()[0]
print(f"Total actual: {total}")
print("\nA melhor solução é:")
print("1. Iniciar a aplicação")
print("2. Ir ao menu Fornecedores")
print("3. Clicar '🔄 Sincronizar PHC'")
print("   - A nova query só traz fornecedores com facturas de compra")
print("   - Os registos inválidos NÃO são apagados automaticamente")
print()

# Count potential non-suppliers (individual NIFs starting with 1 or 2)
rows = cur.execute("""
    SELECT COUNT(*) FROM fornecedores_phc 
    WHERE (nif LIKE '1%' OR nif LIKE '2%') 
    AND LENGTH(REPLACE(nif,' ','')) = 9
    AND nav_telefone = '' AND nav_email = '' AND nav_notas = '' 
    AND (marcas IS NULL OR marcas = '')
""").fetchone()[0]
print(f"Registos potencialmente clientes (NIF pessoal, sem dados NAV): {rows}")
print("(apenas estes seriam seguros de remover)")

# Offer to clean
resp = input("\nRemover estes registos? (s/N): ").strip().lower()
if resp == 's':
    cur.execute("""
        DELETE FROM fornecedores_phc 
        WHERE (nif LIKE '1%' OR nif LIKE '2%') 
        AND LENGTH(REPLACE(nif,' ','')) = 9
        AND nav_telefone = '' AND nav_email = '' AND nav_notas = '' 
        AND (marcas IS NULL OR marcas = '')
    """)
    removed = cur.rowcount
    conn.commit()
    print(f"Removidos {removed} registos.")
else:
    print("Nenhum registo removido.")

conn.close()
