"""
phc_sync.py
───────────
Ligação ao SQL Server Express local onde o .bak do PHC CS é restaurado.
Lê artigos, fornecedores e última compra em modo só-leitura.
Sincroniza para tabelas locais SQLite usadas pelo ComprasNet.

Tabelas PHC CS utilizadas (só leitura):
  st   → Artigos (stock)
  ec   → Entidades / Fornecedores
  lc   → Linhas de compra (para último preço)
  ft   → Cabeçalho de documentos de compra
"""

import pyodbc
import logging
from datetime import datetime
from models import db, ArtigoPHC, FornecedorPHC, ConfigPHC

logger = logging.getLogger(__name__)

# ── Queries PHC CS ────────────────────────────────────────────────────────────

SQL_ARTIGOS = """
SELECT
    st.ref                          AS referencia,
    st.design                       AS designacao,
    ISNULL(st.qtt, 0)               AS stock_atual,
    ISNULL(st.pcusto, 0)            AS preco_custo,
    ISNULL(st.pcp, 0)               AS preco_custo_ponderado,
    ISNULL(st.unidade, '')          AS unidade,
    ISNULL(st.familia, '')          AS familia,
    ISNULL(st.iva, 23)              AS taxa_iva,
    ISNULL(st.inactivo, 0)          AS inactivo,
    st.stamp                        AS stamp
FROM st
WHERE ISNULL(st.inactivo, 0) = 0
  AND st.ref IS NOT NULL
  AND LEN(LTRIM(RTRIM(st.ref))) > 0
ORDER BY st.ref
"""

SQL_FORNECEDORES = """
SELECT
    ec.no                           AS numero,
    ec.nome                         AS nome,
    ISNULL(ec.nipc, '')             AS nif,
    ISNULL(ec.morada, '')           AS morada,
    ISNULL(ec.local, '')            AS localidade,
    ISNULL(ec.codpost, '')          AS cod_postal,
    ISNULL(ec.tel, '')              AS telefone,
    ISNULL(ec.email, '')            AS email,
    ISNULL(ec.vendedor, '')         AS vendedor,
    ISNULL(ec.inactivo, 0)          AS inactivo,
    ec.stamp                        AS stamp
FROM ec
WHERE ISNULL(ec.inactivo, 0) = 0
  AND ec.fornecedor = 1
ORDER BY ec.nome
"""

SQL_ULTIMO_PRECO = """
SELECT
    lc.ref                          AS referencia,
    ec.nome                         AS fornecedor_nome,
    ec.no                           AS fornecedor_no,
    lc.preco                        AS preco,
    lc.desconto                     AS desconto,
    lc.ettot                        AS total_linha,
    ft.data                         AS data_compra,
    ft.fno                          AS num_documento
FROM lc
INNER JOIN ft ON ft.ftstamp = lc.ftstamp
INNER JOIN ec ON ec.no = ft.no
WHERE lc.ref = ?
  AND ft.anulado = 0
ORDER BY ft.data DESC, ft.fno DESC
"""

# ── Connection ────────────────────────────────────────────────────────────────

def get_phc_connection(config: ConfigPHC):
    """Create pyodbc connection to local SQL Server Express."""
    drivers = [
        'ODBC Driver 18 for SQL Server',
        'ODBC Driver 17 for SQL Server',
        'SQL Server Native Client 11.0',
        'SQL Server',
    ]
    
    last_error = None
    for driver in drivers:
        try:
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={config.servidor},{config.porta};"
                f"DATABASE={config.base_dados};"
            )
            if config.autenticacao == 'windows':
                conn_str += "Trusted_Connection=yes;"
            else:
                conn_str += f"UID={config.utilizador};PWD={config.password};"
            
            if driver == 'ODBC Driver 18 for SQL Server':
                conn_str += "TrustServerCertificate=yes;"
            
            conn = pyodbc.connect(conn_str, timeout=10)
            logger.info(f"PHC ligado via driver: {driver}")
            return conn
        except pyodbc.Error as e:
            last_error = e
            continue
    
    raise ConnectionError(f"Não foi possível ligar ao SQL Server. Último erro: {last_error}")


