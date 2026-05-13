"""Force recalculate all durations for all assistencias from history."""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(__file__))

# First ensure column exists
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cols = [r[1] for r in cur.execute("PRAGMA table_info(assistencias)").fetchall()]
for col in ['dias_conclusao_comunicado', 'dias_recepcao_conclusao', 'dias_conclusao_faturado']:
    if col not in cols:
        cur.execute(f"ALTER TABLE assistencias ADD COLUMN {col} INTEGER")
        print(f"Added column: {col}")
conn.commit()
conn.close()

# Now recalculate via Flask
from app import app, db, Assistencia, AssistenciaHistorico, _assist_calc_durations

with app.app_context():
    items = Assistencia.query.all()
    print(f"\nA recalcular {len(items)} assistências...\n")
    for a in items:
        # Get all history ordered by criado_em
        hist = AssistenciaHistorico.query.filter_by(assist_id=a.id)\
            .order_by(AssistenciaHistorico.criado_em.asc()).all()
        
        # Build date map from history
        dates = {}
        for h in hist:
            if h.data_real:
                dates[h.status_novo] = h.data_real

        # Apply dates
        if 'rececionado'      in dates: a.data_rececionado    = dates['rececionado']
        if 'em_execucao'      in dates: a.data_em_execucao    = dates['em_execucao']
        if 'obra_concluida'   in dates: a.data_obra_concluida = dates['obra_concluida']
        if 'comunicado'       in dates: a.data_comunicado     = dates['comunicado']
        if 'faturado_fechado' in dates: a.data_faturado       = dates['faturado_fechado']

        # Recalculate durations
        _assist_calc_durations(a)

        print(f"  #{a.numero:04d} {a.requerente_nome[:25]:<25} | "
              f"rec={a.data_rececionado} obra={a.data_obra_concluida} "
              f"com={a.data_comunicado} fat={a.data_faturado}")
        print(f"         dias: rec->obra={a.dias_recepcao_conclusao} "
              f"obra->com={a.dias_conclusao_comunicado} "
              f"obra->fat={a.dias_conclusao_faturado}")

    db.session.commit()
    print(f"\n✅ {len(items)} assistências recalculadas.")
