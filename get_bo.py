from app import app
from models import ConfigPHC
from phc_sync import get_phc_connection

def cols(cur, t):
    cur.execute("SELECT COLUMN_NAME,DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION", t)
    return {r[0]: r[1] for r in cur.fetchall()}

def sample(cur, t, n=2):
    try:
        cur.execute(f"SELECT TOP {n} * FROM [{t}]")
        rows = cur.fetchall()
        desc = [d[0] for d in cur.description]
        return [dict(zip(desc, row)) for row in rows]
    except Exception as e:
        return [{'erro': str(e)}]

with app.app_context():
    cfg = ConfigPHC.query.first()
    conn = get_phc_connection(cfg)
    cur = conn.cursor()

    # Explore bo, bo2, bo3, bora, bfo, bdo
    for t in ['bo','bo2','bo3','bora','bfo','bdo','bbl','bl']:
        try:
            c = cols(cur, t)
            cur.execute(f"SELECT COUNT(*) FROM [{t}]"); cnt = cur.fetchone()[0]
            print(f"\n=== [{t}] — {cnt} registos ===")
            print("  Colunas:", list(c.keys())[:30])
            if cnt > 0:
                for row in sample(cur, t, 1):
                    interesting = {k: v for k, v in row.items()
                                   if k.lower() in ('no','data','nome','cl','clno','cln','aberto',
                                                    'fechado','anulado','concluido','fecho','estado',
                                                    'serie','tipodoc','ndoc','ref','design','obs',
                                                    'ousrinis','ousrdata','stamp','bostamp')}
                    print("  Exemplo:", interesting)
        except Exception as e:
            print(f"  [{t}] erro: {e}")

    # Check ft table for document types — OF and FO might be in the general doc table
    print("\n\n=== ft — tipos de documento distintos ===")
    try:
        cur.execute("""
            SELECT DISTINCT tipodoc, COUNT(*) as cnt
            FROM ft
            WHERE tipodoc IS NOT NULL AND tipodoc <> ''
            GROUP BY tipodoc
            ORDER BY cnt DESC
        """)
        tipos = cur.fetchall()
        print(f"  {len(tipos)} tipos distintos:")
        for t in tipos:
            print(f"    tipodoc='{t[0]}' — {t[1]} docs")
    except Exception as e:
        print("  Erro ft tipodoc:", e)

    # Look for ft with tipodoc that might be OF or FO
    print("\n=== ft — pesquisa por tipodoc que contenha OF/FO/FAB ===")
    try:
        cur.execute("""
            SELECT TOP 5 ft.no, ft.data, ft.tipodoc, ft.nome, ft.serie,
                   ft.aberto, ft.fechado, ft.anulado
            FROM ft
            WHERE tipodoc IN ('OF','FO','FAB','OFB','ORF','of','fo','fab')
               OR tipodoc LIKE '%OF%' OR tipodoc LIKE '%FAB%'
        """)
        rows = cur.fetchall()
        desc = [d[0] for d in cur.description]
        print(f"  Resultados: {len(rows)}")
        for r in rows: print(" ", dict(zip(desc, r)))
    except Exception as e:
        print("  Erro:", e)

    # Check ft columns - does it have aberto/fechado?
    print("\n=== ft — colunas de estado ===")
    ft_cols = cols(cur, 'ft')
    state = [c for c in ft_cols if c.lower() in ('aberto','fechado','anulado','concluido','fecho','estado')]
    print("  Colunas de estado em ft:", state)
    print("  Total colunas ft:", len(ft_cols))

    # Check bo columns more carefully
    print("\n=== bo — exploração detalhada ===")
    bo_cols = cols(cur, 'bo')
    print("  Todas as colunas bo:", list(bo_cols.keys()))
    cur.execute("SELECT COUNT(*) FROM bo"); cnt = cur.fetchone()[0]
    print(f"  {cnt} registos")
    if cnt > 0:
        cur.execute("SELECT TOP 3 * FROM bo")
        rows = cur.fetchall()
        desc2 = [d[0] for d in cur.description]
        for row in rows:
            print("  Row:", dict(zip(desc2, row)))

    conn.close()
