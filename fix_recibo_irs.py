"""Fix IRS fields directly in DB for existing recibos."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db

with app.app_context():
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Show existing recibos
    rows = cur.execute("SELECT id, funcionario_id, mes_label, ano, irs_taxa, irs_parcela_abater, irs_taxa_efetiva, irs_base, irs_retencao FROM recibo_salario ORDER BY id").fetchall()
    print("\nRecibos existentes:")
    for r in rows:
        print(f"  ID {r[0]} | {r[2]} {r[3]} | irs_taxa={r[4]} | parcela={r[5]} | tx_ef={r[6]} | base={r[7]} | retencao={r[8]}")

    rid = input("\nID do recibo a corrigir: ").strip()
    print("\nIntroduza os valores do Excel:")
    b19 = float(input("  Taxa Marginal B19 (ex: 0.3836): ").strip() or 0)
    c19 = float(input("  Parcela a Abater C19 (ex: 530.52): ").strip() or 0)
    d19 = float(input("  Taxa Efetiva D19 (ex: 0.1792): ").strip() or 0)
    e19 = float(input("  Base IRS E19 (ex: 2600): ").strip() or 0)
    h19 = float(input("  Valor IRS H19 (ex: 466): ").strip() or 0)

    cur.execute("""
        UPDATE recibo_salario
        SET irs_taxa=?, irs_parcela_abater=?, irs_taxa_efetiva=?, irs_base=?, irs_retencao=?
        WHERE id=?
    """, (b19, c19, d19, e19, h19, int(rid)))
    conn.commit()
    conn.close()
    print(f"\n✅ Recibo ID {rid} actualizado com sucesso.")
