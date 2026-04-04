"""
reposicao.py
────────────
Motor de reposição baseado em vendas reais do PHC CS.

Tabelas usadas (só leitura):
  fi   → linhas de documentos (ref, qtt, preco, ftstamp)
  ft   → cabeçalho documentos (ftstamp, no, fdata, anulado, tipodoc)
  st   → artigos (ref, stock, epcusto, epcpond)

Lógica:
  - Vendas = linhas fi com ft.tipodoc=1 (facturas de venda)
  - Calcula venda média mensal nos últimos N anos
  - Filtra artigos sem movimento relevante (comprados e vendidos 1x)
  - Compara com stock actual
  - Calcula dias de cobertura, ROP, EOQ, sugestão de encomenda
"""

import math
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

CONFIG_PADRAO = {
    'meses_historico':             60,    # 5 anos
    'lead_time_dias':               7,
    'fator_seguranca':             1.5,
    'meses_cobertura':              2,
    'custo_encomenda':             25.0,
    'taxa_posse_anual':            0.20,
    'quantidade_minima_encomenda': 1,
    'alertar_dias_cobertura':      30,
    'ignorar_parados_dias':       365,
    'min_meses_com_venda':          2,    # ignorar se só vendeu em <2 meses distintos
    'min_total_vendido':            2,    # ignorar se total vendido < 2 unidades
}

# ── SQL ───────────────────────────────────────────────────────────────────────

SQL_VENDAS_ARTIGO = """
SELECT
    YEAR(ft.fdata)              AS ano,
    MONTH(ft.fdata)             AS mes,
    SUM(ABS(ISNULL(fi.qtt,0)))  AS total_vendido,
    COUNT(DISTINCT ft.ftstamp)  AS num_facturas
FROM fi
INNER JOIN ft ON ft.ftstamp = fi.ftstamp
WHERE fi.ref = ?
  AND ft.anulado = 0
  AND ft.tipodoc = 1
  AND ft.fdata >= DATEADD(month, -?, GETDATE())
  AND fi.qtt IS NOT NULL
  AND fi.qtt > 0
GROUP BY YEAR(ft.fdata), MONTH(ft.fdata)
ORDER BY ano, mes
"""

SQL_TODAS_VENDAS = """
SELECT
    fi.ref,
    YEAR(ft.fdata)              AS ano,
    MONTH(ft.fdata)             AS mes,
    SUM(ABS(ISNULL(fi.qtt,0)))  AS total_vendido,
    COUNT(DISTINCT ft.ftstamp)  AS num_facturas
FROM fi
INNER JOIN ft ON ft.ftstamp = fi.ftstamp
WHERE ft.anulado = 0
  AND ft.tipodoc = 1
  AND ft.fdata >= DATEADD(month, -?, GETDATE())
  AND fi.qtt IS NOT NULL
  AND fi.qtt > 0
  AND fi.ref IS NOT NULL
  AND fi.ref <> ''
GROUP BY fi.ref, YEAR(ft.fdata), MONTH(ft.fdata)
ORDER BY fi.ref, ano, mes
"""


# ── Engine ────────────────────────────────────────────────────────────────────

def calcular_metricas(vendas_por_mes: dict, stock_atual: float,
                      preco_custo: float, config: dict) -> dict:
    """
    Given monthly sales dict {(ano,mes): qty}, compute all metrics.
    """
    if not vendas_por_mes:
        return _sem_dados(stock_atual)

    # Total vendido e meses com vendas
    total_vendido    = sum(vendas_por_mes.values())
    meses_com_venda  = len([v for v in vendas_por_mes.values() if v > 0])

    # Filtrar artigos sem relevância
    min_meses = config.get('min_meses_com_venda', 2)
    min_total = config.get('min_total_vendido', 2)

    if meses_com_venda < min_meses or total_vendido < min_total:
        return _sem_relevancia(stock_atual, total_vendido, meses_com_venda)

    # Período total: desde o primeiro mês com venda até hoje
    # Isto dá a média real anual sem inflar artigos de venda esporádica
    if vendas_por_mes:
        chaves = sorted(vendas_por_mes.keys())  # list of (ano, mes)
        primeiro_ano, primeiro_mes = chaves[0]
        hoje = datetime.now()
        # Months elapsed from first sale to now
        meses_periodo = (hoje.year - primeiro_ano) * 12 + (hoje.month - primeiro_mes) + 1
        meses_periodo = max(meses_periodo, 1)
    else:
        meses_periodo = config.get('meses_historico', 60)

    # Média mensal = total vendido / meses desde primeira venda
    cmm = total_vendido / meses_periodo
    cmd = cmm / 30.0

    # Lead time
    lt = float(config.get('lead_time_dias', 7))

    # Stock de segurança
    ss = round(config.get('fator_seguranca', 1.5) * cmd * lt, 2)

    # ROP
    rop = round(cmd * lt + ss, 2)

    # EOQ
    D = cmm * 12
    S = float(config.get('custo_encomenda', 25))
    taxa = float(config.get('taxa_posse_anual', 0.20))
    H = preco_custo * taxa if preco_custo > 0 else 1.0
    eoq = round(math.sqrt(2 * D * S / H), 2) if D > 0 and H > 0 else 1

    # Cobertura actual
    dias_cobertura = round(stock_atual / cmd) if cmd > 0 and stock_atual > 0 else 0

    # Precisa encomendar?
    precisa = stock_atual <= rop

    # Quantidade sugerida
    meses_cob = config.get('meses_cobertura', 2)
    qtd_base  = cmm * meses_cob
    qtd_min   = config.get('quantidade_minima_encomenda', 1)
    qtd       = round(max(qtd_base, eoq, qtd_min), 2) if precisa else 0

    # Urgência
    if stock_atual <= 0:
        urgencia = 'critico'
    elif dias_cobertura < config.get('alertar_dias_cobertura', 30):
        urgencia = 'urgente'
    elif precisa:
        urgencia = 'necessario'
    else:
        urgencia = 'ok'

    return {
        'tem_dados':              True,
        'relevante':              True,
        'precisa_encomendar':     precisa,
        'urgencia':               urgencia,
        'quantidade_sugerida':    qtd,
        'consumo_medio_mensal':   round(cmm, 2),
        'consumo_medio_diario':   round(cmd, 4),
        'stock_seguranca':        ss,
        'ponto_reorder':          rop,
        'eoq':                    eoq,
        'dias_cobertura_atual':   int(dias_cobertura),
        'total_vendido':          round(total_vendido, 2),
        'meses_com_venda':        meses_com_venda,
        'meses_periodo':          meses_periodo,
        'lead_time_dias':         lt,
    }


