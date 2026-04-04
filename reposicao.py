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
    'min_anos_historico':           2,    # ignorar se < 2 anos desde 1a venda
    'min_meses_com_venda':          3,    # ignorar se vendeu em < 3 meses distintos
    'min_total_vendido':            3,    # ignorar se total vendido < 3 unidades
    'ignorar_sem_movimento_anos':   3,    # ignorar se > 3 anos sem qualquer venda
}

# ── SQL ───────────────────────────────────────────────────────────────────────
SQL_DIVERSIDADE_ARTIGO = """
SELECT
    COUNT(DISTINCT ft.no)           AS num_clientes,
    COUNT(DISTINCT ft.ftstamp)      AS num_facturas,
    SUM(ABS(ISNULL(fi.qtt,0)))      AS total_vendido,
    MIN(ft.fdata)                   AS primeira_venda,
    MAX(ft.fdata)                   AS ultima_venda,
    AVG(ISNULL(fi.epv,0))           AS preco_venda_medio
FROM fi
INNER JOIN ft ON ft.ftstamp = fi.ftstamp
WHERE fi.ref = ?
  AND ft.anulado = 0
  AND ft.tipodoc = 1
  AND fi.qtt IS NOT NULL AND fi.qtt > 0
"""

SQL_DIVERSIDADE_TODAS = """
SELECT
    fi.ref,
    COUNT(DISTINCT ft.no)           AS num_clientes,
    COUNT(DISTINCT ft.ftstamp)      AS num_facturas,
    SUM(ABS(ISNULL(fi.qtt,0)))      AS total_vendido,
    AVG(ISNULL(fi.epv,0))           AS preco_venda_medio
FROM fi
INNER JOIN ft ON ft.ftstamp = fi.ftstamp
WHERE ft.anulado = 0
  AND ft.tipodoc = 1
  AND ft.fdata >= DATEADD(month, -?, GETDATE())
  AND fi.qtt IS NOT NULL AND fi.qtt > 0
  AND fi.ref IS NOT NULL AND fi.ref <> ''
GROUP BY fi.ref
"""



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


def score_relevancia(total_vendido: float, num_clientes: int, num_facturas: int,
                     meses_periodo: int, preco_custo: float, config: dict) -> dict:
    """
    Score 0-100 que determina se vale a pena fazer stock.
    
    Factores negativos (reduzem score):
      - Poucos clientes (mono-cliente = risco)
      - Poucas facturas (compra/venda isolada)
      - Preço de custo elevado (capital imobilizado)
      - Baixa rotatividade (consumo anual baixo)
    
    Factores positivos (aumentam score):
      - Múltiplos clientes
      - Muitas facturas distribuídas no tempo
      - Preço baixo (fácil de ter em stock)
      - Alta rotatividade
    """
    score = 100
    razoes = []
    
    # Factor 1: Diversidade de clientes
    if num_clientes == 1:
        score -= 40
        razoes.append(f"⚠️ Vendido a apenas 1 cliente — risco de dependência")
    elif num_clientes == 2:
        score -= 20
        razoes.append(f"⚠️ Vendido a apenas 2 clientes")
    elif num_clientes >= 5:
        razoes.append(f"✅ {num_clientes} clientes distintos — boa diversidade")
    
    # Factor 2: Frequência de facturas
    if num_facturas <= 2:
        score -= 35
        razoes.append(f"⚠️ Apenas {num_facturas} factura(s) — venda isolada")
    elif num_facturas <= 5:
        score -= 15
        razoes.append(f"⚠️ Apenas {num_facturas} facturas no período")
    elif num_facturas >= 10:
        razoes.append(f"✅ {num_facturas} facturas — rotatividade consistente")
    
    # Factor 3: Custo de aquisição
    if preco_custo > 500:
        score -= 25
        razoes.append(f"⚠️ Preço elevado ({preco_custo:.0f}€) — capital imobilizado alto")
    elif preco_custo > 200:
        score -= 10
        razoes.append(f"⚠️ Preço médio-alto ({preco_custo:.0f}€)")
    elif preco_custo > 0 and preco_custo < 50:
        score += 5
        razoes.append(f"✅ Preço baixo — económico manter em stock")
    
    # Factor 4: Consumo anual (rotatividade)
    consumo_anual = (total_vendido / meses_periodo * 12) if meses_periodo > 0 else 0
    if consumo_anual < 1:
        score -= 20
        razoes.append(f"⚠️ Consumo muito baixo ({consumo_anual:.1f}/ano)")
    elif consumo_anual < 3:
        score -= 10
        razoes.append(f"⚠️ Baixo consumo anual ({consumo_anual:.1f}/ano)")
    elif consumo_anual >= 10:
        score += 10
        razoes.append(f"✅ Alto consumo anual ({consumo_anual:.0f}/ano)")
    
    score = max(0, min(100, score))
    
    # Recomendação
    if score >= 70:
        recomendacao = 'manter_stock'
        rec_label = '✅ Vale a pena manter em stock'
    elif score >= 45:
        recomendacao = 'stock_cauteloso'
        rec_label = '⚠️ Stock cauteloso — avaliar caso a caso'
    else:
        recomendacao = 'nao_fazer_stock'
        rec_label = '❌ Não recomendado fazer stock'
    
    return {
        'score': score,
        'recomendacao': recomendacao,
        'rec_label': rec_label,
        'razoes': razoes,
        'num_clientes': num_clientes,
        'num_facturas': num_facturas,
        'consumo_anual': round(consumo_anual, 2),
    }


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

    # Check last sale - ignore if no movement for X years
    ignorar_anos = config.get('ignorar_sem_movimento_anos', 3)
    if vendas_por_mes:
        ultimo = sorted(vendas_por_mes.keys())[-1]
        from datetime import datetime as _dt2
        meses_parado = (_dt2.now().year - ultimo[0]) * 12 + (_dt2.now().month - ultimo[1])
        if meses_parado > ignorar_anos * 12:
            return _sem_relevancia(stock_atual, total_vendido, meses_com_venda, 'parado')

    # Filtrar artigos sem relevância
    min_meses = config.get('min_meses_com_venda', 3)
    min_total = config.get('min_total_vendido', 3)
    if meses_com_venda < min_meses or total_vendido < min_total:
        return _sem_relevancia(stock_atual, total_vendido, meses_com_venda, 'pouco_historico')

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

    # Ignorar se histórico < N anos desde 1ª venda
    anos_historico = meses_periodo / 12
    min_anos = config.get('min_anos_historico', 2)
    if anos_historico < min_anos:
        return _sem_relevancia(stock_atual, total_vendido, meses_com_venda, 'pouco_historico')

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


