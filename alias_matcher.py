"""
alias_matcher.py
────────────────
Matches supplier PDF line descriptions to PHC articles.

Priority order (with confidence):
  1. Exact alias match (manual/learned)      → 1.0
  2. Supplier reference match                → 0.95
  3. AI semantic match (LM Studio/Claude)    → 0.85
  4. Fuzzy text similarity                   → 0.5-0.8
  5. No match                                → 0.0

Unconfirmed matches (conf < CONFIRM_THRESHOLD) go to
the PendingMatch table for operator review.
"""

import re
import json
import unicodedata
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

CONFIRM_THRESHOLD = 0.90   # below this → needs human confirmation
AI_MATCH_THRESHOLD = 0.50  # minimum AI confidence to propose a suggestion


# ── Text normalisation ────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    if not text: return ''
    nfkd = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in nfkd if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s/]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def _similarity(a: str, b: str) -> float:
    if not a or not b: return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _ref_tokens(text: str) -> set:
    """Extract numeric/alphanumeric tokens — catches '1/4', 'DN50', etc."""
    return set(re.findall(r'[a-z0-9]+(?:[./][a-z0-9]+)*', text.lower()))


# ── AI semantic matching ──────────────────────────────────────────────────────

def _ai_match(descricao_forn: str, candidatos: list[dict],
              fornecedor: str = '') -> tuple[str | None, float]:
    """
    Ask the configured AI provider whether any candidate article matches
    the supplier description. Returns (artigo_ref, confianca) or (None, 0).

    candidatos: [{'ref': str, 'design': str}, ...]
    """
    try:
        from models import ConfigIA
        cfg_ia = ConfigIA.query.first()
        if not cfg_ia:
            return None, 0.0

        if not candidatos:
            return None, 0.0

        lista = '\n'.join(
            f"{i+1}. REF={c['ref']} | {c['design']}"
            for i, c in enumerate(candidatos)
        )

        prompt = f"""Tens uma linha de orçamento de um fornecedor e uma lista de artigos de stock.
Determina qual artigo da lista corresponde melhor à linha do orçamento.

Linha do orçamento (fornecedor: {fornecedor}):
"{descricao_forn}"

Artigos disponíveis:
{lista}

Responde APENAS com JSON válido neste formato exacto:
{{"numero": 1, "confianca": 0.9, "justificacao": "breve motivo"}}

Onde:
- "numero" é o número da lista (1, 2, 3...) ou 0 se nenhum corresponde
- "confianca" é 0.0 a 1.0
- Se nenhum corresponde, responde {{"numero": 0, "confianca": 0.0, "justificacao": "sem correspondência"}}"""

        from ai_provider import analyze_pdf
        # Reuse the provider infrastructure with a simple text prompt
        class _FakeCfg:
            def __init__(self, real):
                for k in ['provider','lm_host','lm_port','lm_model','claude_api_key']:
                    setattr(self, k, getattr(real, k, ''))

        import urllib.request
        if cfg_ia.provider in ('lmstudio', 'ollama'):
            base_url = f"http://{cfg_ia.lm_host}:{cfg_ia.lm_port}"
            payload = json.dumps({
                "model": cfg_ia.lm_model or "default",
                "messages": [
                    {"role": "system", "content": "Responde sempre e só com JSON válido, sem texto extra."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.0,
                "max_tokens": 150,
                "stream": False
            }).encode()
            req = urllib.request.Request(
                base_url.rstrip('/') + '/v1/chat/completions',
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            raw = data['choices'][0]['message']['content'].strip()

        elif cfg_ia.provider == 'claude':
            import anthropic
            client = anthropic.Anthropic(api_key=cfg_ia.claude_api_key or '')
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                system="Responde sempre e só com JSON válido, sem texto extra.",
                messages=[{"role": "user", "content": prompt}]
            )
            raw = msg.content[0].text.strip()
        else:
            return None, 0.0

        # Parse response
        raw = raw.strip('`').strip()
        if raw.startswith('json'): raw = raw[4:]
        result = json.loads(raw)
        num  = int(result.get('numero', 0))
        conf = float(result.get('confianca', 0))

        if num > 0 and num <= len(candidatos) and conf >= AI_MATCH_THRESHOLD:
            return candidatos[num - 1]['ref'], round(conf * 0.85, 3)  # scale slightly
        return None, 0.0

    except Exception as e:
        logger.debug(f"AI match failed: {e}")
        return None, 0.0


# ── Core matching ─────────────────────────────────────────────────────────────

def match_item_to_artigo(descricao: str, referencia_forn: str,
                          fornecedor: str, linhas_pedido: list,
                          aliases_db: list,
                          use_ai: bool = True) -> tuple[str | None, float, str | None]:
    """
    Try to match a supplier line to one of the pedido's PHC articles.
    Returns (artigo_ref, confianca, method).
    """
    desc_norm = _normalise(descricao)
    ref_norm  = _normalise(referencia_forn or '')
    forn_norm = _normalise(fornecedor or '')
    desc_toks = _ref_tokens(desc_norm)
    ref_toks  = _ref_tokens(ref_norm)

    pedido_refs = {l.artigo_ref for l in linhas_pedido if l.artigo_ref}

    # ── 1. Exact alias ────────────────────────────────────────────────────────
    for alias in aliases_db:
        if alias.artigo_ref not in pedido_refs: continue
        if alias.fornecedor and _normalise(alias.fornecedor) not in forn_norm: continue
        if alias.descricao_norm and alias.descricao_norm == desc_norm:
            return alias.artigo_ref, 1.0, 'alias_exact'
        if ref_norm and alias.referencia_forn and _normalise(alias.referencia_forn) == ref_norm:
            return alias.artigo_ref, 0.97, 'alias_ref'

    # ── 2. Direct reference match ─────────────────────────────────────────────
    if referencia_forn:
        for linha in linhas_pedido:
            if not linha.artigo_ref: continue
            if _normalise(linha.artigo_ref) == ref_norm:
                return linha.artigo_ref, 0.95, 'ref_exact'
            # Token overlap on reference
            phc_toks = _ref_tokens(_normalise(linha.referencia or ''))
            if ref_toks and phc_toks and len(ref_toks & phc_toks) / max(len(ref_toks), 1) > 0.7:
                return linha.artigo_ref, 0.88, 'ref_tokens'

    # ── 3. Token overlap on description ──────────────────────────────────────
    best_ref, best_score = None, 0.0
    for linha in linhas_pedido:
        if not linha.artigo_ref: continue
        design_norm = _normalise(linha.designacao or '')
        design_toks = _ref_tokens(design_norm)

        # Pure text similarity
        sim = _similarity(desc_norm, design_norm)

        # Bonus for shared numeric tokens (e.g. "1/4", "DN50")
        shared = desc_toks & design_toks
        if shared:
            token_score = len(shared) / max(len(desc_toks | design_toks), 1)
            sim = max(sim, 0.4 + token_score * 0.5)

        if sim > best_score:
            best_score = sim
            best_ref   = linha.artigo_ref

    if best_score >= 0.72:
        return best_ref, round(best_score * 0.88, 3), 'fuzzy'

    # ── 4. AI semantic match ──────────────────────────────────────────────────
    if use_ai and linhas_pedido:
        candidatos = [
            {'ref': l.artigo_ref, 'design': l.designacao or ''}
            for l in linhas_pedido if l.artigo_ref
        ]
        ai_ref, ai_conf = _ai_match(descricao, candidatos, fornecedor)
        if ai_ref:
            return ai_ref, ai_conf, 'ai'

    # ── 5. Weak fuzzy (below threshold — still propose) ───────────────────────
    if best_score >= 0.40:
        return best_ref, round(best_score * 0.75, 3), 'fuzzy_weak'

    return None, 0.0, None


# ── Orcamento matching ────────────────────────────────────────────────────────

def match_orcamento_items(orcamento, pedido, aliases_db: list,
                           use_ai: bool = True) -> list[dict]:
    """
    Match all items of an orcamento to pedido PHC articles.
    Saves PendingMatch for items needing confirmation.
    Returns list of match results.
    """
    from models import db, PendingMatch
    results = []

    # Remove old pending for this orcamento
    PendingMatch.query.filter_by(orcamento_id=orcamento.id).delete()
    db.session.flush()

    for item in orcamento.items:
        ref, conf, method = match_item_to_artigo(
            descricao       = item.descricao or '',
            referencia_forn = item.referencia or '',
            fornecedor      = orcamento.empresa or '',
            linhas_pedido   = pedido.linhas,
            aliases_db      = aliases_db,
            use_ai          = use_ai
        )
        item.artigo_ref_match = ref
        item.match_confianca  = conf

        # Save pending if below threshold and has a suggestion
        needs_confirm = conf < CONFIRM_THRESHOLD
        if needs_confirm or ref is None:
            pm = PendingMatch(
                pedido_id    = pedido.id,
                orcamento_id = orcamento.id,
                item_id      = item.id,
                descricao_forn    = item.descricao or '',
                referencia_forn   = item.referencia or '',
                fornecedor        = orcamento.empresa or '',
                artigo_ref_sugerido = ref,
                confianca_sugerido  = conf,
                metodo              = method,
                confirmado          = False,
            )
            db.session.add(pm)

        results.append({
            'item_id':      item.id,
            'descricao':    item.descricao,
            'artigo_ref':   ref,
            'confianca':    conf,
            'method':       method,
            'needs_confirm': needs_confirm,
        })

    db.session.commit()
    return results


# ── Comparison matrix ─────────────────────────────────────────────────────────

def build_comparison_matrix(pedido, orcamentos: list) -> list[dict]:
    matrix = []
    for linha in pedido.linhas:
        row = {'linha': linha, 'orcamentos': []}
        precos = []
        for orc in orcamentos:
            best_item, best_conf = None, 0.0
            for item in orc.items:
                if item.artigo_ref_match == linha.artigo_ref and linha.artigo_ref:
                    if item.match_confianca > best_conf:
                        best_item, best_conf = item, item.match_confianca
            preco = best_item.preco_unitario if best_item else None
            row['orcamentos'].append({
                'orcamento_id':   orc.id,
                'empresa':        orc.empresa,
                'item':           best_item,
                'preco_unitario': preco,
                'total':          (preco or 0) * linha.quantidade,
                'confianca':      best_conf,
                'matched':        best_item is not None,
            })
            if preco is not None:
                precos.append((len(row['orcamentos']) - 1, preco))
        row['melhor_idx'] = min(precos, key=lambda x: x[1])[0] if precos else None
        matrix.append(row)
    return matrix


# ── Alias persistence ─────────────────────────────────────────────────────────

def save_alias(db, artigo_ref: str, descricao_orig: str, fornecedor: str,
               referencia_forn: str, user_id: int, confianca: float = 1.0):
    from models import AliasArtigo
    desc_norm = _normalise(descricao_orig)
    existing = AliasArtigo.query.filter_by(
        artigo_ref=artigo_ref, descricao_norm=desc_norm
    ).first()
    if existing:
        existing.vezes_usado += 1
        existing.confianca    = max(existing.confianca, confianca)
        if fornecedor and not existing.fornecedor:
            existing.fornecedor = fornecedor
        if referencia_forn and not existing.referencia_forn:
            existing.referencia_forn = referencia_forn
    else:
        from models import AliasArtigo
        db.session.add(AliasArtigo(
            artigo_ref=artigo_ref, fornecedor=fornecedor,
            descricao_orig=descricao_orig, descricao_norm=desc_norm,
            referencia_forn=referencia_forn, confianca=confianca,
            criado_por=user_id, vezes_usado=1,
        ))
    db.session.commit()
