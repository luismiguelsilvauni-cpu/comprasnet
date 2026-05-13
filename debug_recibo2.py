import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(__file__))
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
rows = cur.execute("SELECT id, mes_label, ano, vencimento_base, vencimento_base_rht, irs_taxa, irs_parcela_abater, irs_taxa_efetiva, irs_base, irs_retencao, seg_social_func, liquido FROM recibo_salario ORDER BY id DESC LIMIT 5").fetchall()
cols = [d[0] for d in cur.description]
for r in rows:
    print(dict(zip(cols, r)))
conn.close()
