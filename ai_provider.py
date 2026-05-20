"""
ai_provider.py
──────────────
Abstração do provedor de IA para análise de PDFs.
Suporta LM Studio, Ollama, Claude API e Gemini Flash (gratuito).
"""

import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

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

Regras:
- Valores monetários são floats, nunca strings
- Datas no formato YYYY-MM-DD ou null
- Se não encontrares empresa, usa "Fornecedor Desconhecido"
- Extrai TODOS os itens/linhas de produto"""


def _parse_response(raw: str) -> tuple:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1:
        return None, f"JSON não encontrado: {text[:200]}"
    try:
        return json.loads(text[start:end+1]), None
    except json.JSONDecodeError as e:
        return None, f"JSON inválido: {e}"


# ── Gemini auto-detect ────────────────────────────────────────────────────────

def _get_best_gemini_model(api_key: str) -> str:
    """Query Google API and return best available model. Auto-updates if deprecated."""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        models = []
        for m in data.get('models', []):
            if 'generateContent' in m.get('supportedGenerationMethods', []):
                name = m['name'].replace('models/', '')
                if 'flash' in name and 'lite' not in name and 'thinking' not in name:
                    models.append(name)
        models.sort(reverse=True)
        if models:
            return models[0]
    except Exception:
        pass

    # Fallback: try known models in order
    for model in ['gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-1.5-flash-latest']:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = json.dumps({"contents": [{"parts": [{"text": "hi"}]}]}).encode()
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as resp:
                json.loads(resp.read())
            return model
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            return model
        except Exception:
            continue
    return 'gemini-2.0-flash'


# ── Providers ─────────────────────────────────────────────────────────────────

def _call_openai_compat(base_url: str, model: str, pdf_text: str, filename: str,
                         timeout: int = 120) -> tuple:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": _build_user_prompt(pdf_text, filename)}
        ],
        "temperature": 0.1, "max_tokens": 2000, "stream": False
    }).encode()
    url = base_url.rstrip("/") + "/v1/chat/completions"
    req = urllib.request.Request(url, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return _parse_response(data["choices"][0]["message"]["content"])
    except urllib.error.URLError as e:
        return None, f"Não foi possível ligar ao servidor de IA em {base_url} — {e.reason}"
    except Exception as e:
        return None, f"Erro inesperado: {e}"


def _call_lmstudio(cfg, pdf_text: str, filename: str) -> tuple:
    return _call_openai_compat(f"http://{cfg.lm_host}:{cfg.lm_port}",
                                cfg.lm_model, pdf_text, filename)


def _call_ollama(cfg, pdf_text: str, filename: str) -> tuple:
    return _call_openai_compat(f"http://{cfg.lm_host}:{cfg.lm_port}",
                                cfg.lm_model, pdf_text, filename)


def _call_claude(cfg, pdf_text: str, filename: str) -> tuple:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.claude_api_key or '')
        msg = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(pdf_text, filename)}])
        return _parse_response(msg.content[0].text)
    except ImportError:
        return None, "Biblioteca anthropic não instalada."
    except Exception as e:
        return None, f"Erro Claude API: {e}"


def _call_gemini(cfg, pdf_text: str, filename: str) -> tuple:
    """Call Google Gemini API via REST — no library needed, free tier."""
    api_key = cfg.gemini_api_key or ""
    if not api_key:
        return None, "Chave API Gemini não configurada."

    # Auto-detect best available model
    model = cfg.gemini_model or ""
    if not model or model in ('gemini-1.5-flash', 'gemini-1.5-pro'):
        model = _get_best_gemini_model(api_key)
        try:
            from models import ConfigIA, db
            cfg_db = ConfigIA.query.first()
            if cfg_db and cfg_db.gemini_model != model:
                cfg_db.gemini_model = model
                db.session.commit()
                logger.info(f"Gemini model auto-updated to: {model}")
        except Exception:
            pass

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        prompt = SYSTEM_PROMPT + "\n\n" + _build_user_prompt(pdf_text, filename)
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000}
        }).encode()
        req = urllib.request.Request(url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_response(text)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if "API_KEY_INVALID" in body:
            return None, "Chave API Gemini inválida."
        return None, f"Erro Gemini HTTP {e.code}: {body[:200]}"
    except Exception as e:
        return None, f"Erro Gemini: {e}"


# ── Public interface ──────────────────────────────────────────────────────────

def analyze_pdf(cfg, pdf_text: str, filename: str) -> tuple:
    if not cfg or not pdf_text.strip():
        return None, "Texto do PDF vazio ou sem configuração de IA."
    provider = cfg.provider if cfg else "lmstudio"
    if provider == "lmstudio":
        return _call_lmstudio(cfg, pdf_text, filename)
    elif provider == "ollama":
        return _call_ollama(cfg, pdf_text, filename)
    elif provider == "claude":
        return _call_claude(cfg, pdf_text, filename)
    elif provider == "gemini":
        return _call_gemini(cfg, pdf_text, filename)
    return None, f"Provedor desconhecido: {provider}"


def test_provider(cfg) -> tuple:
    if cfg.provider in ("lmstudio", "ollama"):
        url = f"http://{cfg.lm_host}:{cfg.lm_port}/v1/models"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            models = [m["id"] for m in data.get("data", [])]
            label = "LM Studio" if cfg.provider == "lmstudio" else "Ollama"
            if models:
                return True, f"{label} ativo — modelos: {', '.join(models[:3])}"
            return True, f"{label} ativo mas sem modelos carregados."
        except urllib.error.URLError as e:
            label = "LM Studio" if cfg.provider == "lmstudio" else "Ollama"
            return False, f"{label} não encontrado em {cfg.lm_host}:{cfg.lm_port}."

    elif cfg.provider == "gemini":
        if not cfg.gemini_api_key:
            return False, "Chave API Gemini não configurada."
        try:
            model = _get_best_gemini_model(cfg.gemini_api_key)
            # Save detected model
            try:
                from models import ConfigIA, db
                cfg_db = ConfigIA.query.first()
                if cfg_db:
                    cfg_db.gemini_model = model
                    db.session.commit()
            except Exception:
                pass
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={cfg.gemini_api_key}"
            payload = json.dumps({"contents": [{"parts": [{"text": "ping"}]}]}).encode()
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            if data.get("candidates"):
                return True, f"✅ Gemini API OK! Modelo activo: {model} (gratuito)"
            return False, f"Resposta inesperada: {str(data)[:100]}"
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if "API_KEY_INVALID" in body:
                return False, "❌ Chave API inválida."
            if "PERMISSION_DENIED" in body:
                return False, "❌ Sem permissão. Active a API em aistudio.google.com."
            return False, f"❌ Erro HTTP {e.code}: {body[:150]}"
        except Exception as e:
            return False, f"❌ Erro: {e}"

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


def _call_openai_compat_text(base_url: str, model: str, system: str, user_msg: str,
                             timeout: int = 60) -> tuple:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg}
        ],
        "temperature": 0.7, "max_tokens": 1500, "stream": False
    }).encode()
    url = base_url.rstrip("/") + "/v1/chat/completions"
    req = urllib.request.Request(url, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip(), None
    except urllib.error.URLError as e:
        return None, f"Não foi possível ligar ao servidor de IA em {base_url} — {e.reason}"
    except Exception as e:
        return None, f"Erro inesperado: {e}"


def _call_claude_text(cfg, system: str, user_msg: str) -> tuple:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.claude_api_key or '')
        msg = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user_msg}])
        return msg.content[0].text.strip(), None
    except ImportError:
        return None, "Biblioteca anthropic não instalada."
    except Exception as e:
        return None, f"Erro Claude API: {e}"


def _call_gemini_text(cfg, system: str, user_msg: str) -> tuple:
    api_key = cfg.gemini_api_key or ""
    if not api_key:
        return None, "Chave API Gemini não configurada."
    model = cfg.gemini_model or "gemini-2.0-flash"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        prompt = system + "\n\n" + user_msg
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1500}
        }).encode()
        req = urllib.request.Request(url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip(), None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if "API_KEY_INVALID" in body:
            return None, "Chave API Gemini inválida."
        return None, f"Erro Gemini HTTP {e.code}: {body[:200]}"
    except Exception as e:
        return None, f"Erro Gemini: {e}"


def _call_text(cfg, system: str, user_msg: str) -> tuple:
    """Generic text generation using configured AI provider. Returns (text, error)."""
    if not cfg:
        return None, "Sem configuração de IA."
    provider = getattr(cfg, 'provider', 'lmstudio')
    if provider in ("lmstudio", "ollama"):
        return _call_openai_compat_text(
            f"http://{cfg.lm_host}:{cfg.lm_port}", cfg.lm_model, system, user_msg)
    elif provider == "claude":
        return _call_claude_text(cfg, system, user_msg)
    elif provider == "gemini":
        return _call_gemini_text(cfg, system, user_msg)
    return None, f"Provedor desconhecido: {provider}"


def search_company_brands(cfg, company_name: str) -> tuple:
    """Ask AI what brands/products a company represents. Returns (brands_csv, error)."""
    system = ("You are a knowledgeable assistant specialising in industrial, marine, "
              "and commercial suppliers worldwide. "
              "When given a company name, provide the company name, main brands and product lines "
              "they manufacture, represent, or distribute. "
              "Reply ONLY with comma-separated values — no explanations, "
              "no full sentences, no numbering.")

    user_msg = (f"For the company: {company_name}\n\n"
                f"Reply with ONLY the company name, followed by brands and product lines, "
                f"all separated by commas. "
                f"Format: Company Name, Brand1, Brand2, Product1, Product2, etc.\n"
                f"Example: Scanpart AB, Volvo, Jabsco, marine engines, pumps, filtration systems. "
                f"If you have no information about this company, reply with the company name only.")

    text, err = _call_text(cfg, system, user_msg)
    if err:
        return None, err
    # Clean up: remove quotes, extra spaces, empty tokens
    brands = ', '.join(
        b.strip().strip('"\'') for b in text.replace('\n', ',').split(',')
        if b.strip().strip('"\'')
    )
    return brands, None


def generate_inquiry_email(cfg, prompt_utilizador: str, fornecedor_nome: str,
                           contacto_nome: str, lingua: str, empresa_nome: str) -> tuple:
    """Generate a short, direct inquiry email. Returns (email_text, error)."""
    _linguas = {
        'pt': ('português europeu', 'Bom dia', 'Melhores cumprimentos'),
        'en': ('English',           'Good morning', 'Best regards'),
        'fr': ('français',          'Bonjour',       'Cordialement'),
        'es': ('español',           'Buenos días',   'Un cordial saludo'),
    }
    lang_label, saudacao, despedida = _linguas.get(lingua, _linguas['en'])
    primeiro_nome = contacto_nome.split()[0] if contacto_nome else ''
    abertura = f"{saudacao} {primeiro_nome}," if primeiro_nome else f"{saudacao},"

    system = ("És um assistente de comunicação empresarial. "
              "Rediges emails de consulta comercial curtos, directos e profissionais. "
              "Responde APENAS com o texto do email — sem explicações, sem markdown, sem ```.")

    user_msg = f"""Escreve um email de consulta comercial em {lang_label}.

