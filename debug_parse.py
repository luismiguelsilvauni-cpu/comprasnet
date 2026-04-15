import sys, os, xlrd
sys.path.insert(0, os.path.dirname(__file__))

xls = os.path.join(os.path.dirname(__file__), 'uploads', 'salarios', '2026-Mar.xls')
wb = xlrd.open_workbook(xls)

for sname in wb.sheet_names():
    ws = wb.sheet_by_name(sname)
    # Find 'original' row
    orig_row = 1
    for r in range(min(5, ws.nrows)):
        for c in range(ws.ncols):
            if str(ws.cell_value(r,c)).strip().lower() == 'original':
                orig_row = r
                print(f"[{sname}] 'original' found at row {r} (Excel row {r+1}), col {c}")
                break

    O = orig_row
    print(f"[{sname}] IRS row offset O+17 = row {O+17} (Excel {O+18})")
    # Print the IRS row
    irs_row = O + 17
    if irs_row < ws.nrows:
        for c in range(min(10, ws.ncols)):
            v = ws.cell_value(irs_row, c)
            if v != '' and v is not None:
                print(f"  col {c} ({chr(65+c)}{irs_row+1}): {repr(v)}")
    print()
    break  # just first employee sheet
