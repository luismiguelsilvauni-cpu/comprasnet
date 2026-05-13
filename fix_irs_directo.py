"""Fix IRS fields directly from Excel into DB - no questions asked."""
import sys, os, xlrd, glob, sqlite3

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

xls_files = glob.glob(os.path.join(os.path.dirname(__file__), 'uploads', 'salarios', '*.xls'))
if not xls_files:
    print("ERRO: Nenhum .xls em uploads/salarios/")
    sys.exit(1)

xls_path = xls_files[0]
print(f"A ler: {os.path.basename(xls_path)}")

wb = xlrd.open_workbook(xls_path)

def sv(ws, r, c):
    try: return str(ws.cell_value(r, c)).strip()
    except: return ''

def fv(ws, r, c):
    try: return float(ws.cell_value(r, c) or 0)
    except: return 0.0

updated = 0
for sname in wb.sheet_names():
    if sname.upper() in ('INICIO', 'TRANSF BCP'): continue
    ws = wb.sheet_by_name(sname)

    # Find 'original' row
    orig_row = 1
    for r in range(min(10, ws.nrows)):
        for c in range(ws.ncols):
            if sv(ws, r, c).lower() == 'original':
                orig_row = r; break

    O = orig_row

    # Check salary sheet
    has_rem = any('REMUNERAÇÃO BASE' in sv(ws, r, 0).upper() or 'REMUNERACAO BASE' in sv(ws, r, 0).upper()
                  for r in range(O, min(O+15, ws.nrows)))
    if not has_rem:
        print(f"  SKIP {sname} (não é recibo salarial)")
        continue

    # Find IRS row by text
    irs_row = None
    for r in range(O, min(O+30, ws.nrows)):
        txt = sv(ws, r, 0).upper()
        if 'I.R.S' in txt and 'HORAS' not in txt and 'EXTRAS' not in txt:
            irs_row = r; break

    if irs_row is None:
        print(f"  SKIP {sname} (IRS row não encontrada)")
        continue

    # Extract values
    irs_taxa   = fv(ws, irs_row, 1)  # B
    irs_parc   = fv(ws, irs_row, 2)  # C
    irs_tx_ef  = fv(ws, irs_row, 3)  # D
    irs_base   = fv(ws, irs_row, 4)  # E
    irs_val    = fv(ws, irs_row, 7)  # H

    # Get num from sheet name (e.g. "11-Luis Silva" → "11")
    num = sname.split('-')[0].strip() if '-' in sname else None

    print(f"  {sname}: IRS taxa={irs_taxa} parcela={irs_parc} tx_ef={irs_tx_ef} base={irs_base} val={irs_val}")

    # Find recibo by funcionario number
    if num:
        rows = cur.execute("""
            SELECT rs.id FROM recibo_salario rs
            JOIN funcionario f ON f.id = rs.funcionario_id
            WHERE f.numero = ?
        """, (num,)).fetchall()
    else:
        rows = []

    for (rid,) in rows:
        cur.execute("""
            UPDATE recibo_salario
            SET irs_taxa=?, irs_parcela_abater=?, irs_taxa_efetiva=?, irs_base=?, irs_retencao=?
            WHERE id=?
        """, (irs_taxa, irs_parc, irs_tx_ef, irs_base, irs_val, rid))
        print(f"    → Recibo ID {rid} actualizado")
        updated += 1

conn.commit()
conn.close()
print(f"\n✅ {updated} recibo(s) actualizado(s)")
