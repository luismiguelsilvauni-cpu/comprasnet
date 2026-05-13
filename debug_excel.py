"""Debug: le o excel e mostra o que foi detectado"""
import sys, openpyxl
from io import BytesIO

if len(sys.argv) < 2:
    print("Uso: python debug_excel.py ficheiro.xlsx")
    sys.exit(1)

wb = openpyxl.load_workbook(sys.argv[1], data_only=True)
ws = wb.active

headers = [str(cell.value or '').strip() for cell in ws[1]]
print("Cabeçalhos encontrados:")
for i, h in enumerate(headers):
    print(f"  Col {i}: '{h}'")

print(f"\nTotal de linhas de dados: {ws.max_row - 1}")
print("\nPrimeiras 3 linhas:")
for row in ws.iter_rows(min_row=2, max_row=4, values_only=True):
    print(" ", row)
