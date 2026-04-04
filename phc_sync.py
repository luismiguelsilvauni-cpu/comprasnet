"""
phc_sync.py
───────────
Ligação ao SQL Server Express local (BD PHC CS restaurada).
Lê artigos, fornecedores e histórico em modo só-leitura.

Estrutura desta BD PHC:
  st   → Artigos (ref, design, stock, pcusto, pcpond, unidade, familia, tabiva)
  cl   → Clientes/Fornecedores (no, nome, ncont, morada, local, codpost, telefone, email)
  ft   → Cabeçalho documentos (ftstamp, no, anulado, tipodoc)
  fi   → Linhas de documentos (ftstamp, ref, design, preco, qtt)
"""

import pyodbc
import logging
from datetime import datetime
from models import db, ArtigoPHC, FornecedorPHC, ConfigPHC

logger = logging.getLogger(__name__)

# ── Queries ───────────────────────────────────────────────────────────────────

SQL_ARTIGOS = """
SELECT
    st.ref                          AS referencia,
    st.design                       AS designacao,
    ISNULL(st.stock, 0)             AS stock_atual,
    COALESCE(NULLIF(st.epcusto,0),
             (SELECT TOP 1 fi.ecusto FROM fi INNER JOIN ft ON ft.ftstamp=fi.ftstamp
              WHERE fi.ref=st.ref AND ft.anulado=0 AND fi.ecusto>0 ORDER BY ft.fdata DESC),
             0)                                                     AS preco_custo,
    COALESCE(NULLIF(st.epcpond,0), NULLIF(st.epcusto,0), NULLIF(st.epcult,0), 0) AS preco_custo_ponderado,
    ISNULL(st.unidade, '')          AS unidade,
    ISNULL(st.familia, '')          AS familia,
    ISNULL(st.tabiva, 23)           AS taxa_iva,
    ISNULL(st.epv1, 0)              AS pvp,
    (SELECT TOP 1 ISNULL(fi.ecusto,0)
     FROM fi INNER JOIN ft ON ft.ftstamp=fi.ftstamp
     WHERE fi.ref=st.ref AND ft.anulado=0 AND fi.ecusto>0
     ORDER BY ft.fdata DESC)        AS ultimo_preco_entrada,
    ISNULL(st.inactivo, 0)          AS inactivo,
    st.ststamp                      AS stamp
FROM st
WHERE ISNULL(st.inactivo, 0) = 0
  AND st.ref IS NOT NULL
  AND LEN(LTRIM(RTRIM(st.ref))) > 0
ORDER BY st.ref
"""

SQL_FORNECEDORES = """
SELECT DISTINCT
    fo.no                           AS numero,
    fo.nome                         AS nome,
    ISNULL(fo.ncont, '')            AS nif,
    ISNULL(fo.morada, '')           AS morada,
    ISNULL(fo.local, '')            AS localidade,
    ISNULL(fo.codpost, '')          AS cod_postal,
    ''                              AS telefone,
    ''                              AS email,
    0                               AS inactivo,
    fo.fostamp                      AS stamp
FROM fo
WHERE fo.nome IS NOT NULL
  AND LEN(LTRIM(RTRIM(fo.nome))) > 0
ORDER BY fo.nome
"""

SQL_HISTORICO_COMPRAS = """
SELECT TOP 20
    fi.ref                          AS referencia,
    cl.nome                         AS fornecedor_nome,
    fi.no                           AS fornecedor_no,
    ISNULL(fi.preco, 0)             AS preco,
    ISNULL(fi.desconto, 0)          AS desconto,
    ISNULL(fi.qtt, 0)               AS quantidade,
    ft.data                         AS data_compra,
    ft.no                           AS num_documento
FROM fi
INNER JOIN ft ON ft.ftstamp = fi.ftstamp
LEFT  JOIN cl ON cl.no = ft.no
WHERE fi.ref = ?
  AND ft.anulado = 0
ORDER BY ft.data DESC
"""

SQL_VENDAS_CLIENTE = """
SELECT TOP 100
    fi.ref                          AS ref,
    fi.design                       AS design,
    ISNULL(fi.qtt, 0)               AS qtt,
    ISNULL(fi.preco, 0)             AS preco,
    ft.data                         AS data,
    ft.no                           AS fno,
    ft.serie                        AS serie
FROM fi
INNER JOIN ft ON ft.ftstamp = fi.ftstamp
WHERE ft.no = ?
  AND ft.anulado = 0
  AND (fi.ref LIKE ? OR fi.design LIKE ?)
  AND fi.ref IS NOT NULL AND fi.ref <> ''
ORDER BY ft.data DESC
"""

