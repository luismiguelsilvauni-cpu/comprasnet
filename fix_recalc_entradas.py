"""Recalculate all duration fields for existing entradas from history."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app, db, EntradaEquipamento, _recalc_entrada_dates

with app.app_context():
    items = EntradaEquipamento.query.all()
    print(f"A recalcular {len(items)} entradas...\n")
    for e in items:
        _recalc_entrada_dates(e)
        print(f"  #{e.numero:04d} {e.cliente_nome[:20]:<20} | "
              f"R-CF={e.dias_total} R-F={e.dias_rec_faturado} "
              f"CM-RP={e.dias_mat_reparacao} RP-F={e.dias_reparacao_fat}")
    db.session.commit()
    print(f"\n✅ {len(items)} entradas recalculadas.")
