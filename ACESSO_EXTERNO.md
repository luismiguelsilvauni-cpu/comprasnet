# Acesso Externo ao ComprasNet — Cloudflare Tunnel

## O que é o Cloudflare Tunnel?

Cria um URL público seguro (ex: `comprasnet-empresa.trycloudflare.com`) que aponta
para o ComprasNet a correr no seu servidor Windows local — sem abrir portas no router,
sem IP fixo, sem configurações de firewall. Completamente **gratuito**.

---

## Instalação (fazer uma vez)

### Passo 1 — Descarregar cloudflared

Aceder a:
```
https://github.com/cloudflare/cloudflared/releases/latest
```
Descarregar: `cloudflared-windows-amd64.exe`

Copiar para a pasta do ComprasNet e renomear para `cloudflared.exe`.

---

### Passo 2 — Opção A: URL temporário (sem conta, mais simples)

Abrir um segundo terminal/CMD na pasta do ComprasNet e correr:

```batch
cloudflared tunnel --url http://localhost:5000
```

Aparecerá algo como:
```
Your quick Tunnel has been created! Visit it at:
https://abc-def-ghi.trycloudflare.com
```

Este URL funciona **enquanto o terminal estiver aberto**.
Qualquer pessoa com o URL pode aceder (partilhe só com quem deve).

---

### Passo 3 — Opção B: URL fixo permanente (recomendado, requer conta gratuita Cloudflare)

**3.1** — Criar conta gratuita em [cloudflare.com](https://cloudflare.com)

**3.2** — Fazer login no cloudflared:
```batch
cloudflared tunnel login
```
Abre o browser para autorizar — clicar em "Authorize".

**3.3** — Criar o tunnel:
```batch
cloudflared tunnel create comprasnet
```
Guarda o UUID do tunnel — algo como `a1b2c3d4-...`.

**3.4** — Criar ficheiro de configuração `cloudflared_config.yml` na pasta do ComprasNet:
```yaml
tunnel: a1b2c3d4-XXXX-XXXX-XXXX-XXXXXXXXXXXX
credentials-file: C:\Users\User\.cloudflared\a1b2c3d4-XXXX.json

ingress:
  - hostname: comprasnet.suaempresa.com
    service: http://localhost:5000
  - service: http_status:404
```

**3.5** — Apontar o domínio (se tiver domínio próprio) ou usar subdomínio Cloudflare:
```batch
cloudflared tunnel route dns comprasnet comprasnet.suaempresa.com
```

**3.6** — Iniciar o tunnel:
```batch
cloudflared tunnel run comprasnet
```

---

## Iniciar automaticamente com o Windows

Para o tunnel arrancar com o Windows (sem precisar de abrir terminal):

```batch
cloudflared service install
```

Depois iniciar o serviço:
```batch
sc start cloudflared
```

---

## Script de arranque completo (`arrancar_externo.bat`)

Coloque este ficheiro na pasta do ComprasNet:

```batch
@echo off
echo A iniciar ComprasNet com acesso externo...

start "ComprasNet" cmd /k ".\iniciar.bat"
timeout /t 3

echo A iniciar Cloudflare Tunnel...
cloudflared tunnel --url http://localhost:5000

pause
```

---

## Segurança

⚠️ **Importante:** com acesso externo, qualquer pessoa com o URL pode tentar
aceder ao ComprasNet. Garanta que:

- Todos os utilizadores têm passwords fortes
- A conta `admin` tem password diferente do padrão `admin123`
- Considere adicionar autenticação Cloudflare Access (gratuita) para
  restringir o acesso por email autorizado

Para adicionar Cloudflare Access:
No painel Cloudflare → **Zero Trust** → **Access** → **Applications** →
adicionar o URL do tunnel e definir emails autorizados.

---

## Resumo das opções

| | URL Temporário | URL Fixo (conta CF) |
|---|---|---|
| Conta necessária | ❌ Não | ✅ Sim (gratuita) |
| URL muda | Sim (cada vez) | ❌ Não (sempre igual) |
| Arranque automático | ❌ | ✅ |
| Custo | Grátis | Grátis |
| Configuração | 1 comando | 15 minutos |
