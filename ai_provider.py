"""
ai_provider.py
──────────────
Abstração do provedor de IA para análise de PDFs.
Suporta:
  - LM Studio  (servidor local OpenAI-compatible, porta 1234)
  - Ollama     (servidor local OpenAI-compatible, porta 11434)
  - Claude API (Anthropic, requer chave API + internet)

O ComprasNet usa sempre a mesma função analyze_pdf().
A escolha do provedor é feita nas configurações e guardada na BD.
"""

import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ── Prompt (igual para todos os provedores) ───────────────────────────────────

SYSTEM_PROMPT = """És um assistente especializado em análise de documentos comerciais portugueses.
A tua tarefa é extrair informação estruturada de orçamentos e propostas comerciais.
Responde SEMPRE e APENAS com JSON válido, sem texto adicional, sem markdown, sem ```."""

def _build_user_prompt(pdf_text: str, filename: str) -> str:
    return f"""Analisa este orçamento/proposta comercial e extrai as informações.

Ficheiro: {filename}

Texto do documento:
{pdf_text[:3500]}

Retorna APENAS este objeto JSON preenchido (sem mais nada):
{{
    "empresa": "Nome da empresa fornecedora",
    "nif": null,
    "data_orcamento": null,
    "numero_orcamento": null,
    "subtotal": 0.00,
    "desconto_total": 0.00,
    "desconto_percentagem": 0.00,
    "iva_valor": 0.00,
    "total": 0.00,
    "moeda": "EUR",
    "validade": null,
    "contacto": null,
    "items": [
        {{
            "descricao": "Descrição do produto/serviço",
            "referencia": null,
            "quantidade": 1,
            "unidade": "un",
            "preco_unitario": 0.00,
            "desconto_item": 0.00,
            "total_item": 0.00
        }}
    ],
    "observacoes": null
}}

Regras obrigatórias:
- Valores monetários são números decimais (float), nunca strings
- Datas no formato YYYY-MM-DD ou null se não existir
- Se não encontrares empresa, usa "Fornecedor Desconhecido"
- Extrai TODOS os itens/linhas de produto que encontrares
- O total deve incluir IVA se disponível"""


def _parse_response(raw: str) -> tuple[dict | None, str | None]:
    """Extract JSON from model response, tolerating markdown fences."""
    text = raw.strip()
    # Strip ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # Find first { and last }
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1:
        return None, f"Não foi encontrado JSON na resposta: {text[:200]}"
    try:
        return json.loads(text[start:end+1]), None
    except json.JSONDecodeError as e:
        return None, f"JSON inválido: {e} — resposta: {text[:200]}"


# ── LM Studio / Ollama (OpenAI-compatible endpoint) ──────────────────────────

def _call_openai_compat(base_url: str, model: str, pdf_text: str, filename: str,
                         timeout: int = 120) -> tuple[dict | None, str | None]:
    """
    POST to any OpenAI-compatible /v1/chat/completions endpoint.
    Works with LM Studio (port 1234) and Ollama (port 11434).
    Uses only stdlib urllib — no openai package needed.
    """
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": _build_user_prompt(pdf_text, filename)}
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
        "stream": False
    }).encode("utf-8")

    url = base_url.rstrip("/") + "/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"]
        return _parse_response(raw)
    except urllib.error.URLError as e:
        return None, f"Não foi possível ligar ao servidor de IA em {base_url} — {e.reason}"
    except (KeyError, IndexError) as e:
        return None, f"Resposta inesperada do servidor de IA: {e}"
    except Exception as e:
        return None, f"Erro inesperado: {e}"


def _call_lmstudio(cfg, pdf_text: str, filename: str) -> tuple[dict | None, str | None]:
    base_url = f"http://{cfg.lm_host}:{cfg.lm_port}"
    return _call_openai_compat(base_url, cfg.lm_model, pdf_text, filename)


def _call_ollama(cfg, pdf_text: str, filename: str) -> tuple[dict | None, str | None]:
    base_url = f"http://{cfg.lm_host}:{cfg.lm_port}"
    return _call_openai_compat(base_url, cfg.lm_model, pdf_text, filename)


