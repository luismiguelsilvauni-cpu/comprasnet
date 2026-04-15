"""Update IRS fields directly in SQLite."""
import sqlite3, os

db = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db)
cur = conn.cursor()

# Show current recibos
rows = cur.execute("SELECT id, mes_label, ano, irs_parcela_abater, irs_taxa_efetiva FROM recibo_salario").fetchall()
print("Recibos actuais:")
for r in rows:
    print(f"  ID={r[0]} {r[2]}-{r[1]} parcela={r[3]} tx_ef={r[4]}")

rid = input("\nID do recibo a corrigir: ").strip()
b19 = float(input("Taxa Marginal B19 (ex: 0.3836): ").strip())
c19 = float(input("Parcela Abater C19 (ex: 530.52): ").strip())
d19 = float(input("Taxa Efetiva D19 (ex: 0.1792): ").strip())

cur.execute("UPDATE recibo_salario SET irs_parcela_abater=?, irs_taxa_efetiva=? WHERE id=?",
            (c19, d19, int(rid)))
conn.commit()

# Verify
r = cur.execute("SELECT irs_taxa, irs_parcela_abater, irs_taxa_efetiva FROM recibo_salario WHERE id=?", (rid,)).fetchone()
print(f"\n✅ Verificado: irs_taxa={r[0]} | parcela={r[1]} | tx_ef={r[2]}")
conn.close()