# ── Connection ────────────────────────────────────────────────────────────────

def get_phc_connection(config):
    """Create pyodbc connection using ConfigPHC settings."""
    servidor   = (config.servidor or r'.\SQLEXPRESS').replace('localhost\\', '.\\')
    base_dados = config.base_dados or 'PHC_Uniao'
    driver     = getattr(config, 'driver', None) or 'ODBC Driver 17 for SQL Server'

    for drv in [driver, 'ODBC Driver 17 for SQL Server',
                'ODBC Driver 13 for SQL Server', 'SQL Server']:
        try:
            conn_str = (f'DRIVER={{{drv}}};SERVER={servidor};'
                        f'DATABASE={base_dados};Trusted_Connection=yes;'
                        f'Connection Timeout=10;')
            return pyodbc.connect(conn_str)
        except Exception:
            continue
    raise Exception(f"Não foi possível ligar a {servidor}/{base_dados}")


def test_connection(config):
    """Test connection and return (ok, message)."""
    try:
        conn   = get_phc_connection(config)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM st WHERE ISNULL(inactivo,0)=0 AND ref IS NOT NULL AND ref <> ''")
        count = cursor.fetchone()[0]
        conn.close()
        return True, f"Ligação OK — {count} artigos activos na BD PHC."
    except Exception as e:
        return False, str(e)


# ── Sync functions ─────────────────────────────────────────────────────────────

def sync_artigos(config) -> tuple[int, int, list]:
    """Sync PHC articles to local SQLite. Returns (inserted, updated, errors)."""
    conn   = get_phc_connection(config)
    cursor = conn.cursor()
    cursor.execute(SQL_ARTIGOS)
    rows   = cursor.fetchall()
    conn.close()

    inserted = updated = 0
    errors = []

    for r in rows:
        try:
            ref = str(r.referencia or '').strip()
            if not ref:
                continue
            existing = ArtigoPHC.query.filter_by(referencia=ref).first()
            if existing:
                existing.designacao              = str(r.designacao or '')
                existing.stock_atual             = float(r.stock_atual or 0)
                existing.preco_custo             = float(r.preco_custo or 0)
                existing.preco_custo_ponderado   = float(r.preco_custo_ponderado or 0)
                existing.unidade                 = str(r.unidade or '')
                existing.familia                 = str(r.familia or '')
                existing.taxa_iva                = float(r.taxa_iva or 23)
                existing.pvp                     = float(r.pvp or 0)
                existing.ultimo_preco_entrada    = float(r.ultimo_preco_entrada or 0)
                updated += 1
            else:
                db.session.add(ArtigoPHC(
                    referencia             = ref,
                    designacao             = str(r.designacao or ''),
                    stock_atual            = float(r.stock_atual or 0),
                    preco_custo            = float(r.preco_custo or 0),
                    preco_custo_ponderado  = float(r.preco_custo_ponderado or 0),
                    unidade                = str(r.unidade or ''),
                    familia                = str(r.familia or ''),
                    taxa_iva               = float(r.taxa_iva or 23),
                    pvp                    = float(r.pvp or 0),
                    ultimo_preco_entrada   = float(r.ultimo_preco_entrada or 0),
                ))
                inserted += 1
        except Exception as e:
            errors.append(f"{ref}: {e}")

    if inserted or updated:
        db.session.commit()
    return inserted, updated, errors


def sync_fornecedores(config) -> tuple[int, int, list]:
    """Sync PHC suppliers to local SQLite."""
    conn   = get_phc_connection(config)
    cursor = conn.cursor()
    cursor.execute(SQL_FORNECEDORES)
    rows   = cursor.fetchall()
    conn.close()

    inserted = updated = 0
    errors = []

    for r in rows:
        try:
            no = int(r.numero or 0)
            if not no:
                continue
            existing = FornecedorPHC.query.filter_by(numero=no).first()
            nome = str(r.nome or '').strip()
            if existing:
                existing.nome       = nome
                existing.nif        = str(r.nif or '')
                existing.morada     = str(r.morada or '')
                existing.localidade = str(r.localidade or '')
                existing.cod_postal = str(r.cod_postal or '')
                existing.telefone   = str(r.telefone or '')
                existing.email      = str(r.email or '')
                updated += 1
            else:
                db.session.add(FornecedorPHC(
                    numero      = no,
                    nome        = nome,
                    nif         = str(r.nif or ''),
                    morada      = str(r.morada or ''),
                    localidade  = str(r.localidade or ''),
                    cod_postal  = str(r.cod_postal or ''),
                    telefone    = str(r.telefone or ''),
                    email       = str(r.email or ''),
                ))
                inserted += 1
        except Exception as e:
            errors.append(str(e))

    if inserted or updated:
        db.session.commit()
    return inserted, updated, errors


