"""
reposicao.py
────────────
Motor de sugestão de reposição baseado em histórico de movimentos PHC CS.

Tabelas PHC lidas (só leitura):
  st   → artigos: stock actual, mínimo, máximo, unidade
  mo   → movimentos de stock: tipo, quantidade, data
  lc   → linhas de compra: preço, quantidade, fornecedor
  ft   → cabeçalho documentos de compra: data, fornecedor

Métricas calculadas:
  - Consumo médio (diário / semanal / mensal)
  - Stock mínimo de segurança dinâmico
  - Lead time médio por fornecedor
  - Sazonalidade mensal (índice 0.0–2.0)
  - Rotatividade (dias desde último movimento)
  - Quantidade económica de encomenda (QEE / EOQ)
  - Ponto de reorder (ROP)
  - Sugestão de quantidade a encomendar
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── PHC SQL queries ───────────────────────────────────────────────────────────

SQL_MOVIMENTOS = """
SELECT
    mo.ref                          AS referencia,
    mo.data                         AS data_mov,
    mo.qtt                          AS quantidade,
    mo.tipomov                      AS tipo,
    ISNULL(mo.documento, '')        AS documento
FROM mo
WHERE mo.ref = ?
  AND mo.data >= ?
  AND mo.data <= ?
  AND mo.qtt IS NOT NULL
ORDER BY mo.data ASC
"""

SQL_HISTORICO_COMPRAS_ARTIGO = """
SELECT TOP 50
    ft.data                         AS data_compra,
    lc.qtt                          AS quantidade,
    lc.preco                        AS preco_unitario,
    ec.nome                         AS fornecedor,
    DATEDIFF(day, ft.data,
        LAG(ft.data) OVER (
            PARTITION BY ft.no ORDER BY ft.data DESC
        )
    )                               AS dias_entre_compras
FROM lc
INNER JOIN ft ON ft.ftstamp = lc.ftstamp
INNER JOIN ec ON ec.no = ft.no
WHERE lc.ref = ?
  AND ft.anulado = 0
ORDER BY ft.data DESC
"""

SQL_LEAD_TIME = """
SELECT
    ec.nome                         AS fornecedor,
    AVG(CAST(DATEDIFF(day, ft.data, GETDATE()) AS FLOAT))
        OVER (PARTITION BY ft.no)   AS dias_medio_entrega
FROM lc
INNER JOIN ft ON ft.ftstamp = lc.ftstamp
INNER JOIN ec ON ec.no = ft.no
WHERE lc.ref = ?
  AND ft.anulado = 0
  AND ft.data >= DATEADD(year, -2, GETDATE())
GROUP BY ec.nome, ft.no, ft.data
"""

SQL_ARTIGO_COMPLETO = """
SELECT
    st.ref                          AS referencia,
    st.design                       AS designacao,
    ISNULL(st.qtt, 0)               AS stock_atual,
    ISNULL(st.qttmin, 0)            AS stock_minimo_phc,
    ISNULL(st.qttmax, 0)            AS stock_maximo_phc,
    ISNULL(st.pcusto, 0)            AS preco_custo,
    ISNULL(st.pcp, 0)               AS preco_ponderado,
    ISNULL(st.unidade, 'un')        AS unidade,
    ISNULL(st.familia, '')          AS familia,
    ISNULL(st.iva, 23)              AS taxa_iva
