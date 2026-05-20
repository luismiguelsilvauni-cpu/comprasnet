"""Explora a tabela mo (movimentos de stock) do PHC."""
from app import app
from models import ConfigPHC
from phc_sync import get_phc_connection

def cols(cur, t):
    cur.execute("SELECT COLUMN_NAME,DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION", t)
    return {r[0]: r[1] for r in cur.fetchall()}

with app.app_context():
    cfg = ConfigPHC.query.first()
    conn = get_phc_connection(cfg)
    cur = conn.cursor()

    # 1. Columns of mo
    print("=== mo — colunas ===")
    mo_cols = cols(cur, 'mo')
    print("Colunas:", list(mo_cols.keys()))

    # 2. Total records
    cur.execute("SELECT COUNT(*) FROM mo"); cnt = cur.fetchone()[0]
    print(f"Total registos: {cnt}")

    # 3. Distinct movement codes
    print("\n=== Códigos de movimento distintos (tipomov ou similar) ===")
    # Find the movement type column
    type_col = None
    for c in mo_cols:
        if c.lower() in ('tipomov','tpmov','tipo','codmov','codigo','cod','ndoc','nmov','descrmov','descri','obs','docnome'):
            print(f"  Candidata: [{c}] tipo={mo_cols[c]}")

    # Try to get distinct values for likely columns
    for c in ['tipomov','tpmov','tipo','cod','codmov','ndoc','nmov','obrano']:
        if c in mo_cols:
            try:
                cur.execute(f"SELECT DISTINCT [{c}], COUNT(*) FROM mo GROUP BY [{c}] ORDER BY COUNT(*) DESC")
                rows = cur.fetchall()
                print(f"\n  [{c}] distintos ({len(rows)} valores):")
                for r in rows[:15]:
                    print(f"    '{r[0]}' — {r[1]}")
            except Exception as e:
                print(f"  [{c}] erro: {e}")

    # 4. Entrada/Saída columns
    print("\n=== Colunas de Entrada/Saída ===")
    entry_cols = [c for c in mo_cols if c.lower() in ('entrada','entradas','saida','saidas','qtt','qttentrada','qttsaida','qttent','qttsa','quant','cantidad')]
    print("Candidatas:", entry_cols)

    # 5. Cost columns
    print("\n=== Colunas de Custo ===")
    cost_cols = [c for c in mo_cols if c.lower() in ('epv','preco','custo','ecusto','epcusto','epcpond','pcusto','pcpond','cmpond','cmunit','eunit','eval')]
    print("Candidatas:", cost_cols)

    # 6. Sample rows for article 049VC02
    print("\n=== Amostra: artigo 049VC02 ===")
    ref_col = None
    for c in ['ref','referencia','artigo','codigo']:
        if c in mo_cols:
            ref_col = c
            break
    if ref_col:
        try:
            cur.execute(f"SELECT TOP 10 * FROM mo WHERE [{ref_col}] = '049VC02' ORDER BY data DESC")
            rows = cur.fetchall()
            desc = [d[0] for d in cur.description]
            print(f"  Colunas: {desc}")
            for row in rows:
                d = dict(zip(desc, row))
                # Show only non-null/non-zero
                clean = {k: v for k,v in d.items() if v is not None and v != '' and v != 0 and v != False}
                print(f"  {clean}")
        except Exception as e:
            print(f"  Erro: {e}")
    else:
        print("  Coluna ref não encontrada!")
        print("  Todas as colunas:", list(mo_cols.keys()))

    # 7. Also try first 3 rows regardless of article
    print("\n=== Primeiros 3 registos de mo ===")
    cur.execute("SELECT TOP 3 * FROM mo")
    rows = cur.fetchall()
    desc = [d[0] for d in cur.description]
    print("Colunas:", desc)
    for row in rows:
        d = dict(zip(desc, row))
        clean = {k: v for k,v in d.items() if v is not None and v != '' and str(v) != '0' and str(v) != 'False'}
        print(" ", clean)

    conn.close()
