"""
alias_matcher.py
────────────────
Matches supplier PDF line descriptions to PHC articles.

Priority order:
  1. Exact alias match (manual or learned)         → confianca 1.0
  2. Supplier reference match (artigo_ref field)   → confianca 0.95
  3. Normalised text similarity (fuzzy)            → confianca 0.5–0.8
  4. No match                                      → confianca 0.0

When a user manually links a supplier line to a PHC article,
we save it as an alias with confianca=1.0 and vezes_usado increments
each time it matches automatically in future PDFs.
"""

import re
import unicodedata
from difflib import SequenceMatcher


def _normalise(text: str) -> str:
    """Lowercase, remove accents, collapse whitespace, strip punctuation."""
    if not text:
        return ''
    # Remove accents
    nfkd = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in nfkd if not unicodedata.combining(c))
    text = text.lower()
    # Remove punctuation except digits and letters
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _similarity(a: str, b: str) -> float:
    """Return 0.0–1.0 similarity between two normalised strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def match_item_to_artigo(descricao: str, referencia_forn: str,
                          fornecedor: str, linhas_pedido: list,
                          aliases_db: list) -> tuple[str | None, float, str | None]:
    """
    Try to match a supplier line (from PDF) to one of the pedido's PHC articles.

    Args:
        descricao        : line description from supplier PDF
        referencia_forn  : supplier's reference code (if any)
        fornecedor       : supplier name
        linhas_pedido    : list of LinhaPedido objects
        aliases_db       : list of AliasArtigo objects (all aliases in DB)

    Returns:
        (artigo_ref, confianca, match_method)
        artigo_ref   : PHC reference or None
        confianca    : 0.0–1.0
        match_method : 'alias_exact' | 'ref_match' | 'fuzzy' | None
    """
    desc_norm = _normalise(descricao)
    ref_norm  = _normalise(referencia_forn or '')
    forn_norm = _normalise(fornecedor or '')

    # Build set of refs in this pedido for filtering
    pedido_refs = {l.artigo_ref for l in linhas_pedido if l.artigo_ref}

    # ── 1. Exact alias match ──────────────────────────────────────────────────
    for alias in aliases_db:
        # Only consider aliases for articles in this pedido
        if alias.artigo_ref not in pedido_refs:
            continue
        # Supplier filter — if alias has supplier, must match
        if alias.fornecedor and _normalise(alias.fornecedor) not in forn_norm:
            continue
        # Description match
        if alias.descricao_norm and alias.descricao_norm == desc_norm:
            return alias.artigo_ref, 1.0, 'alias_exact'
        # Reference match on alias
        if ref_norm and alias.referencia_forn and _normalise(alias.referencia_forn) == ref_norm:
            return alias.artigo_ref, 0.95, 'ref_alias'

    # ── 2. Direct reference match (supplier ref == PHC ref) ──────────────────
    if referencia_forn:
        for linha in linhas_pedido:
            if not linha.artigo_ref:
                continue
            if _normalise(linha.artigo_ref) == ref_norm:
                return linha.artigo_ref, 0.95, 'ref_match'
            if _normalise(linha.referencia or '') == ref_norm:
                return linha.artigo_ref, 0.90, 'ref_match'

    # ── 3. Fuzzy description match against pedido lines ───────────────────────
    best_ref   = None
    best_score = 0.0
    for linha in linhas_pedido:
        if not linha.artigo_ref:
            continue
        linha_norm = _normalise(linha.designacao or '')
        score = _similarity(desc_norm, linha_norm)
        if score > best_score:
            best_score = score
            best_ref   = linha.artigo_ref

    if best_score >= 0.55:
        return best_ref, round(best_score * 0.85, 2), 'fuzzy'

    return None, 0.0, None


def match_orcamento_items(orcamento, pedido, aliases_db: list) -> list[dict]:
    """
    Match all items of an orcamento to the pedido's PHC articles.
    Returns list of match results (one per item).
    Updates ItemOrcamento.artigo_ref_match and match_confianca in-place.
    """
    results = []
    for item in orcamento.items:
        ref, conf, method = match_item_to_artigo(
            descricao       = item.descricao or '',
            referencia_forn = item.referencia or '',
            fornecedor      = orcamento.empresa or '',
            linhas_pedido   = pedido.linhas,
            aliases_db      = aliases_db
        )
        item.artigo_ref_match = ref
        item.match_confianca  = conf
        results.append({
            'item_id':    item.id,
            'descricao':  item.descricao,
            'artigo_ref': ref,
            'confianca':  conf,
            'method':     method,
        })
    return results


def build_comparison_matrix(pedido, orcamentos: list) -> list[dict]:
    """
    Build a comparison matrix: one row per pedido linha, columns per orcamento.

    Returns list of rows:
    {
      'linha': LinhaPedido,
      'orcamentos': [
        {
          'orcamento_id': int,
          'empresa': str,
          'item': ItemOrcamento | None,
          'preco_unitario': float,
          'total': float,
          'confianca': float,
          'matched': bool,
        }, ...
      ],
      'melhor_idx': int | None,   # index into orcamentos with lowest price
    }
    """
    matrix = []
    for linha in pedido.linhas:
        row = {'linha': linha, 'orcamentos': []}
        precos = []
        for orc in orcamentos:
            # Find best matching item in this orcamento for this linha
            best_item = None
            best_conf = 0.0
            for item in orc.items:
                if item.artigo_ref_match == linha.artigo_ref and linha.artigo_ref:
                    if item.match_confianca > best_conf:
                        best_item = item
                        best_conf = item.match_confianca
            # Fallback: unmatched items not yet associated
            preco = best_item.preco_unitario if best_item else None
            row['orcamentos'].append({
                'orcamento_id':  orc.id,
                'empresa':       orc.empresa,
                'item':          best_item,
                'preco_unitario': preco,
                'total':         (preco or 0) * linha.quantidade,
                'confianca':     best_conf,
                'matched':       best_item is not None,
            })
            if preco is not None:
                precos.append((len(row['orcamentos']) - 1, preco))

        # Find cheapest
        if precos:
            row['melhor_idx'] = min(precos, key=lambda x: x[1])[0]
        else:
            row['melhor_idx'] = None
        matrix.append(row)
    return matrix


def save_alias(db, artigo_ref: str, descricao_orig: str, fornecedor: str,
               referencia_forn: str, user_id: int, confianca: float = 1.0):
    """Create or update an alias mapping."""
    from models import AliasArtigo
    desc_norm = _normalise(descricao_orig)

    existing = AliasArtigo.query.filter_by(
        artigo_ref=artigo_ref,
        descricao_norm=desc_norm
    ).first()

    if existing:
        existing.vezes_usado += 1
        existing.confianca    = max(existing.confianca, confianca)
        if fornecedor and not existing.fornecedor:
            existing.fornecedor = fornecedor
    else:
        alias = AliasArtigo(
            artigo_ref     = artigo_ref,
            fornecedor     = fornecedor,
            descricao_orig = descricao_orig,
            descricao_norm = desc_norm,
            referencia_forn= referencia_forn,
            confianca      = confianca,
            criado_por     = user_id,
            vezes_usado    = 1,
        )
        db.session.add(alias)
    db.session.commit()