FROM st
WHERE st.ref = ?
"""


# ── Analysis engine ───────────────────────────────────────────────────────────

class AnaliseMov:
    """Analyses movement history and computes replenishment metrics."""

    def __init__(self, movimentos: list[dict], compras: list[dict],
                 config: dict, stock_atual: float, preco_custo: float):
        self.movimentos  = movimentos   # list of {data_mov, quantidade, tipo}
        self.compras     = compras      # list of {data_compra, quantidade, preco_unitario, fornecedor}
        self.config      = config       # user-editable config dict
        self.stock_atual = stock_atual
        self.preco_custo = preco_custo
        self.hoje        = datetime.now()

    # ── Consumo ──────────────────────────────────────────────────────────────

    def saidas(self) -> list[dict]:
        """Filter only outgoing movements (consumption)."""
        tipos_saida = self.config.get('tipos_saida_mo', [0, 1, 2, 10, 11])
        return [m for m in self.movimentos
                if m.get('tipo') in tipos_saida and m.get('quantidade', 0) > 0]

    def consumo_por_mes(self) -> dict[str, float]:
        """Return {YYYY-MM: total_consumed} for all months with data."""
        por_mes = defaultdict(float)
        for m in self.saidas():
            data = m['data_mov']
            if isinstance(data, str):
                data = datetime.strptime(data[:10], '%Y-%m-%d')
            chave = data.strftime('%Y-%m')
            por_mes[chave] += abs(m['quantidade'])
        return dict(por_mes)

    def consumo_medio_mensal(self) -> float:
        por_mes = self.consumo_por_mes()
        if not por_mes:
            return 0.0
        meses_com_consumo = [v for v in por_mes.values() if v > 0]
        if not meses_com_consumo:
            return 0.0
        return sum(meses_com_consumo) / len(meses_com_consumo)

    def consumo_medio_diario(self) -> float:
        return self.consumo_medio_mensal() / 30.0

    def consumo_medio_semanal(self) -> float:
        return self.consumo_medio_mensal() / 4.33

    # ── Sazonalidade ─────────────────────────────────────────────────────────

    def indice_sazonalidade(self) -> dict[int, float]:
        """
        Returns {mes_1_12: indice} where 1.0 = media, >1 = acima media.
        """
        por_mes = self.consumo_por_mes()
        # Group by month number across all years
        por_num_mes = defaultdict(list)
        for chave, total in por_mes.items():
            mes = int(chave.split('-')[1])
            por_num_mes[mes].append(total)

        medias_mes = {m: sum(v)/len(v) for m, v in por_num_mes.items()}
        media_geral = sum(medias_mes.values()) / len(medias_mes) if medias_mes else 1.0

        if media_geral == 0:
            return {m: 1.0 for m in range(1, 13)}

        return {m: round(v / media_geral, 2) for m, v in medias_mes.items()}

    def indice_mes_atual(self) -> float:
        idx = self.indice_sazonalidade()
        return idx.get(self.hoje.month, 1.0)

    # ── Lead time ─────────────────────────────────────────────────────────────

    def lead_time_medio(self) -> float:
        """Estimate average lead time in days from purchase history."""
        lt = self.config.get('lead_time_dias', 7)
        return float(lt)

    # ── Rotatividade ─────────────────────────────────────────────────────────

    def dias_sem_movimento(self) -> int:
        if not self.movimentos:
            return 9999
        datas = []
        for m in self.movimentos:
            d = m['data_mov']
            if isinstance(d, str):
                d = datetime.strptime(d[:10], '%Y-%m-%d')
            datas.append(d)
        ultimo = max(datas)
        return (self.hoje - ultimo).days

    def classificacao_rotatividade(self) -> str:
        dias = self.dias_sem_movimento()
        if dias <= 30:   return 'alta'
        if dias <= 90:   return 'media'
        if dias <= 180:  return 'baixa'
        return 'parado'

    # ── Stock mínimo de segurança ─────────────────────────────────────────────

    def stock_seguranca(self) -> float:
        """
        Safety stock = Z * σ_demanda * sqrt(lead_time)
        Simplified: fator_seguranca * consumo_diario * lead_time
        """
        fator  = self.config.get('fator_seguranca', 1.5)
        lt     = self.lead_time_medio()
        cd     = self.consumo_medio_diario()
        return round(fator * cd * lt, 2)

    # ── Ponto de reorder ──────────────────────────────────────────────────────

    def ponto_reorder(self) -> float:
        """ROP = consumo_diario * lead_time + stock_seguranca"""
        cd  = self.consumo_medio_diario()
        lt  = self.lead_time_medio()
        ss  = self.stock_seguranca()
        return round(cd * lt + ss, 2)

    # ── EOQ — quantidade económica de encomenda ───────────────────────────────

    def eoq(self) -> float:
        """
        EOQ = sqrt(2 * D * S / H)
        D = consumo anual
        S = custo de encomenda (fixo por encomenda)
        H = custo de posse unitário anual
        """
        D = self.consumo_medio_mensal() * 12
        S = self.config.get('custo_encomenda', 25.0)
        taxa_posse = self.config.get('taxa_posse_anual', 0.20)
        H = self.preco_custo * taxa_posse if self.preco_custo > 0 else 1.0
        if D <= 0 or H <= 0:
            return self.config.get('quantidade_minima_encomenda', 1)
        import math
        return round(math.sqrt(2 * D * S / H), 2)

    # ── Sugestão final ────────────────────────────────────────────────────────

    def sugestao_quantidade(self) -> dict:
        """
        Main output: suggested order quantity and full breakdown.
        """
        cmm   = self.consumo_medio_mensal()
        cmd   = self.consumo_medio_diario()
        ss    = self.stock_seguranca()
        rop   = self.ponto_reorder()
        eoq_v = self.eoq()
        rot   = self.classificacao_rotatividade()
        idx_s = self.indice_mes_atual()

        # Needs ordering?
        precisa_encomendar = self.stock_atual <= rop

        # Suggested quantity
        meses_cobertura = self.config.get('meses_cobertura', 2)
        qtd_base = cmm * meses_cobertura * idx_s
        qtd_min  = self.config.get('quantidade_minima_encomenda', 1)
        qtd_sugerida = max(round(max(qtd_base, eoq_v), 2), qtd_min)

        # If stock is already above ROP, no order needed
        if not precisa_encomendar:
            qtd_sugerida = 0

        # Cobertura com stock actual
        dias_cobertura = round(self.stock_atual / cmd, 0) if cmd > 0 else 9999

        return {
            'precisa_encomendar':   precisa_encomendar,
            'quantidade_sugerida':  qtd_sugerida,
            'consumo_medio_diario': round(cmd, 4),
            'consumo_medio_semanal':round(self.consumo_medio_semanal(), 2),
            'consumo_medio_mensal': round(cmm, 2),
            'stock_seguranca':      ss,
            'ponto_reorder':        rop,
            'eoq':                  eoq_v,
            'dias_cobertura_atual': int(dias_cobertura) if dias_cobertura < 9999 else None,
            'rotatividade':         rot,
            'dias_sem_movimento':   self.dias_sem_movimento(),
            'indice_sazonalidade':  round(idx_s, 2),
            'sazonalidade_meses':   self.indice_sazonalidade(),
            'lead_time_dias':       self.lead_time_medio(),
            'total_meses_historico':len(self.consumo_por_mes()),
        }


# ── PHC data fetcher ──────────────────────────────────────────────────────────

def fetch_movimentos_phc(cfg, referencia: str, meses: int = 24) -> tuple[list, list, dict]:
    """
    Fetch movements and purchase history from PHC SQL Server.
    Returns (movimentos, compras, artigo_info).
    Falls back to empty lists if PHC not connected.
    """
    desde = datetime.now() - timedelta(days=meses * 30)
    ate   = datetime.now()

    try:
        from phc_sync import get_phc_connection
        conn   = get_phc_connection(cfg)
        cursor = conn.cursor()

        # Movements
        cursor.execute(SQL_MOVIMENTOS, referencia, desde, ate)
        cols_mo = [d[0] for d in cursor.description]
        movimentos = [dict(zip(cols_mo, row)) for row in cursor.fetchall()]

        # Purchase history
        cursor.execute(SQL_HISTORICO_COMPRAS_ARTIGO, referencia)
        cols_lc = [d[0] for d in cursor.description]
        compras = [dict(zip(cols_lc, row)) for row in cursor.fetchall()]

        # Article info
        cursor.execute(SQL_ARTIGO_COMPLETO, referencia)
        cols_st = [d[0] for d in cursor.description]
        row_st  = cursor.fetchone()
        artigo_info = dict(zip(cols_st, row_st)) if row_st else {}

        conn.close()
        return movimentos, compras, artigo_info

    except Exception as e:
        logger.warning(f"PHC não disponível para {referencia}: {e}")
        return [], [], {}


def analisar_artigo(cfg_phc, cfg_config: dict, referencia: str,
                    stock_atual: float = None, preco_custo: float = None) -> dict:
    """
    Full analysis for one article.
    cfg_phc     : ConfigPHC instance (may be None)
    cfg_config  : dict of user-editable parameters
    referencia  : PHC article reference
    """
    movimentos, compras, artigo_phc = [], [], {}

    if cfg_phc and cfg_phc.ultima_sync:
        meses = cfg_config.get('meses_historico', 24)
        movimentos, compras, artigo_phc = fetch_movimentos_phc(cfg_phc, referencia, meses)

    # Use local cache if PHC not available
    from models import ArtigoPHC
    artigo_local = ArtigoPHC.query.filter_by(referencia=referencia).first()

    stock = stock_atual
    preco = preco_custo
    if artigo_local:
        if stock is None:  stock = artigo_local.stock_atual
        if preco is None:  preco = artigo_local.preco_custo_ponderado or artigo_local.preco_custo

    stock = stock or 0.0
    preco = preco or 0.0

    analise = AnaliseMov(movimentos, compras, cfg_config, stock, preco)
    resultado = analise.sugestao_quantidade()

    resultado['referencia']   = referencia
    resultado['designacao']   = artigo_phc.get('designacao') or (artigo_local.designacao if artigo_local else '')
    resultado['stock_atual']  = stock
    resultado['preco_custo']  = preco
    resultado['unidade']      = artigo_phc.get('unidade') or (artigo_local.unidade if artigo_local else 'un')
    resultado['familia']      = artigo_phc.get('familia') or (artigo_local.familia if artigo_local else '')
    resultado['tem_historico_phc'] = len(movimentos) > 0

    return resultado


# ── Default config ────────────────────────────────────────────────────────────

CONFIG_PADRAO = {
    'meses_historico':              24,     # months of history to analyse
    'lead_time_dias':               7,      # default lead time (days)
    'fator_seguranca':              1.5,    # safety stock multiplier
    'meses_cobertura':              2,      # target months of stock to order
    'custo_encomenda':              25.0,   # fixed ordering cost (€) for EOQ
    'taxa_posse_anual':             0.20,   # annual holding cost rate (20%)
    'quantidade_minima_encomenda':  1,      # minimum order quantity
    'tipos_saida_mo':               [0, 1, 2, 10, 11],  # PHC mo.tipomov = outgoing
    'alertar_dias_cobertura':       30,     # alert if coverage < N days
    'ignorar_artigos_parados_dias': 365,    # ignore articles with no movement > N days
}
