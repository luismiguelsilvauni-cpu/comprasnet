"""Recalculate all duration fields for existing assistencias."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app, db, Assistencia, _assist_calc_durations

with app.app_context():
    all_a = Assistencia.query.all()
    updated = 0
    for a in all_a:
        before = (a.dias_recepcao_conclusao, a.dias_conclusao_comunicado, a.dias_conclusao_faturado)
        _assist_calc_durations(a)
        after = (a.dias_recepcao_conclusao, a.dias_conclusao_comunicado, a.dias_conclusao_faturado)
        if before != after:
            updated += 1
        print(f"#{a.numero:04d} {a.requerente_nome[:20]:<20} "
              f"rec→obra={a.dias_recepcao_conclusao} "
              f"obra→com={a.dias_conclusao_comunicado} "
              f"obra→fat={a.dias_conclusao_faturado}")
    db.session.commit()
    print(f"\n✅ {updated} registos actualizados de {len(all_a)} total.")