def _sem_relevancia(stock_atual, total_vendido, meses_com_venda, motivo='irrelevante'):
    return {
        **_sem_dados(stock_atual),
        'relevante': False, 'urgencia': motivo,
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
    diversidade = {}  # ref -> {num_clientes, num_facturas, total_vendido}

    if cfg_phc and cfg_phc.ultima_sync:
        try:
            from phc_sync import get_phc_connection
            conn   = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            meses  = config.get('meses_historico', 60)

            # Fetch monthly sales
            cursor.execute(SQL_TODAS_VENDAS, meses)
            for ref, ano, mes, total, _ in cursor.fetchall():
                vendas[ref][(ano, mes)] = float(total)

            # Fetch diversity data
            cursor.execute(SQL_DIVERSIDADE_TODAS, meses)
            for ref, nc, nf, tv, pv in cursor.fetchall():
                diversidade[ref] = {
                    'num_clientes': int(nc or 0),
                    'num_facturas': int(nf or 0),
                    'total_vendido': float(tv or 0),
                }

            conn.close()
            logger.info(f"Vendas: {len(vendas)} artigos, Diversidade: {len(diversidade)} artigos")
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

        # Add relevance score
        div = diversidade.get(ref, {})
        meses_per = m.get('meses_periodo', config.get('meses_historico', 60))
        tot_vend  = m.get('total_vendido', div.get('total_vendido', 0))
        sc = score_relevancia(
            total_vendido  = tot_vend,
            num_clientes   = div.get('num_clientes', 0),
            num_facturas   = div.get('num_facturas', 0),
            meses_periodo  = meses_per,
            preco_custo    = preco,
            config         = config,
        )
        m.update({
            'score':          sc['score'],
            'recomendacao':   sc['recomendacao'],
            'rec_label':      sc['rec_label'],
            'razoes':         sc['razoes'],
            'num_clientes':   sc['num_clientes'],
            'num_facturas':   sc['num_facturas'],
        })

        # Override suggestion if score is low
        if sc['recomendacao'] == 'nao_fazer_stock' and m.get('quantidade_sugerida', 0) > 0:
            m['quantidade_sugerida'] = 0
            m['urgencia'] = 'nao_recomendado'

        resultados.append(m)

    # Sort: critico > urgente > necessario > ok > irrelevante > sem_dados
    ordem = {'critico': 0, 'urgente': 1, 'necessario': 2, 'ok': 3,
              'nao_recomendado': 4, 'irrelevante': 5, 'parado': 6,
              'pouco_historico': 7, 'sem_dados': 8}
    resultados.sort(key=lambda x: ordem.get(x.get('urgencia', 'sem_dados'), 5))
    return resultados
