"""Analisa movimentos de CU0149-2783-02 e identifica porque o saldo fica negativo."""
from app import app
from models import ConfigPHC
from phc_sync import get_phc_connection

with app.app_context():
    cfg = ConfigPHC.query.first()
    conn = get_phc_connection(cfg)
    cur = conn.cursor()

    ref = 'CU0149-2783-02'

    # 1. Current stock in st
    cur.execute("SELECT RTRIM(ref), design, stock, epcpond FROM st WHERE RTRIM(ref)=?", ref)
    r = cur.fetchone()
    if r:
        print(f"st.stock = {r[2]} | epcpond = {r[3]}")
    else:
        print("Artigo nao encontrado em st")

    # 2. All sl movements with running balance
    print(f"\n=== Todos os movimentos sl para {ref} ===")
    cur.execute("""
        SELECT sl.datalc, sl.cmdesc, sl.qtt, sl.evu, sl.ett, sl.epcpond,
               LTRIM(RTRIM(ISNULL(sl.nome,''))),
               RTRIM(ISNULL(sl.fnstamp,'')),
               RTRIM(ISNULL(sl.fistamp,'')),
               RTRIM(ISNULL(sl.bistamp,''))
        FROM sl WHERE RTRIM(sl.ref)=?
        ORDER BY sl.datalc, sl.lno
    """, ref)
    rows = cur.fetchall()
    print(f"Total movimentos: {len(rows)}")

    saldo = 0.0
    for r in rows:
        data   = r[0].strftime('%Y-%m-%d') if r[0] else '?'
        cmdesc = (r[1] or '').strip()
        qtt    = float(r[2] or 0)
        evu    = float(r[3] or 0)
        fn     = r[7]
        fi     = r[8]
        bi     = r[9]

        # Classify (same logic as API)
        is_entry = bool(fn) or cmdesc == 'Compra' or cmdesc.startswith('Stock') or cmdesc.startswith('E.')
        is_sale  = bool(fi) or cmdesc.startswith('N/Factura') or cmdesc.startswith('V/Factura') or cmdesc.startswith('V/Venda') or cmdesc.startswith('Resumo')
        is_prod  = bool(bi) or cmdesc.startswith('Consu') or cmdesc.startswith('S.')

        if is_entry:
            saldo += qtt; dir_ = 'ENT +'
        elif is_sale or is_prod:
            saldo -= qtt; dir_ = 'SAI -'
        else:
            dir_ = 'OTHER'
            # What is it?

        neg = ' <<< NEGATIVO!' if saldo < 0 else ''
        print(f"  {data} | {cmdesc:25s} | qtt={qtt:6.2f} | {dir_} | saldo={saldo:7.2f} | fn={bool(fn)} fi={bool(fi)} bi={bool(bi)}{neg}")

    # 3. Distinct cmdesc for this ref
    print(f"\n=== cmdesc distintos para {ref} ===")
    cur.execute("SELECT DISTINCT cmdesc, COUNT(*) FROM sl WHERE RTRIM(ref)=? GROUP BY cmdesc ORDER BY COUNT(*) DESC", ref)
    for r in cur.fetchall():
        print(f"  '{r[0]}' — {r[1]}")

    conn.close()
