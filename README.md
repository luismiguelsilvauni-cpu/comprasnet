# ComprasNet — Gestão de Orçamentos e Compras

Sistema de gestão de pedidos de compra com análise automática de PDFs por IA.
Integra no fluxo de trabalho de empresas que utilizam PHC para faturação.

---

## 🚀 Instalação e Arranque

### Requisitos
- Python 3.10 ou superior
- Chave API Anthropic (para análise de PDFs)
- Rede local (LAN) para acesso multi-posto

### Windows — Arranque Rápido
1. Extraia a pasta `compras` para o servidor ou PC principal
2. Clique duas vezes em `iniciar.bat`
3. Introduza a chave API Anthropic quando pedido
4. Aceda em `http://localhost:5000`

### Linux/Mac
```bash
cd compras
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
python app.py
```

---

## 🔑 Primeiro Login
- **Utilizador:** `admin`
- **Palavra-passe:** `admin123`

> ⚠️ Altere a palavra-passe após o primeiro acesso.

---

## 🌐 Acesso em Rede

O servidor corre em `0.0.0.0:5000` — todos os computadores na mesma rede podem aceder:

```
http://[IP-DO-SERVIDOR]:5000
```

Para descobrir o IP do servidor:
- Windows: `ipconfig` → IPv4 Address
- Linux/Mac: `ip addr` ou `ifconfig`

Para acesso permanente, configure o servidor para arrancar automaticamente com o Windows (Serviços ou Tarefa Agendada).

---

## 📦 Funcionalidades

### Pedidos de Compra
- Crie pedidos com título, departamento e prioridade
- Acompanhe o estado: Aberto → Em Análise → Aprovado

### Orçamentos PDF
- Carregue até **3 PDFs** por pedido
- A IA extrai automaticamente:
  - Nome da empresa / fornecedor
  - NIF, número e data do orçamento
  - Subtotal, descontos, IVA e total
  - Linhas de produto com preços unitários
- Comparação visual dos 3 orçamentos
- Identificação automática do **melhor preço**

### Aprovação
- Selecione o orçamento vencedor
- Registo de quem aprovou e quando
- PDF original sempre disponível para download

### Utilizadores
- Login individual por utilizador
- Perfis: Administrador / Utilizador
- Gestão de utilizadores pelo admin

---

## 🗂️ Estrutura de Ficheiros

```
compras/
├── app.py              # Aplicação principal Flask
├── models.py           # Modelos da base de dados
├── requirements.txt    # Dependências Python
├── iniciar.bat         # Arranque Windows
├── instance/
│   └── compras.db      # Base de dados SQLite (criada automaticamente)
├── uploads/            # PDFs carregados
└── templates/          # Páginas HTML
```

---

## 🔒 Segurança

- Autenticação obrigatória para todas as páginas
- Senhas guardadas com hash bcrypt
- Ficheiros PDF acessíveis apenas a utilizadores autenticados
- Para produção, altere `SECRET_KEY` em `app.py`

---

## 🛠️ Personalização

### Alterar porta
Em `app.py`, linha final:
```python
app.run(host='0.0.0.0', port=5000)  # Altere 5000 para outra porta
```

### Base de dados
SQLite por defeito — adequado para até ~20 utilizadores simultâneos.
Para mais utilizadores, migre para PostgreSQL alterando `SQLALCHEMY_DATABASE_URI`.

---

## 📞 Notas PHC

O ComprasNet é independente do PHC mas complementar:
- Use o ComprasNet para gerir o processo de obtenção de orçamentos
- Após aprovação, introduza a encomenda no PHC normalmente
- O número de referência PC-XXXX pode ser usado como nota interna no PHC
