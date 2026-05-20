"""
analisar_phc_of.py
──────────────────
Analisa a BD PHC e encontra as tabelas de Ordens de Fabrico e Folhas de Obra.
Execute: python analisar_phc_of.py
"""
import sys
try:
    import pyodbc
except ImportError:
    import subprocess; subprocess.run([sys.executable,'-m','pip','install','pyodbc','-q']); import pyodbc

SERVER   = r'.\SQLEXPRESS'
DATABASE = 'PHC_Uniao'

def connect():
    for drv in ['ODBC Driver 17 for SQL Server','ODBC Driver 13 for SQL Server','SQL Server']:
        try:
            return pyodbc.connect(
                f'DRIVER={{{drv}}};SERVER={SERVER};DATABASE={DATABASE};'
                f'Trusted_Connection=yes;Connection Timeout=10;')
        except: continue
    raise Exception("Não foi possível ligar")

def cols(cursor, table):
    cursor.execute(
        "SELECT COLUMN_NAME,DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION", table)
    return {r[0]: r[1] for r in cursor.fetchall()}

def sample(cursor, table, limit=2):
    try:
        cursor.execute(f"SELECT TOP {limit} * FROM [{table}]")
        rows = cursor.fetchall()
        desc = [d[0] for d in cursor.description]
        return [dict(zip(desc, row)) for row in rows]
    except Exception as e:
        return [{'erro': str(e)}]

print("="*65)
print("ComprasNet — Análise OF e Folhas de Obra na BD PHC")
print("="*65)

conn = connect(); cursor = conn.cursor()
print("✅ Ligação OK\n")

# 1. List ALL tables
cursor.execute("""
    SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE='BASE TABLE'
    ORDER BY TABLE_NAME
""")
all_tables = [r[0] for r in cursor.fetchall()]
print(f"Total de tabelas: {len(all_tables)}\n")

# 2. Candidate tables for OF (Ordem de Fabrico)
# PHC CS typically uses: of, ofl, ofst, ofp
of_candidates = [t for t in all_tables if t.lower() in ('of','ofl','ofst','ofp','ofh','ofc','of1','of2')]
print(f"Candidatas OF: {of_candidates}")
for t in of_candidates:
    c = cols(cursor, t)
    print(f"\n  📋 Tabela [{t}] — {len(c)} colunas:")
    print(f"     Colunas: {list(c.keys())}")
    s = sample(cursor, t)
    for row in s:
        # Show only key fields
        preview = {k: v for k, v in row.items() if k.lower() in
                   ('ofstamp','no','data','fdata','nome','entidade','aberto','fechado',
                    'ousrinis','ousrdata','cria','estado','status','anulado','concluido',
                    'fecho','datafecho','cl','clno','cln','numerodoc','ndoc','serie','tipodoc')}
        print(f"     Exemplo: {preview}")

# 3. Candidate tables for Folhas de Obra
# PHC CS typically uses: fo, fol, foa, fw, fwl, ob, obl
fo_candidates = [t for t in all_tables if t.lower() in
                 ('fo','fol','foa','fw','fwl','ob','obl','fow','foal','ow','owl')]
print(f"\nCandidatas Folhas de Obra: {fo_candidates}")
for t in fo_candidates:
    c = cols(cursor, t)
    print(f"\n  📋 Tabela [{t}] — {len(c)} colunas:")
    print(f"     Colunas: {list(c.keys())}")
    s = sample(cursor, t)
    for row in s:
        preview = {k: v for k, v in row.items() if k.lower() in
                   ('fostamp','no','data','fdata','nome','entidade','aberto','fechado',
                    'estado','status','anulado','concluido','fecho','cl','clno','cln',
                    'numerodoc','ndoc','serie','tipodoc','ousrinis','ousrdata')}
        print(f"     Exemplo: {preview}")

# 4. Also search by column presence — look for tables with 'ofstamp' or stamp pattern
print("\n\n--- Pesquisa por stamp patterns ---")
for stamp_col in ['ofstamp','fwstamp','fostamp','oestamp']:
    cursor.execute("""
        SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE COLUMN_NAME=? ORDER BY TABLE_NAME
    """, stamp_col)
    tbls = [r[0] for r in cursor.fetchall()]
    if tbls:
        print(f"Tabelas com [{stamp_col}]: {tbls}")
        for t in tbls[:3]:
            c = cols(cursor, t)
            print(f"  [{t}] colunas: {list(c.keys())[:25]}")

# 5. Broader search — tables likely to have "no" + "data" + some state field
print("\n\n--- Tabelas com [no]+[data]+[aberto/fechado/anulado/concluido] ---")
cursor.execute("""
    SELECT DISTINCT t.TABLE_NAME
    FROM INFORMATION_SCHEMA.COLUMNS t
    WHERE EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME='no')
      AND EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME IN ('fdata','data'))
      AND EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME IN ('aberto','fechado','anulado','concluido','fecho','estado'))
      AND t.TABLE_NAME NOT LIKE 'BackUp%'
    ORDER BY t.TABLE_NAME
""")
state_tables = [r[0] for r in cursor.fetchall()]
print(f"Candidatas com no+data+estado: {state_tables}")
for t in state_tables:
    c = cols(cursor, t)
    state_cols = [k for k in c if k.lower() in ('aberto','fechado','anulado','concluido','fecho','estado')]
    print(f"  [{t}] estado-cols: {state_cols} | total-cols: {len(c)}")
    # Check if it has rows
    try:
        cursor.execute(f"SELECT COUNT(*) FROM [{t}]")
        cnt = cursor.fetchone()[0]
        if cnt > 0:
            print(f"     → {cnt} registos")
            s = sample(cursor, t, 1)
            for row in s:
                preview = {k: v for k, v in row.items() if k.lower() in
                           ('no','data','fdata','nome','cl','clno','aberto','fechado',
                            'anulado','concluido','fecho','serie','tipodoc','estado')}
                print(f"     Exemplo: {preview}")
    except: pass

conn.close()
print("\n✅ Análise concluída")
