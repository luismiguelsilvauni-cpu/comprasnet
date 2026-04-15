import sys, os, xlrd
xls = os.path.join(os.path.dirname(__file__), 'uploads', 'salarios', '2026-Mar.xls')
wb = xlrd.open_workbook(xls)

print("Sheets:", wb.sheet_names())

for sname in wb.sheet_names():
    if sname.upper() in ('INICIO', 'TRANSF BCP'): continue
    ws = wb.sheet_by_name(sname)

    # Find 'original' row
    orig_row = None
    for r in range(min(10, ws.nrows)):
        for c in range(ws.ncols):
            v = str(ws.cell_value(r, c)).strip().lower()
            if v == 'original':
                orig_row = r
                break
        if orig_row is not None: break

    print(f"\n[{sname}] orig_row={orig_row} (Excel row {orig_row+1 if orig_row is not None else '?'})")
    if orig_row is None:
        print("  WARNING: 'original' not found! Scanning first 5 rows:")
        for r in range(min(5, ws.nrows)):
            for c in range(ws.ncols):
                v = ws.cell_value(r, c)
                if v: print(f"    {chr(65+c)}{r+1}={repr(str(v)[:30])}")
        continue

    O = orig_row
    irs_r = O + 17
    print(f"  IRS row = O+17 = {irs_r} (Excel {irs_r+1})")
    if irs_r < ws.nrows:
        row_data = [(chr(65+c), ws.cell_value(irs_r, c)) for c in range(min(10, ws.ncols)) if ws.cell_value(irs_r, c) not in ('', None, 0, 0.0)]
        print(f"  IRS row values: {row_data}")
    break  # first employee only