def test_connection(config: ConfigPHC) -> tuple[bool, str]:
    """Test PHC connection. Returns (success, message)."""
    try:
        conn = get_phc_connection(config)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM st WHERE ISNULL(inactivo,0)=0")
        count = cursor.fetchone()[0]
        conn.close()
        return True, f"Ligação OK — {count} artigos ativos encontrados na base PHC."
    except ConnectionError as e:
        return False, str(e)
    except pyodbc.Error as e:
        return False, f"Erro SQL: {str(e)}"
    except Exception as e:
        return False, f"Erro inesperado: {str(e)}"


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync_artigos(app, config: ConfigPHC) -> dict:
    """Sync artigos from PHC to local SQLite. Returns stats dict."""
    stats = {'inseridos': 0, 'atualizados': 0, 'erros': 0, 'total_phc': 0}
    
    try:
        conn = get_phc_connection(config)
        cursor = conn.cursor()
        cursor.execute(SQL_ARTIGOS)
        rows = cursor.fetchall()
        conn.close()
        stats['total_phc'] = len(rows)
    except Exception as e:
        raise RuntimeError(f"Erro ao ler artigos do PHC: {e}")
    
    with app.app_context():
        for row in rows:
            try:
                ref = str(row.referencia).strip()
                artigo = ArtigoPHC.query.filter_by(referencia=ref).first()
                
                if artigo:
                    # Update
                    artigo.designacao = str(row.designacao or '').strip()
                    artigo.stock_atual = float(row.stock_atual or 0)
                    artigo.preco_custo = float(row.preco_custo or 0)
                    artigo.preco_custo_ponderado = float(row.preco_custo_ponderado or 0)
                    artigo.unidade = str(row.unidade or 'un').strip()
                    artigo.familia = str(row.familia or '').strip()
                    artigo.taxa_iva = float(row.taxa_iva or 23)
                    artigo.ultima_sync = datetime.utcnow()
                    stats['atualizados'] += 1
                else:
                    # Insert
                    artigo = ArtigoPHC(
                        referencia=ref,
                        designacao=str(row.designacao or '').strip(),
                        stock_atual=float(row.stock_atual or 0),
                        preco_custo=float(row.preco_custo or 0),
                        preco_custo_ponderado=float(row.preco_custo_ponderado or 0),
                        unidade=str(row.unidade or 'un').strip(),
                        familia=str(row.familia or '').strip(),
                        taxa_iva=float(row.taxa_iva or 23),
                        ultima_sync=datetime.utcnow()
                    )
                    db.session.add(artigo)
                    stats['inseridos'] += 1
            except Exception as e:
                logger.warning(f"Erro artigo {row.referencia}: {e}")
                stats['erros'] += 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise RuntimeError(f"Erro ao gravar artigos: {e}")

    return stats


def sync_fornecedores(app, config: ConfigPHC) -> dict:
    """Sync fornecedores from PHC to local SQLite."""
    stats = {'inseridos': 0, 'atualizados': 0, 'erros': 0, 'total_phc': 0}

    try:
        conn = get_phc_connection(config)
        cursor = conn.cursor()
        cursor.execute(SQL_FORNECEDORES)
        rows = cursor.fetchall()
        conn.close()
        stats['total_phc'] = len(rows)
    except Exception as e:
        raise RuntimeError(f"Erro ao ler fornecedores do PHC: {e}")

    with app.app_context():
        for row in rows:
            try:
                forn = FornecedorPHC.query.filter_by(numero=int(row.numero)).first()
                if forn:
                    forn.nome        = str(row.nome or '').strip()
                    forn.nif         = str(row.nif or '').strip()
                    forn.morada      = str(row.morada or '').strip()
                    forn.localidade  = str(row.localidade or '').strip()
                    forn.cod_postal  = str(row.cod_postal or '').strip()
                    forn.telefone    = str(row.telefone or '').strip()
                    forn.email       = str(row.email or '').strip()
                    forn.ultima_sync = datetime.utcnow()
                    stats['atualizados'] += 1
                else:
                    forn = FornecedorPHC(
                        numero      = int(row.numero),
                        nome        = str(row.nome or '').strip(),
                        nif         = str(row.nif or '').strip(),
                        morada      = str(row.morada or '').strip(),
                        localidade  = str(row.localidade or '').strip(),
                        cod_postal  = str(row.cod_postal or '').strip(),
                        telefone    = str(row.telefone or '').strip(),
                        email       = str(row.email or '').strip(),
                        ultima_sync = datetime.utcnow()
                    )
                    db.session.add(forn)
                    stats['inseridos'] += 1
            except Exception as e:
                logger.warning(f"Erro fornecedor {row.numero}: {e}")
                stats['erros'] += 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise RuntimeError(f"Erro ao gravar fornecedores: {e}")

    return stats


def get_historico_compras(config: ConfigPHC, referencia: str) -> list[dict]:
    """Return purchase history for a given article reference."""
    try:
        conn = get_phc_connection(config)
        cursor = conn.cursor()
        cursor.execute(SQL_ULTIMO_PRECO, referencia)
        rows = cursor.fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                'fornecedor_nome': r.fornecedor_nome,
                'fornecedor_no':   r.fornecedor_no,
                'preco':           float(r.preco or 0),
                'desconto':        float(r.desconto or 0),
                'total_linha':     float(r.total_linha or 0),
                'data_compra':     r.data_compra.strftime('%d/%m/%Y') if r.data_compra else '—',
                'num_documento':   r.num_documento,
            })
        return result
    except Exception as e:
        logger.warning(f"Erro histórico compras {referencia}: {e}")
        return []


def sync_all(app, config: ConfigPHC) -> dict:
    """Full sync: artigos + fornecedores. Returns combined stats."""
    result = {'artigos': {}, 'fornecedores': {}, 'data_sync': datetime.utcnow().strftime('%d/%m/%Y %H:%M')}
    result['artigos']      = sync_artigos(app, config)
    result['fornecedores'] = sync_fornecedores(app, config)

    with app.app_context():
        config.ultima_sync = datetime.utcnow()
        db.session.commit()

    return result
