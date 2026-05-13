import sqlite3, os
db = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db)
conn.execute("UPDATE recibo_salario SET mes=3, mes_label='Março' WHERE id=1")
conn.commit()
r = conn.execute("SELECT id, mes, mes_label, irs_parcela_abater, irs_taxa_efetiva FROM recibo_salario WHERE id=1").fetchone()
print(f"Corrigido: ID={r[0]} mes={r[1]} label={r[2]} parcela={r[3]} tx_ef={r[4]}")
conn.close()