def _call_claude(cfg, pdf_text: str, filename: str) -> tuple[dict | None, str | None]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.claude_api_key or "")
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(pdf_text, filename)}]
        )
        return _parse_response(msg.content[0].text)
    except ImportError:
        return None, "Biblioteca anthropic não instalada. Execute: pip install anthropic"
    except Exception as e:
        return None, f"Erro Claude API: {e}"


# ── Public interface ──────────────────────────────────────────────────────────

def analyze_pdf(cfg, pdf_text: str, filename: str) -> tuple[dict | None, str | None]:
    """
    Analyze a PDF quote using the configured AI provider.
    cfg: ConfigIA model instance (or None → returns fallback empty dict)
    Returns (data_dict, error_string).  One of them is always None.
    """
    if not cfg or not pdf_text.strip():
        return None, "Texto do PDF vazio ou sem configuração de IA."

    provider = cfg.provider if cfg else "lmstudio"

    if provider == "lmstudio":
        return _call_lmstudio(cfg, pdf_text, filename)
    elif provider == "ollama":
        return _call_ollama(cfg, pdf_text, filename)
    elif provider == "claude":
        return _call_claude(cfg, pdf_text, filename)
    else:
        return None, f"Provedor desconhecido: {provider}"


def test_provider(cfg) -> tuple[bool, str]:
    """Quick connectivity test. Returns (ok, message)."""
    if cfg.provider in ("lmstudio", "ollama"):
        # Just check if the /v1/models endpoint responds
        url = f"http://{cfg.lm_host}:{cfg.lm_port}/v1/models"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            models = [m["id"] for m in data.get("data", [])]
            label = "LM Studio" if cfg.provider == "lmstudio" else "Ollama"
            if models:
                return True, f"{label} ativo — {len(models)} modelo(s) disponível(eis): {', '.join(models[:3])}"
            else:
                return True, f"{label} ativo mas sem modelos carregados. Carregue um modelo primeiro."
        except urllib.error.URLError as e:
            label = "LM Studio" if cfg.provider == "lmstudio" else "Ollama"
            porta = cfg.lm_port
            return False, (f"{label} não encontrado em {cfg.lm_host}:{porta}. "
                           f"Verifique se o servidor está iniciado e o 'Local Server' ativo.")
    elif cfg.provider == "claude":
        if not cfg.claude_api_key:
            return False, "Chave API Claude não configurada."
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=cfg.claude_api_key)
            client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=10,
                                   messages=[{"role":"user","content":"ping"}])
            return True, "Claude API ligada com sucesso."
        except Exception as e:
            return False, f"Erro Claude API: {e}"
    return False, "Provedor inválido."


# ── Model recommendations ─────────────────────────────────────────────────────

RECOMMENDED_MODELS = {
    "gemini": [
        {
            "id":    "gemini-1.5-flash",
            "label": "Gemini 1.5 Flash (Recomendado — Gratuito)",
            "ram":   "Cloud — sem requisitos locais",
            "notes": "Muito rápido, excelente para PDFs. Tier gratuito generoso (~1500 req/dia).",
            "search": "gemini-1.5-flash"
        },
        {
            "id":    "gemini-1.5-pro",
            "label": "Gemini 1.5 Pro (Mais preciso)",
            "ram":   "Cloud — sem requisitos locais",
            "notes": "Melhor qualidade, quota gratuita menor (50 req/dia).",
            "search": "gemini-1.5-pro"
        },
    ],
    "lmstudio": [
        {
            "id":    "qwen2.5-7b-instruct",
            "label": "Qwen 2.5 7B Instruct (Recomendado)",
            "ram":   "~5 GB RAM",
            "notes": "Excelente para extração de dados em português. Melhor opção para PC partilhado.",
            "search": "qwen2.5-7b-instruct"
        },
        {
            "id":    "mistral-7b-instruct-v0.3",
            "label": "Mistral 7B Instruct v0.3",
            "ram":   "~5 GB RAM",
            "notes": "Bom desempenho geral, bom com tabelas e números.",
            "search": "mistral-7b-instruct-v0.3"
        },
        {
            "id":    "phi-3.5-mini-instruct",
            "label": "Phi 3.5 Mini (Mais leve)",
            "ram":   "~3 GB RAM",
            "notes": "Para PCs com pouca RAM disponível. Menos preciso mas funcional.",
            "search": "phi-3.5-mini-instruct"
        },
    ]
}
