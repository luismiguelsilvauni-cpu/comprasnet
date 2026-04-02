"""
setup_phc.py
────────────
Script completo que:
1. Liga ao SQL Server
2. Analisa toda a estrutura da BD PHC
3. Corrige o phc_sync.py automaticamente
4. Testa a sincronização
5. Configura o ComprasNet

Execute: .\venv\Scripts\python.exe setup_phc.py
"""

import sys, os, json, subprocess

SERVER   = r'.\SQLEXPRESS'
DATABASE = 'PHC_Uniao'

# ── Install dependencies ──────────────────────────────────────
for pkg in ['pyodbc']:
    try:
        __import__(pkg)
    except ImportError:
        print(f"A instalar {pkg}...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

import pyodbc

def connect():
    for driver in ['ODBC Driver 17 for SQL Server', 'ODBC Driver 13 for SQL Server', 'SQL Server']:
        try:
            conn_str = f'DRIVER={{{driver}}};SERVER={SERVER};DATABASE={DATABASE};Trusted_Connection=yes;'
            return pyodbc.connect(conn_str, timeout=10)
        except Exception:
            continue
    raise Exception("Não foi possível ligar. Verifique que o SQL Server está activo.")

def cols(cursor, table):
    cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION", table)
    return [r[0] for r in cursor.fetchall()]

def find(available, candidates):
    for c in candidates:
        if c in available:
            return c
    return None

def test_query(cursor, sql, params=None):
    try:
        cursor.execute(sql, params or [])
        return cursor.fetchall(), None
    except Exception as e:
        return None, str(e)

print("=" * 65)
print("  ComprasNet — Setup automático PHC CS")
print("=" * 65)

# ── Connect ───────────────────────────────────────────────────
try:
    conn = connect()
    cursor = conn.cursor()
    print("✅ SQL Server ligado")
except Exception as e:
    print(f"❌ {e}")
    sys.exit(1)

# ── Discover all tables ───────────────────────────────────────
cursor.execute("SELECT name FROM sysobjects WHERE type='U' ORDER BY name")
all_tables = {r[0] for r in cursor.fetchall()}

# ── ARTIGOS (st) ──────────────────────────────────────────────
print("\n📦 Artigos...")
st_cols = cols(cursor, 'st')
st = {
    'tabela':      'st',
    'ref':         find(st_cols, ['ref','referencia','codigo']),
    'design':      find(st_cols, ['design','designacao','descricao','nome']),
    'stock':       find(st_cols, ['stock','qtt','qty','stkactual','quant','quantidade']),
    'pcusto':      find(st_cols, ['pcusto','preco','pcompra','prc','pcusto1']),
    'pcp':         find(st_cols, ['pcpond','pcp','pcustopond','pcponderad']),
    'unidade':     find(st_cols, ['unidade','uni','unid']),
    'familia':     find(st_cols, ['familia','fami','grupo','grp','cat']),
    'tabiva':      find(st_cols, ['tabiva','taxa','iva','txiva','codiva']),
    'inactivo':    find(st_cols, ['inactivo','inativo','activo','ativo']),
    'stamp':       find(st_cols, ['ststamp','stamp']),
}
rows, err = test_query(cursor, f"SELECT TOP 1 {st['ref']}, {st['design']}, {st['stock']} FROM st WHERE {st['ref']} IS NOT NULL AND {st['ref']} <> ''")
if rows:
    print(f"   ✅ {rows[0][0]} | {rows[0][1][:40]} | stock={rows[0][2]}")
else:
    print(f"   ❌ {err}")

# ── ENTIDADES/FORNECEDORES ────────────────────────────────────
print("\n👥 Entidades/Fornecedores...")
# Try cl first (clientes/fornecedores), then ec
ent_table = None
for tbl in ['cl', 'ec']:
    if tbl in all_tables:
        t_cols = cols(cursor, tbl)
        if find(t_cols, ['nome','name']):
            ent_table = tbl
            ent_cols_list = t_cols
            break

if not ent_table:
    ent_table = 'cl'
    ent_cols_list = cols(cursor, 'cl') if 'cl' in all_tables else []

ent = {
    'tabela':     ent_table,
    'no':         find(ent_cols_list, ['no','numero','cod','codigo']),
    'nome':       find(ent_cols_list, ['nome','name','designacao','razaosocial']),
    'ncont':      find(ent_cols_list, ['ncont','nipc','nif','contribuinte','cif','fiscal']),
    'morada':     find(ent_cols_list, ['morada','endereco','address','rua']),
    'local':      find(ent_cols_list, ['local','localidade','cidade','city']),
    'codpost':    find(ent_cols_list, ['codpost','cp','cpostal','codigopostal','zipcode']),
    'telefone':   find(ent_cols_list, ['telefone','tel','telef','phone','telf']),
    'tlm':        find(ent_cols_list, ['tlm','telemovel','mobile','tele2','telem']),
    'email':      find(ent_cols_list, ['email','mail','correio']),
    'fornecedor': find(ent_cols_list, ['fornecedor','forn','supplier','isforncedor']),
    'cliente':    find(ent_cols_list, ['cliente','client','customer','iscliente']),
    'inactivo':   find(ent_cols_list, ['inactivo','inativo','activo','ativo']),
    'stamp':      find(ent_cols_list, ['clstamp','ecstamp','stamp']),
}

# Test suppliers
forn_field = ent['fornecedor']
forn_filter = f"AND {forn_field}=1" if forn_field else ""
rows, err = test_query(cursor, f"SELECT TOP 3 {ent['no']}, {ent['nome']}, ISNULL({ent['ncont'] or ent['no']},'') FROM {ent_table} WHERE {ent['nome']} IS NOT NULL {forn_filter}")
if rows:
    for r in rows:
        print(f"   ✅ Fornecedor: {r[0]} | {r[1][:40]}")
else:
    print(f"   ⚠️  {err} — tentando sem filtro fornecedor")
    rows, err = test_query(cursor, f"SELECT TOP 3 {ent['no']}, {ent['nome']} FROM {ent_table} WHERE {ent['nome']} IS NOT NULL AND {ent['nome']} <> ''")
    if rows:
        for r in rows: print(f"   ✅ {r[0]} | {r[1][:40]}")

# ── DOCUMENTOS (ft) ───────────────────────────────────────────
print("\n📄 Documentos...")
ft_cols = cols(cursor, 'ft')
ft = {
    'tabela':  'ft',
    'stamp':   find(ft_cols, ['ftstamp','stamp']),
    'no':      find(ft_cols, ['no','fno','numero','ndoc']),
    'data':    find(ft_cols, ['data','date','datadoc','dtdoc']),
    'ent_no':  find(ft_cols, ['clno','ecno','no','entno','fno']),
    'anulado': find(ft_cols, ['anulado','anulada','cancelado']),
    'serie':   find(ft_cols, ['serie','ser']),
    'tipodoc': find(ft_cols, ['tipodoc','tipo','tpdoc','tpdocumento']),
}
rows, err = test_query(cursor, f"SELECT TOP 1 {ft['stamp']}, {ft['no']}, {ft['data']} FROM ft WHERE {ft['anulado']}=0")
if rows:
    print(f"   ✅ Doc: stamp={str(rows[0][0])[:20]} no={rows[0][1]} data={rows[0][2]}")
else:
    print(f"   ⚠️  {err}")

# ── LINHAS DOCUMENTOS ─────────────────────────────────────────
print("\n📋 Linhas de documentos...")
cursor.execute("""
    SELECT DISTINCT t.TABLE_NAME 
    FROM INFORMATION_SCHEMA.COLUMNS t
    WHERE t.TABLE_NAME NOT LIKE 'BackUp%'
    AND t.TABLE_NAME NOT LIKE 'a_%'
    AND EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME='ftstamp')
    AND EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=t.TABLE_NAME AND COLUMN_NAME='ref')
    ORDER BY t.TABLE_NAME
""")
line_candidates = [r[0] for r in cursor.fetchall()]

best_line = None
for tbl in line_candidates:
    t_cols = cols(cursor, tbl)
    preco = find(t_cols, ['preco','epv','pvenda','prc','price','valor','precou'])
    qtt   = find(t_cols, ['qtt','qty','quant','quantidade','qttot'])
    design = find(t_cols, ['design','designacao','descricao','nome'])
    stamp  = find(t_cols, [f'{tbl}stamp','stamp'])
    if preco and qtt:
        best_line = {'tabela': tbl, 'ftstamp': 'ftstamp', 'ref': 'ref',
                     'design': design, 'preco': preco, 'qtt': qtt, 'stamp': stamp,
                     'desconto': find(t_cols, ['desconto','desc','discount'])}
        rows, err = test_query(cursor, f"SELECT TOP 1 ref, {preco}, {qtt} FROM {tbl} WHERE ref IS NOT NULL AND ref <> ''")
        if rows:
            print(f"   ✅ {tbl}: ref={rows[0][0]} preco={rows[0][1]} qtt={rows[0][2]}")
            break

if not best_line:
    print(f"   ⚠️  Não encontrada. Candidatas: {line_candidates}")
    # Show columns for top candidates
    for tbl in line_candidates[:3]:
        t_cols = cols(cursor, tbl)
        print(f"      {tbl}: {t_cols[:10]}")

# ── VENDAS (historico artigos vendidos a clientes) ────────────
print("\n💰 Histórico vendas a clientes...")
# Try ft + linhas for sales (tipodoc = FA, FT, FR etc)
if best_line:
    tbl = best_line['tabela']
    rows, err = test_query(cursor, f"""
        SELECT TOP 3 l.ref, l.{best_line['preco']}, f.{ft['data']}
        FROM {tbl} l 
        INNER JOIN ft f ON f.ftstamp = l.ftstamp
        WHERE f.{ft['anulado']}=0 AND l.ref IS NOT NULL AND l.ref <> ''
        ORDER BY f.{ft['data']} DESC
    """)
    if rows:
        for r in rows: print(f"   ✅ ref={r[0]} preco={r[1]} data={r[2]}")
    else:
        print(f"   ⚠️  {err}")

# ── MOVIMENTOS STOCK (mo) ─────────────────────────────────────
print("\n📊 Movimentos de stock...")
mo_map = None
if 'mo' in all_tables:
    mo_cols = cols(cursor, 'mo')
    mo_ref   = find(mo_cols, ['ref','referencia'])
    mo_qtt   = find(mo_cols, ['qtt','qty','quant','quantidade'])
    mo_data  = find(mo_cols, ['data','date'])
    mo_tipo  = find(mo_cols, ['tipo','tpmov','tipomov','tpdoc'])
    if mo_ref and mo_qtt:
        mo_map = {'ref': mo_ref, 'qtt': mo_qtt, 'data': mo_data, 'tipo': mo_tipo}
        rows, _ = test_query(cursor, f"SELECT TOP 1 {mo_ref}, {mo_qtt} FROM mo WHERE {mo_ref} IS NOT NULL")
        if rows: print(f"   ✅ mo: ref={rows[0][0]} qtt={rows[0][1]}")
    else:
        print(f"   ⚠️  Campos em falta: ref={mo_ref} qtt={mo_qtt}")
        print(f"      Campos disponíveis: {mo_cols[:15]}")
else:
    print("   ℹ️  Tabela mo não existe nesta BD")

# ── Save complete mapping ─────────────────────────────────────
mapping = {
    'server': SERVER, 'database': DATABASE,
    'st': st, 'ent': ent, 'ft': ft,
    'linhas': best_line, 'mo': mo_map
}
with open('phc_mapping.json', 'w', encoding='utf-8') as f:
    json.dump(mapping, f, indent=2, ensure_ascii=False)

# ── Generate corrected phc_sync.py ───────────────────────────
print("\n🔧 A corrigir phc_sync.py...")

# Read current phc_sync.py
try:
    with open('phc_sync.py', 'r', encoding='utf-8') as f:
        sync_src = f.read()
except:
    with open('phc_sync.py', 'r') as f:
        sync_src = f.read()

# Fix st table
sync_src = sync_src.replace(
    "ISNULL(st.qtt, 0)               AS stock_atual,",
    f"ISNULL(st.{st['stock']}, 0)             AS stock_atual,"
)
sync_src = sync_src.replace(
    "ISNULL(st.stock, 0)             AS stock_atual,",
    f"ISNULL(st.{st['stock']}, 0)             AS stock_atual,"
)
sync_src = sync_src.replace(
    "ISNULL(st.pcp, 0)               AS preco_custo_ponderado,",
    f"ISNULL(st.{st['pcp'] or st['pcusto']}, 0)    AS preco_custo_ponderado,"
)
sync_src = sync_src.replace(
    "ISNULL(st.pcpond, 0)            AS preco_custo_ponderado,",
    f"ISNULL(st.{st['pcp'] or st['pcusto']}, 0)    AS preco_custo_ponderado,"
)
sync_src = sync_src.replace(
    "ISNULL(st.iva, 23)              AS taxa_iva,",
    f"ISNULL(st.{st['tabiva'] or '23'}, 23)    AS taxa_iva,"
)

# Fix ec -> correct entity table
if ent_table != 'ec':
    sync_src = sync_src.replace('FROM ec\n', f'FROM {ent_table}\n')
    sync_src = sync_src.replace('FROM ec ', f'FROM {ent_table} ')

# Fix entity columns
sync_src = sync_src.replace(
    "    ISNULL(ec.nipc, '')             AS nif,",
    f"    ISNULL({ent_table}.{ent['ncont'] or ent['no']},'')    AS nif,"
)
sync_src = sync_src.replace(
    "    ISNULL(ec.ncont, '')            AS nif,",
    f"    ISNULL({ent_table}.{ent['ncont'] or ent['no']},'')    AS nif,"
)
sync_src = sync_src.replace(
    "    ISNULL(ec.tel, '')              AS telefone,",
    f"    ISNULL({ent_table}.{ent['telefone'] or ent['no']},'')  AS telefone,"
)
sync_src = sync_src.replace(
    "    ISNULL(ec.telefone, '')         AS telefone,",
    f"    ISNULL({ent_table}.{ent['telefone'] or ent['no']},'')  AS telefone,"
)

# Fix fornecedor filter
if ent['fornecedor']:
    sync_src = sync_src.replace(
        "  AND ec.fornecedor = 1",
        f"  AND {ent_table}.{ent['fornecedor']} = 1"
    )
elif ent_table == 'cl':
    # cl table might use different filter
    sync_src = sync_src.replace(
        "  AND ec.fornecedor = 1",
        f"  AND 1=1  -- cl table, no fornecedor filter needed"
    )

with open('phc_sync.py', 'w', encoding='utf-8') as f:
    f.write(sync_src)
print("   ✅ phc_sync.py corrigido")

# ── Configure ComprasNet DB ───────────────────────────────────
print("\n⚙️  A configurar ligação no ComprasNet...")
try:
    sys.path.insert(0, os.getcwd())
    from app import app, db, init_db
    from models import ConfigPHC
    init_db()
    with app.app_context():
        cfg = ConfigPHC.query.first()
        if not cfg:
            cfg = ConfigPHC()
            db.session.add(cfg)
        cfg.servidor    = SERVER.replace('.\\', 'localhost\\')
        cfg.base_dados  = DATABASE
        cfg.driver      = 'ODBC Driver 17 for SQL Server'
        cfg.ultima_sync = None
        db.session.commit()
        print(f"   ✅ ConfigPHC: {cfg.servidor} / {cfg.base_dados}")
except Exception as e:
    print(f"   ⚠️  Config manual necessária: {e}")
    print(f"   → Admin → PHC CS: servidor={SERVER} BD={DATABASE}")

# ── Final summary ─────────────────────────────────────────────
print("\n" + "=" * 65)
print("✅ Setup completo!")
print(f"   Artigos:      tabela {st['tabela']} (ref={st['ref']}, stock={st['stock']})")
print(f"   Entidades:    tabela {ent['tabela']} (no={ent['no']}, nome={ent['nome']})")
print(f"   Documentos:   tabela ft")
if best_line:
    print(f"   Linhas docs:  tabela {best_line['tabela']} (ref=ref, preco={best_line['preco']})")
print("\n→ Reinicie o ComprasNet e vá a Admin → PHC CS → Sincronizar")
print("=" * 65)
conn.close()
