import sys, os, xlrd
xls = os.path.join(os.path.dirname(__file__), 'uploads', 'salarios', '2026-Mar.xls')
wb = xlrd.open_workbook(xls)

# Find all sheets and their 'original' blocks
for sname in wb.sheet_names():
    if sname.upper() in ('INICIO', 'TRANSF BCP'): continue
    ws = wb.sheet_by_name(sname)

    # Find ALL 'original' markers
    originals = []
    for r in range(ws.nrows):
        for c in range(ws.ncols):
            if str(ws.cell_value(r,c)).strip().lower() == 'original':
                originals.append(r)

    if not originals:
        print(f"[{sname}] NO 'original' found - SKIP")
        continue

    O = originals[0]
    # Check if this is a salary sheet (has 'PROCESSAMENTO' and 'Remuneração Base')
    has_rem_base = any(
        'REMUNERAÇÃO BASE' in str(ws.cell_value(r, 0)).upper() or
        'REMUNERACAO BASE' in str(ws.cell_value(r, 0)).upper()
        for r in range(O, min(O+15, ws.nrows))
    )

    print(f"[{sname}] orig_row={O} | has_rem_base={has_rem_base}")
    if not has_rem_base:
        print(f"  -> SKIP (not a salary sheet)")
        continue

    # Find IRS row by scanning for 'I.R.S' in col A within the block
    irs_row = None
    for r in range(O, min(O+25, ws.nrows)):
        txt = str(ws.cell_value(r, 0)).upper()
        if 'I.R.S' in txt and 'HORAS' not in txt and 'EXTRAS' not in txt:
            irs_row = r
            break

    if irs_row:
        row_data = [(chr(65+c), ws.cell_value(irs_row, c))
                    for c in range(min(10, ws.ncols))
                    if ws.cell_value(irs_row, c) not in ('', None, ' ')]
        print(f"  IRS at row {irs_row} (Excel {irs_row+1}): {row_data}")
        print(f"  B={ws.cell_value(irs_row,1)} C={ws.cell_value(irs_row,2)} D={ws.cell_value(irs_row,3)}")
