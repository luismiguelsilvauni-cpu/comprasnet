from app import app
from models import ConfigPHC
from phc_sync import get_phc_connection

def cols(cur, t):
    cur.execute("SELECT COLUMN_NAME,DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION", t)
    return {r[0]: r[1] for r in cur.fetchall()}

with app.app_context():
    cfg = ConfigPHC.query.first()
    conn = get_phc_connection(cfg)
    cur = conn.cursor()

    # Also look for tables with 'of' in name that we might have missed
    cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' AND (TABLE_NAME LIKE 'of%' OR TABLE_NAME LIKE '%fab%' OR TABLE_NAME LIKE 'ow%' OR TABLE_NAME LIKE 'ob%') ORDER BY TABLE_NAME")
    of_tables = [r[0] for r in cur.fetchall()]
    print("Tabelas of/fab/ow/ob:", of_tables)

    for t in ['fo', 'ob', 'ofc', 'ow', 'of', 'ofl']:
        try:
            c = cols(cur, t)
            cur.execute(f"SELECT COUNT(*) FROM [{t}]")
            cnt = cur.fetchone()[0]
            print(f"\n=== [{t}] — {cnt} registos, {len(c)} colunas ===")
            print("  Colunas:", list(c.keys()))
            if cnt > 0:
                cur.execute(f"SELECT TOP 2 * FROM [{t}]")
                rows = cur.fetchall()
                desc = [d[0] for d in cur.description]
                for row in rows:
                    d = dict(zip(desc, row))
                    # Show interesting fields
                    interesting = {k: v for k, v in d.items()
                                   if k.lower() in ('no','data','fdata','nome','cl','clno','cln',
                                                    'aberto','fechado','anulado','concluido','fecho',
                                                    'estado','status','serie','tipodoc','ndoc',
                                                    'ofstamp','fwstamp','obstamp','owstamp',
                                                    'stamp','ousrinis','ousrdata','obs',
                                                    'artigo','ref','design','totalc','totalliq')}
                    print("  Exemplo:", interesting)
        except Exception as e:
            print(f"  [{t}] erro: {e}")

    # Check for tables with 'of' stamp
    print("\n\n=== Tabelas com coluna *stamp que possa ser OF ===")
    for stamp in ['ofstamp','obstamp','owstamp','orfstamp','ordfstamp']:
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE COLUMN_NAME=? ORDER BY TABLE_NAME", stamp)
        tbls = [r[0] for r in cur.fetchall()]
        if tbls: print(f"  {stamp}: {tbls}")

    conn.close()
