"""
analisar_phc.py
───────────────
Analisa automaticamente a estrutura da BD PHC e encontra
as tabelas e colunas correctas para o ComprasNet.
Execute: python analisar_phc.py
"""

import sys
import json

try:
    import pyodbc
except ImportError:
    print("A instalar pyodbc...")
    import subprocess
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyodbc', '-q'])
    import pyodbc

SERVER   = r'.\SQLEXPRESS'
DATABASE = 'PHC_Uniao'

def connect():
    conn_str = (
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
        f'Trusted_Connection=yes;'
    )
    try:
        return pyodbc.connect(conn_str, timeout=10)
    except Exception:
        conn_str2 = (
            f'DRIVER={{SQL Server}};'
            f'SERVER={SERVER};'
            f'DATABASE={DATABASE};'
            f'Trusted_Connection=yes;'
        )
        return pyodbc.connect(conn_str2, timeout=10)

def get_columns(cursor, table):
    cursor.execute(f"""
        SELECT COLUMN_NAME, DATA_TYPE 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME=? 
        ORDER BY ORDINAL_POSITION
    """, table)
    return {r[0]: r[1] for r in cursor.fetchall()}

def find_best(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return None

print("=" * 60)
print("ComprasNet — Análise da BD PHC")
print("=" * 60)

try:
    conn = connect()
    cursor = conn.cursor()
    print("✅ Ligação OK\n")
except Exception as e:
    print(f"❌ Erro de ligação: {e}")
    sys.exit(1)

# ── Artigos (st) ──────────────────────────────────────────────
print("📦 ARTIGOS (tabela st):")
st = get_columns(cursor, 'st')
mapping_st = {
    'referencia':          find_best(st, ['ref','referencia','codigo']),
    'designacao':          find_best(st, ['design','designacao','descricao','nome']),
    'stock':               find_best(st, ['stock','qtt','qty','stkactual','quant']),
    'preco_custo':         find_best(st, ['pcusto','preco','pcompra','prc']),
    'preco_custo_pond':    find_best(st, ['pcp','pcpond','pcustopond']),
    'unidade':             find_best(st, ['unidade','uni','unid']),
    'familia':             find_best(st, ['familia','fami','grupo','grp']),
    'taxa_iva':            find_best(st, ['tabiva','taxa','iva','txiva']),
    'inactivo':            find_best(st, ['inactivo','inativo','activo']),
    'stamp':               find_best(st, ['ststamp','stamp']),
}
for k, v in mapping_st.items():
    status = '✅' if v else '❌'
    print(f"  {status} {k}: {v or 'NÃO ENCONTRADO'}")

# Quick data test
try:
    ref_col = mapping_st['referencia']
    des_col = mapping_st['designacao']
    stk_col = mapping_st['stock']
    cursor.execute(f"SELECT TOP 2 {ref_col}, {des_col}, {stk_col} FROM st WHERE {ref_col} IS NOT NULL AND {ref_col} <> ''")
    rows = cursor.fetchall()
    print(f"\n  Exemplo: {rows[0][0]} | {rows[0][1]} | stock={rows[0][2]}")
except Exception as e:
    print(f"  Erro teste: {e}")

# ── Entidades/Fornecedores (ec) ───────────────────────────────
print("\n👥 ENTIDADES (tabela ec):")
ec = get_columns(cursor, 'ec')
mapping_ec = {
    'numero':      find_best(ec, ['no','numero','cod','codigo']),
    'nome':        find_best(ec, ['nome','name','designacao']),
    'nif':         find_best(ec, ['ncont','nipc','nif','contribuinte','cif']),
    'morada':      find_best(ec, ['morada','endereco','address']),
    'localidade':  find_best(ec, ['local','localidade','cidade']),
    'cod_postal':  find_best(ec, ['codpost','cp','cpostal','codigopostal']),
    'telefone':    find_best(ec, ['telefone','tel','telef','phone']),
    'telemovel':   find_best(ec, ['tlm','telemovel','mobile','tele2']),
    'email':       find_best(ec, ['email','mail']),
    'fornecedor':  find_best(ec, ['fornecedor','forn','supplier']),
    'cliente':     find_best(ec, ['cliente','client','customer']),
    'inactivo':    find_best(ec, ['inactivo','inativo']),
    'stamp':       find_best(ec, ['ecstamp','stamp']),
}
for k, v in mapping_ec.items():
    status = '✅' if v else '❌'
    print(f"  {status} {k}: {v or 'NÃO ENCONTRADO'}")

# ── Documentos cabeçalho (ft) ─────────────────────────────────
print("\n📄 DOCUMENTOS (tabela ft):")
ft = get_columns(cursor, 'ft')
mapping_ft = {
    'stamp':       find_best(ft, ['ftstamp','stamp']),
    'numero':      find_best(ft, ['no','fno','numero','ndoc']),
    'data':        find_best(ft, ['data','date','dataDoc']),
    'entidade_no': find_best(ft, ['no','ecno','clno','fno']),
    'anulado':     find_best(ft, ['anulado','anulada','cancelado']),
    'serie':       find_best(ft, ['serie','ser']),
    'tipo':        find_best(ft, ['tipodoc','tipo','tpdoc']),
}
for k, v in mapping_ft.items():
    status = '✅' if v else '❌'
    print(f"  {status} {k}: {v or 'NÃO ENCONTRADO'}")

# ── Encontrar tabela de linhas com ref + ftstamp ──────────────
print("\n🔍 A PROCURAR tabela de linhas de documentos...")
cursor.execute("""
    SELECT DISTINCT t.TABLE_NAME 
    FROM INFORMATION_SCHEMA.COLUMNS t
    WHERE t.TABLE_NAME NOT LIKE 'BackUp%'
    AND t.TABLE_NAME NOT LIKE 'a_%'
    AND t.TABLE_NAME NOT LIKE 'A_%'
    AND EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME='ftstamp')
    AND EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME='ref')
    ORDER BY t.TABLE_NAME
""")
candidates = [r[0] for r in cursor.fetchall()]
print(f"  Candidatas com ftstamp+ref: {candidates}")

best_lines = None
for tbl in candidates:
    cols = get_columns(cursor, tbl)
    preco = find_best(cols, ['preco','epv','pvenda','prc','price','valor'])
    qtt   = find_best(cols, ['qtt','qty','quant','quantidade'])
    if preco and qtt:
        best_lines = {'tabela': tbl, 'preco': preco, 'qtt': qtt, 'cols': list(cols.keys())[:20]}
        print(f"  ✅ Melhor candidata: {tbl} (preco={preco}, qtt={qtt})")
        break
    else:
        print(f"  ⚠️  {tbl}: preco={preco}, qtt={qtt}")

if not best_lines:
    # Check all columns
    for tbl in candidates:
        cols = get_columns(cursor, tbl)
        print(f"\n  {tbl} campos: {list(cols.keys())[:15]}")

# ── Movimentos stock (mo) ─────────────────────────────────────
print("\n📊 MOVIMENTOS (tabela mo):")
try:
    mo = get_columns(cursor, 'mo')
    mapping_mo = {
        'referencia': find_best(mo, ['ref','referencia']),
        'quantidade': find_best(mo, ['qtt','qty','quant','quantidade']),
        'data':       find_best(mo, ['data','date']),
        'tipo':       find_best(mo, ['tipo','tpmov','tipomov']),
    }
    for k, v in mapping_mo.items():
        print(f"  {'✅' if v else '❌'} {k}: {v or 'NÃO ENCONTRADO'}")
except Exception as e:
    print(f"  Tabela mo não existe ou erro: {e}")

# ── Save mapping ──────────────────────────────────────────────
mapping = {
    'server':   SERVER,
    'database': DATABASE,
    'tabelas': {
        'artigos':     {'tabela': 'st',  'campos': mapping_st},
        'entidades':   {'tabela': 'ec',  'campos': mapping_ec},
        'documentos':  {'tabela': 'ft',  'campos': mapping_ft},
        'linhas':      best_lines or {},
    }
}

with open('phc_mapping.json', 'w', encoding='utf-8') as f:
    json.dump(mapping, f, indent=2, ensure_ascii=False)

print("\n" + "=" * 60)
print("✅ Mapeamento guardado em phc_mapping.json")
print("=" * 60)
conn.close()