def _sem_dados(stock_atual):
    return {
        'tem_dados': False, 'relevante': False,
        'precisa_encomendar': False, 'urgencia': 'sem_dados',
        'quantidade_sugerida': 0, 'consumo_medio_mensal': 0,
        'consumo_medio_diario': 0, 'stock_seguranca': 0,
        'ponto_reorder': 0, 'eoq': 0, 'dias_cobertura_atual': 0,
        'total_vendido': 0, 'meses_com_venda': 0, 'lead_time_dias': 0,
    }


def _sem_relevancia(stock_atual, total_vendido, meses_com_venda):
    return {
        **_sem_dados(stock_atual),
        'relevante': False, 'urgencia': 'irrelevante',
        'total_vendido': round(total_vendido, 2),
        'meses_com_venda': meses_com_venda,
    }


# ── PHC fetchers ──────────────────────────────────────────────────────────────

def analisar_artigo(cfg_phc, config: dict, referencia: str,
                    stock_atual: float = None, preco_custo: float = None) -> dict:
    """Analyse one article."""
    from models import ArtigoPHC

    artigo = ArtigoPHC.query.filter_by(referencia=referencia).first()
    if stock_atual is None:
        stock_atual = artigo.stock_atual if artigo else 0
    if preco_custo is None:
        preco_custo = (artigo.preco_custo_ponderado or artigo.preco_custo) if artigo else 0

    vendas_por_mes = {}

    if cfg_phc and cfg_phc.ultima_sync:
        try:
            from phc_sync import get_phc_connection
            conn   = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            meses  = config.get('meses_historico', 60)
            cursor.execute(SQL_VENDAS_ARTIGO, referencia, meses)
            for row in cursor.fetchall():
                vendas_por_mes[(row[0], row[1])] = float(row[2])
            conn.close()
        except Exception as e:
            logger.warning(f"PHC error for {referencia}: {e}")

    m = calcular_metricas(vendas_por_mes, stock_atual or 0, preco_custo or 0, config)
    m['referencia']  = referencia
    m['designacao']  = artigo.designacao if artigo else ''
    m['stock_atual'] = stock_atual or 0
    m['preco_custo'] = preco_custo or 0
    m['unidade']     = artigo.unidade if artigo else 'un'
    m['familia']     = artigo.familia if artigo else ''
    return m


def analisar_todos(cfg_phc, config: dict, artigos_local: list) -> list:
    """
    Analyse ALL articles in bulk using a single SQL query.
    Much faster than calling analisar_artigo() per article.
    """
    # Build lookup: ref -> (stock, preco)
    local = {a.referencia: a for a in artigos_local}

    vendas = defaultdict(dict)  # ref -> {(ano,mes): qty}

    if cfg_phc and cfg_phc.ultima_sync:
        try:
            from phc_sync import get_phc_connection
            conn   = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            meses  = config.get('meses_historico', 60)
            cursor.execute(SQL_TODAS_VENDAS, meses)
            for ref, ano, mes, total, _ in cursor.fetchall():
                vendas[ref][(ano, mes)] = float(total)
            conn.close()
            logger.info(f"Vendas carregadas: {len(vendas)} artigos com histórico")
        except Exception as e:
            logger.error(f"PHC bulk error: {e}")

    resultados = []
    for artigo in artigos_local:
        ref   = artigo.referencia
        stock = artigo.stock_atual or 0
        preco = artigo.preco_custo_ponderado or artigo.preco_custo or 0

        # Skip negative stock
        if stock < 0:
            continue

        m = calcular_metricas(vendas.get(ref, {}), stock, preco, config)
        m['referencia']  = ref
        m['designacao']  = artigo.designacao or ''
        m['stock_atual'] = stock
        m['preco_custo'] = preco
        m['unidade']     = artigo.unidade or 'un'
        m['familia']     = artigo.familia or ''
        resultados.append(m)

    # Sort: critico > urgente > necessario > ok > irrelevante > sem_dados
    ordem = {'critico': 0, 'urgente': 1, 'necessario': 2, 'ok': 3,
              'irrelevante': 4, 'sem_dados': 5}
    resultados.sort(key=lambda x: ordem.get(x.get('urgencia', 'sem_dados'), 5))
    return resultados
