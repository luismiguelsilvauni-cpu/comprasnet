from app import app
from models import ConfigPHC
from phc_sync import get_phc_connection

with app.app_context():
    cfg = ConfigPHC.query.first()
    try:
        conn = get_phc_connection(cfg)
        cur = conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME")
        tables = [r[0] for r in cur.fetchall()]
        print('Total tabelas:', len(tables))
        # Look for OF/FO related
        of_related = [t for t in tables if t.lower() in ('of','ofl','ofp','ofh','ofc','of1','fo','fol','foa','fw','fwl','ob','obl','ow','owl','fow','foal')]
        print('OF/FO candidatas:', of_related)
        # Also print all short table names (likely PHC tables)
        short = [t for t in tables if len(t) <= 4 and not t.startswith('a')]
        print('Tabelas curtas PHC:', short[:60])
        conn.close()
    except Exception as e:
        print('ERRO:', e)
