"""Verifica preços de custo para CU5527131 no PHC."""
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

    ref = 'CU5527131'

    # 1. Check available cost columns in st
    st_cols = cols(cur, 'st')
    cost_related = [c for c in st_cols if any(x in c.lower() for x in ['custo','pond','pcult','epv','pv1','pv2','pv3'])]
    print(f"Colunas de custo em st: {cost_related}")

    # 2. st - get all cost values
    cost_sel = ', '.join(f'[{c}]' for c in cost_related[:15])
    cur.execute(f"SELECT ref, design, stock, {cost_sel} FROM st WHERE RTRIM(ref) = ?", ref)
    row = cur.fetchone()
    if row:
        desc = [d[0] for d in cur.description]
        for k, v in zip(desc, row):
            if v not in (None, 0, False, ''):
                print(f"  st.{k} = {v}")

    # 3. sl - last 10 movements
    print(f"\n=== sl — últimos 10 movimentos de {ref} ===")
    cur.execute("""
        SELECT TOP 10 datalc, cmdesc, qtt, vu, evu, tt, ett, epcpond
        FROM sl WHERE RTRIM(ref) = ?
        ORDER BY datalc DESC
    """, ref)
    for r in cur.fetchall():
        print(f"  {r[0].date() if r[0] else '?'} | {r[1]!r:25s} | qtt={r[2]} vu={r[3]} evu={r[4]} epcpond={r[7]}")

    # 4. Most recent epcpond from sl
    print(f"\n=== Custo ponderado mais recente (sl) ===")
    cur.execute("SELECT TOP 1 epcpond, pcpond, datalc FROM sl WHERE RTRIM(ref) = ? ORDER BY datalc DESC", ref)
    row = cur.fetchone()
    if row:
        print(f"  epcpond (sl) = {row[0]} | pcpond = {row[1]} | data = {row[2]}")

    # 5. fn purchases
    print(f"\n=== fn — compras ===")
    fn_cols = cols(cur, 'fn')
    price_cols = [c for c in fn_cols if any(x in c.lower() for x in ['epv','pv','custo','preco','price'])]
    print(f"  fn price cols: {price_cols}")
    try:
        cur.execute("""
            SELECT TOP 5 fn.qtt, fn.epv, fo.data, LTRIM(RTRIM(fo.nome))
            FROM fn INNER JOIN fo ON fo.fostamp = fn.fostamp
            WHERE RTRIM(fn.ref) = ? ORDER BY fo.data DESC
        """, ref)
        for r in cur.fetchall():
            print(f"  qtt={r[0]} epv={r[1]}€ data={r[2]} forn={r[3]!r}")
    except Exception as e:
        print(f"  Erro fn: {e}")

    # 6. Diagnose
    print(f"\n=== Diagnóstico final ===")
    cur.execute("SELECT ISNULL(epcusto,0), ISNULL(epcpond,0) FROM st WHERE RTRIM(ref) = ?", ref)
    r = cur.fetchone()
    if r:
        epcusto, epcpond = float(r[0]), float(r[1])
        print(f"  st.epcusto = {epcusto:.4f} €  ← último preço custo")
        print(f"  st.epcpond = {epcpond:.4f} €  ← custo ponderado médio")
        print(f"  Sistema usa: {'epcusto' if epcusto else 'epcpond'} = {epcusto or epcpond:.4f} €")
        print(f"  Utilizador espera: 3413.40 €")

    conn.close()
