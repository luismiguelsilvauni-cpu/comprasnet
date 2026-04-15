"""Inspect all non-empty cells in XLS to map structure."""
import sys, os, glob
import xlrd

upload_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'salarios')
files = glob.glob(os.path.join(upload_dir, '*.xls')) + glob.glob(os.path.join(upload_dir, '*.xlsx'))

if not files:
    xls_path = input("Caminho do ficheiro: ").strip()
else:
    print("Ficheiros encontrados:")
    for i,f in enumerate(files): print(f"  {i+1}. {os.path.basename(f)}")
    c = input("Escolha (Enter=1): ").strip()
    xls_path = files[int(c)-1 if c.isdigit() else 0]

print(f"\nA ler: {os.path.basename(xls_path)}\n")
wb = xlrd.open_workbook(xls_path)

for sname in wb.sheet_names():
    if sname.upper() in ('INICIO','TRANSF BCP'): continue
    ws = wb.sheet_by_name(sname)
    print(f"=== {sname} ({ws.nrows} linhas x {ws.ncols} colunas) ===")
    for r in range(ws.nrows):
        parts = []
        for c in range(ws.ncols):
            v = ws.cell_value(r, c)
            if v != '' and v != 0 and v is not None:
                parts.append(f"{chr(65+c)}{r+1}={repr(str(v)[:25])}")
        if parts:
            print('  ' + '  |  '.join(parts))
    print()
