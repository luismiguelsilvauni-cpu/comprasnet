"""Encontra a tabela de movimentos de stock do PHC."""
from app import app
from models import ConfigPHC
from phc_sync import get_phc_connection

def cols(cur, t):
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION", t)
    return [r[0] for r in cur.fetchall()]

with app.app_context():
    cfg = ConfigPHC.query.first()
    conn = get_phc_connection(cfg)
    cur = conn.cursor()

    # 1. Tables with both 'ref' AND ('entrada' or 'saida' or 'tipomov')
    print("=== Tabelas com ref + entrada/saida/tipomov ===")
    cur.execute("""
        SELECT DISTINCT t.TABLE_NAME
        FROM INFORMATION_SCHEMA.COLUMNS t
        WHERE EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME='ref')
          AND (
            EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME IN ('entrada','saida','tipomov','tpmov'))
            OR EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME LIKE '%entrada%')
            OR EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME LIKE '%saida%')
          )
        ORDER BY t.TABLE_NAME
    """)
    cands = [r[0] for r in cur.fetchall()]
    print(f"  {cands}")

    for t in cands[:10]:
        c = cols(cur, t)
        cur.execute(f"SELECT COUNT(*) FROM [{t}]"); n = cur.fetchone()[0]
        print(f"\n  [{t}] {n} registos — colunas: {c[:25]}")
        if n > 0:
            cur.execute(f"SELECT TOP 1 * FROM [{t}]")
            desc = [d[0] for d in cur.description]
            row = dict(zip(desc, cur.fetchone()))
            clean = {k: v for k,v in row.items() if v not in (None,'',0,False)}
            print(f"    Exemplo: {clean}")

    # 2. Tables with 'epcpond' or 'epcusto' AND 'ref' (stock movement cost columns)
    print("\n\n=== Tabelas com ref + epcpond/epcusto (custo ponderado) ===")
    cur.execute("""
        SELECT DISTINCT t.TABLE_NAME
        FROM INFORMATION_SCHEMA.COLUMNS t
        WHERE EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME='ref')
          AND EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME IN ('epcpond','epcusto','cmpond','cmunit','ecusto'))
        ORDER BY t.TABLE_NAME
    """)
    cands2 = [r[0] for r in cur.fetchall()]
    print(f"  {cands2}")
    for t in cands2[:8]:
        c = cols(cur, t)
        cur.execute(f"SELECT COUNT(*) FROM [{t}]"); n = cur.fetchone()[0]
        print(f"\n  [{t}] {n} registos — colunas: {c[:30]}")
        if n > 0:
            # look for 049VC02
            try:
                cur.execute(f"SELECT TOP 3 * FROM [{t}] WHERE ref='049VC02'")
                rows = cur.fetchall()
                if rows:
                    desc = [d[0] for d in cur.description]
                    print(f"    Ref 049VC02 ({len(rows)} registos):")
                    for row in rows:
                        d = dict(zip(desc, row))
                        clean = {k: v for k,v in d.items() if v not in (None,'',False) and str(v)!='0'}
                        print(f"      {clean}")
                else:
                    cur.execute(f"SELECT TOP 1 * FROM [{t}]")
                    desc = [d[0] for d in cur.description]
                    row = dict(zip(desc, cur.fetchone()))
                    clean = {k: v for k,v in row.items() if v not in (None,'',0,False)}
                    print(f"    Exemplo geral: {clean}")
            except Exception as e:
                print(f"    Erro: {e}")

    # 3. Tables named with stock movement patterns
    print("\n\n=== Tabelas com nomes típicos de movimentos (mi, ms, mv, bi, sl, mel, mel) ===")
    cur.execute("""
        SELECT TABLE_NAME, (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=T.TABLE_NAME) AS ncols
        FROM INFORMATION_SCHEMA.TABLES T
        WHERE TABLE_TYPE='BASE TABLE'
          AND TABLE_NAME IN ('mi','ms','mv','bi','sl','mel','mst','msi','msa','msp','sai','ent','mov','stm','bom','boi','bol')
        ORDER BY TABLE_NAME
    """)
    for r in cur.fetchall():
        t = r[0]
        c = cols(cur, t)
        cur.execute(f"SELECT COUNT(*) FROM [{t}]"); n = cur.fetchone()[0]
        print(f"  [{t}] {n} registos — {c[:20]}")

    # 4. Search for the 049VC02 ref across likely candidate tables
    print("\n\n=== Procura ref '049VC02' em tabelas com coluna ref ===")
    cur.execute("""
        SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE COLUMN_NAME='ref' AND TABLE_NAME NOT LIKE 'BackUp%'
        ORDER BY TABLE_NAME
    """)
    ref_tables = [r[0] for r in cur.fetchall()]
    print(f"  Tabelas com coluna 'ref' ({len(ref_tables)}): {ref_tables[:30]}")
    for t in ref_tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM [{t}] WHERE ref='049VC02'")
            n = cur.fetchone()[0]
            if n > 0:
                c = cols(cur, t)
                print(f"\n  ✅ [{t}] tem {n} registos para 049VC02 — colunas: {c[:25]}")
                cur.execute(f"SELECT TOP 2 * FROM [{t}] WHERE ref='049VC02'")
                desc = [d[0] for d in cur.description]
                for row in cur.fetchall():
                    d = dict(zip(desc, row))
                    clean = {k: v for k,v in d.items() if v not in (None,'',False) and str(v)!='0'}
                    print(f"    {clean}")
        except: pass

    conn.close()
