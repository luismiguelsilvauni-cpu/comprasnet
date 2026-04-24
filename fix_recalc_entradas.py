"""Recalculate all duration fields for existing entradas.
Uses both history data_real AND the date fields already on the entry."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app, db, EntradaEquipamento, EntradaHistorico

def recalc(e):
    """Recalculate durations from whatever date data is available."""
    # Try to get dates from historico first
    hist = EntradaHistorico.query.filter_by(entrada_id=e.id)\
        .order_by(EntradaHistorico.criado_em.asc()).all()
    
    dates = {}
    for h in hist:
        if h.data_real:
            dates[h.status_novo] = h.data_real
        elif h.criado_em and h.status_novo not in dates:
            # Fallback: use registration date if no real date
            dates[h.status_novo] = h.criado_em.date()

    # data_orcamento may be set directly (inline editor) — only override from history if history has it
    # Apply dates to entry fields
    if 'pre_orcamento'       in dates: e.data_pre_orcamento      = dates['pre_orcamento']
    if 'orcamentado'         in dates: e.data_orcamento           = dates['orcamentado']
    if 'material_pedido'     in dates: e.data_material_pedido     = dates['material_pedido']
    if 'material_stock'      in dates: e.data_material_stock      = dates['material_stock']
    if 'em_reparacao'        in dates: e.data_em_reparacao        = dates['em_reparacao']
    if 'reparacao_concluida' in dates: e.data_reparacao_concluida = dates['reparacao_concluida']
    if 'faturado'            in dates: e.data_faturado            = dates['faturado']
    if 'concluido_fechado'   in dates:
        e.data_fecho = dates['concluido_fechado']

    # Calculate durations (only positive values)
    def diff(d1, d2):
        if d1 and d2:
            v = (d2 - d1).days
            if v < 0:
                print(f'    ⚠️  Negativo: {d1} -> {d2} = {v}d')
                return None  # Don't store negative values
            return v
        return None

    e.dias_total              = diff(e.data_rececao, e.data_fecho)
    e.dias_rec_orcamento      = diff(e.data_rececao, e.data_orcamento)
    e.dias_rec_faturado       = diff(e.data_rececao, e.data_faturado)
    e.dias_orc_reparacao      = diff(e.data_orcamento, e.data_em_reparacao)
    e.dias_mat_reparacao      = diff(e.data_material_pedido, e.data_em_reparacao)
    e.dias_mat_stock          = diff(e.data_material_pedido, e.data_material_stock)
    e.dias_stock_reparacao    = diff(e.data_material_stock, e.data_em_reparacao)
    e.dias_reparacao_concluida = diff(e.data_em_reparacao, e.data_reparacao_concluida)
    e.dias_reparacao_fat      = diff(e.data_em_reparacao, e.data_faturado)

with app.app_context():
    items = EntradaEquipamento.query.all()
    print(f"A recalcular {len(items)} entradas...\n")
    for e in items:
        recalc(e)
        print(f"  #{e.numero:04d} {e.cliente_nome[:22]:<22} | "
              f"status={e.status:<20} "
              f"R-CF={e.dias_total} "
              f"R-ORC={e.dias_rec_orcamento} "
              f"R-F={e.dias_rec_faturado} "
              f"ORC-RP={e.dias_orc_reparacao} "
              f"CM-RP={e.dias_mat_reparacao} "
              f"RP-F={e.dias_reparacao_fat}")
    db.session.commit()
    print(f"\n✅ {len(items)} entradas recalculadas.")
