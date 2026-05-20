"""Explora tabelas sl e bi — movimentos de stock PHC para 049VC02."""
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

    # ==== SL table ====
    print("=== sl — todos os movimentos de 049VC02 ===")
    c = cols(cur, 'sl')
    print("Colunas:", c)
    cur.execute("SELECT COUNT(*) FROM sl WHERE ref='049VC02'")
    n = cur.fetchone()[0]
    print(f"Registos 049VC02: {n}")
    if n > 0:
        cur.execute("SELECT * FROM sl WHERE ref='049VC02' ORDER BY datalc")
        desc = [d[0] for d in cur.description]
        for row in cur.fetchall():
            d = dict(zip(desc, row))
            clean = {k: v for k,v in d.items() if v not in (None,'',False) and str(v) not in ('0','0.0','0.00000',' ')}
            print(f"  {clean}")

    # cmdesc distinct values in sl
    print("\n=== sl — cmdesc distintos (código do movimento) ===")
    cur.execute("SELECT DISTINCT cmdesc, COUNT(*) FROM sl GROUP BY cmdesc ORDER BY COUNT(*) DESC")
    for r in cur.fetchall():
        print(f"  cmdesc='{r[0]}' cnt={r[1]}")

    # Check if sl has separate entrada/saida or uses sign of qtt
    print("\n=== sl — análise qtt positivo vs negativo para 049VC02 ===")
    cur.execute("SELECT cmdesc, qtt, vu, evu, tt, ett, datalc FROM sl WHERE ref='049VC02' ORDER BY datalc")
    for r in cur.fetchall():
        print(f"  {r[0]!r:35s} qtt={r[1]} vu={r[2]} evu={r[3]} tt={r[4]} ett={r[5]} data={r[6]}")

    # ==== BI table ====
    print("\n\n=== bi — movimentos 049VC02 ===")
    c2 = cols(cur, 'bi')
    print("Colunas:", c2)
    cur.execute("SELECT COUNT(*) FROM bi WHERE RTRIM(ref)='049VC02'")
    n2 = cur.fetchone()[0]
    print(f"Registos: {n2}")
    if n2 > 0:
        cur.execute("SELECT nmdos, qtt, pu, epu, pcusto, epcusto, debito, edebito, stipo, rdata FROM bi WHERE RTRIM(ref)='049VC02'")
        for r in cur.fetchall():
            print(f"  nmdos={r[0]!r:30s} qtt={r[1]} pu={r[2]} epu={r[3]} custo={r[4]} ecusto={r[5]} debito={r[6]} edebito={r[7]} stipo={r[8]} data={r[9]}")

    # stipo distinct values in bi
    print("\n=== bi — stipo distintos e nmdos ===")
    cur.execute("SELECT stipo, nmdos, COUNT(*) FROM bi GROUP BY stipo, nmdos ORDER BY stipo, COUNT(*) DESC")
    for r in cur.fetchall():
        print(f"  stipo={r[0]} nmdos={r[1]!r:30s} cnt={r[2]}")

    # Total entries and exits for 049VC02 using sl
    print("\n\n=== sl — Totais entradas/saídas 049VC02 ===")
    cur.execute("""
        SELECT
            SUM(CASE WHEN qtt > 0 THEN qtt ELSE 0 END) AS total_entradas_qtt,
            SUM(CASE WHEN qtt < 0 THEN ABS(qtt) ELSE 0 END) AS total_saidas_qtt,
            SUM(CASE WHEN qtt > 0 THEN tt ELSE 0 END) AS total_entradas_valor,
            SUM(CASE WHEN qtt < 0 THEN ABS(tt) ELSE 0 END) AS total_saidas_valor,
            SUM(CASE WHEN qtt > 0 THEN ett ELSE 0 END) AS total_entradas_eur,
            SUM(CASE WHEN qtt < 0 THEN ABS(ett) ELSE 0 END) AS total_saidas_eur
        FROM sl WHERE ref='049VC02'
    """)
    r = cur.fetchone()
    print(f"  Entradas: qty={r[0]} valor={r[2]} eur={r[4]}")
    print(f"  Saídas:   qty={r[1]} valor={r[3]} eur={r[5]}")

    conn.close()
