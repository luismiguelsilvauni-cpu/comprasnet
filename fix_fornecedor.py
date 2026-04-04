"""fix_fornecedor.py - Corrige por-fornecedor para garantir SQL Server ligado"""
import re

with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

fixes = 0

# Fix 1: Ensure SQL Server starts before analysis in por-fornecedor route
old = '''    # Run bulk analysis using local DB only (no PHC connection needed here)
    artigos = ArtigoPHC.query.filter(ArtigoPHC.stock_atual >= 0).all()
    erro = None
    try:
        resultados = analisar_todos(cfg_phc, config, artigos)'''

new = '''    # Ensure SQL Server is running before analysis
    ensure_sqlserver_running()
    artigos = ArtigoPHC.query.filter(ArtigoPHC.stock_atual >= 0).all()
    erro = None
    try:
        resultados = analisar_todos(cfg_phc, config, artigos)'''

if old in src:
    src = src.replace(old, new)
    fixes += 1
    print("OK Fix 1: ensure_sqlserver_running adicionado")
else:
    print("Fix 1: nao encontrado - a verificar estado actual...")
    idx = src.find('analisar_todos(cfg_phc, config, artigos)')
    if idx > 0:
        print("  analisar_todos encontrado em:", idx)
        print("  Contexto:", repr(src[idx-200:idx+50]))

# Fix 2: Remove cursor.timeout if present
if 'cursor.timeout' in src:
    src = src.replace('cursor = conn.cursor()\n            cursor.timeout = 30',
                      'cursor = conn.cursor()')
    fixes += 1
    print("OK Fix 2: cursor.timeout removido")

# Fix 3: Ensure fn/fo query is correct
if 'FROM fi' in src and 'SQL_FORN_SIMPLES' in src:
    src = src.replace(
        '"SELECT fi.ref, fo.nome, fo.no"'
        '" FROM fi"'
        '" INNER JOIN fo ON fo.fostamp = fi.ftstamp"',
        '"SELECT fn.ref, fo.nome, fo.no"'
        '" FROM fn"'
        '" INNER JOIN fo ON fo.fostamp = fn.fostamp"'
    )
    fixes += 1
    print("OK Fix 3: query corrigida para fn")

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(src)

print(f"\nFeito ({fixes} fixes). Reinicie o servidor.")
