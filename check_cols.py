import sqlite3, os
db = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db)
rows = conn.execute("SELECT id, funcionario_id, mes, mes_label, ano, irs_taxa, irs_parcela_abater, irs_taxa_efetiva FROM recibo_salario ORDER BY id").fetchall()
print("Todos os recibos:")
for r in rows:
    print(f"  ID={r[0]} func={r[1]} mes={r[2]} label={r[3]} ano={r[4]} irs_taxa={r[5]} parcela={r[6]} tx_ef={r[7]}")
conn.close()
