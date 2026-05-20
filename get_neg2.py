"""Verifica a correccao para CU0149-2783-02."""
from datetime import datetime as _dt
from app import app
from models import ConfigPHC
from phc_sync import get_phc_connection

with app.app_context():
    cfg = ConfigPHC.query.first()
    conn = get_phc_connection(cfg)
    cur = conn.cursor()
    ref = 'CU0149-2783-02'
    cur.execute("""
        SELECT sl.datalc, sl.cmdesc, sl.qtt, sl.evu, sl.lno,
               RTRIM(ISNULL(sl.fnstamp,'')), RTRIM(ISNULL(sl.fistamp,'')), RTRIM(ISNULL(sl.bistamp,''))
        FROM sl WHERE RTRIM(sl.ref)=?
        ORDER BY sl.datalc, sl.lno
    """, ref)
    rows_raw = cur.fetchall()
    conn.close()

    def sort_key(r):
        d = r[0] if r[0] else _dt.min
        fn, fi, bi = r[5], r[6], r[7]
        cmd = (r[1] or '').strip()
        is_exit = 1 if (bool(fi) or bool(bi) or
            cmd.startswith('N/Factura') or cmd.startswith('V/Factura') or
            cmd.startswith('V/Venda') or cmd.startswith('Consu') or cmd.startswith('S.')) else 0
        return (d, is_exit)

    rows = sorted(rows_raw, key=sort_key)
    saldo = 0.0
    print("Após reordenação (entradas antes de saídas no mesmo dia):")
    for r in rows:
        data = r[0].strftime('%Y-%m-%d') if r[0] else '?'
        cmd = r[1]; qtt = float(r[2] or 0); lno = r[4]
        fn, fi, bi = bool(r[5]), bool(r[6]), bool(r[7])
        is_entry = fn or (cmd or '').startswith('Compra') or (cmd or '').startswith('Stock')
        if is_entry: saldo += qtt; d='ENT+'
        else: saldo -= qtt; d='SAI-'
        saldo_disp = max(0.0, saldo)
        neg = '' if saldo >= 0 else f' [raw={saldo:.2f} → display=0]'
        print(f"  {data} lno={lno:8} | {cmd:20s} | {d} {qtt:.2f} | saldo={saldo_disp:.2f}{neg}")