REGRAS OBRIGATÓRIAS:
- Começa exactamente com "{abertura}"
- Vai directo ao assunto — sem apresentar a empresa nem contextualizar quem somos
- Corpo de 2 a 4 frases, claro e profissional
- Termina com "{despedida},"
- NÃO incluir nome, cargo, empresa, telefone nem qualquer assinatura (o utilizador adiciona manualmente)

Empresa destinatária: {fornecedor_nome}

O utilizador pretende consultar:
{prompt_utilizador}

Formato de saída:
Assunto: [assunto em {lang_label}]

{abertura}

[corpo]

{despedida},"""

    return _call_text(cfg, system, user_msg)


RECOMMENDED_MODELS = {
    "gemini": [
        {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash (Recomendado — Gratuito)",
         "ram": "Cloud", "notes": "Modelo mais recente e gratuito.", "search": "gemini-2.0-flash"},
        {"id": "gemini-2.0-flash-lite", "label": "Gemini 2.0 Flash Lite (Mais leve)",
         "ram": "Cloud", "notes": "Mais rápido, ideal para PDFs simples.", "search": "gemini-2.0-flash-lite"},
    ],
    "lmstudio": [
        {"id": "qwen2.5-7b-instruct", "label": "Qwen 2.5 7B Instruct (Recomendado)",
         "ram": "~5 GB RAM", "notes": "Excelente para português.", "search": "qwen2.5-7b-instruct"},
        {"id": "mistral-7b-instruct-v0.3", "label": "Mistral 7B Instruct",
         "ram": "~5 GB RAM", "notes": "Bom com tabelas e números.", "search": "mistral-7b-instruct-v0.3"},
        {"id": "phi-3.5-mini-instruct", "label": "Phi 3.5 Mini (Mais leve)",
         "ram": "~3 GB RAM", "notes": "Para PCs com pouca RAM.", "search": "phi-3.5-mini-instruct"},
    ]
}