SQL_CLIENTES = """
SELECT
    cl.no                           AS numero,
    cl.nome                         AS nome,
    ISNULL(cl.ncont, '')            AS nif,
    ISNULL(cl.morada, '')           AS morada,
    ISNULL(cl.local, '')            AS localidade,
    ISNULL(cl.codpost, '')          AS cod_postal,
    ISNULL(cl.telefone, '')         AS telefone,
    ISNULL(cl.email, '')            AS email,
    ISNULL(cl.inactivo, 0)          AS inactivo,
    cl.clstamp                      AS stamp
FROM cl
WHERE ISNULL(cl.inactivo, 0) = 0
  AND cl.nome IS NOT NULL
  AND LEN(LTRIM(RTRIM(cl.nome))) > 0
ORDER BY cl.nome
"""


def sync_clientes(config) -> tuple[int, int, list]:
    """Sync PHC clients to local SQLite Cliente table."""
    from models import Cliente
    conn   = get_phc_connection(config)
    cursor = conn.cursor()
    cursor.execute(SQL_CLIENTES)
    rows   = cursor.fetchall()
    conn.close()

    inserted = updated = 0
    errors = []

    for r in rows:
        try:
            no = int(r.numero or 0)
            if not no:
                continue
            nome = str(r.nome or '').strip()
            existing = Cliente.query.filter_by(phc_no=no).first()
            if existing:
                existing.nome       = nome
                existing.nif        = str(r.nif or '')
                existing.morada     = str(r.morada or '')
                existing.localidade = str(r.localidade or '')
                existing.cod_postal = str(r.cod_postal or '')
                existing.telefone   = str(r.telefone or '')
                existing.email      = str(r.email or '')
                updated += 1
            else:
                db.session.add(Cliente(
                    phc_no      = no,
                    nome        = nome,
                    nif         = str(r.nif or ''),
                    morada      = str(r.morada or ''),
                    localidade  = str(r.localidade or ''),
                    cod_postal  = str(r.cod_postal or ''),
                    telefone    = str(r.telefone or ''),
                    email       = str(r.email or ''),
                ))
                inserted += 1
        except Exception as e:
            errors.append(str(e))

    if inserted or updated:
        db.session.commit()
    return inserted, updated, errors


def get_historico_compras(config, ref: str) -> list:
    """Get purchase history for an article."""
    try:
        conn   = get_phc_connection(config)
        cursor = conn.cursor()
        cursor.execute(SQL_HISTORICO_COMPRAS, ref)
        rows   = cursor.fetchall()
        conn.close()
        return [{
            'fornecedor_nome': str(r.fornecedor_nome or ''),
            'fornecedor_no':   r.fornecedor_no,
            'preco':           float(r.preco or 0),
            'desconto':        float(r.desconto or 0),
            'quantidade':      float(r.quantidade or 0),
            'data_compra':     r.data_compra.strftime('%d/%m/%Y') if r.data_compra else '',
            'num_documento':   str(r.num_documento or ''),
        } for r in rows]
    except Exception as e:
        logger.error(f"Erro historico compras {ref}: {e}")
        return []


def get_vendas_cliente(config, cl_no: int, q: str = '') -> list:
    """Get sales history for a client."""
    try:
        conn   = get_phc_connection(config)
        cursor = conn.cursor()
        like   = f'%{q}%' if q else '%'
        cursor.execute(SQL_VENDAS_CLIENTE, cl_no, like, like)
        rows   = cursor.fetchall()
        conn.close()
        return [{
            'ref':    str(r.ref or ''),
            'design': str(r.design or ''),
            'qtt':    float(r.qtt or 0),
            'preco':  float(r.preco or 0),
            'data':   r.data.strftime('%d/%m/%Y') if r.data else '',
            'doc':    f"{r.serie or ''}{r.fno or ''}",
        } for r in rows]
    except Exception as e:
        logger.error(f"Erro vendas cliente {cl_no}: {e}")
        return []
