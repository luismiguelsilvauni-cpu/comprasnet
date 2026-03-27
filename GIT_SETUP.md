# ComprasNet — Git Setup e Fluxo de Atualizações

## CONFIGURAÇÃO INICIAL (fazer apenas uma vez)

### Passo 1 — Criar repositório no GitHub

1. Aceder a https://github.com/new
2. Preencher:
   - **Repository name:** `comprasnet`
   - **Visibility:** ● Private
   - **NÃO marcar** "Add a README file"
3. Clicar **Create repository**
4. Copiar o URL que aparece — será algo como:
   `https://github.com/SEU-USERNAME/comprasnet.git`

---

### Passo 2 — Abrir terminal na pasta do ComprasNet

No Windows Explorer, navegar até à pasta `compras/`.
Clicar com o botão direito numa área vazia → **"Open Git Bash here"**
(ou **"Open in Terminal"** no Windows 11)

---

### Passo 3 — Configurar Git (só na primeira vez)

Substituir pelo seu nome e email do GitHub:

```bash
git config --global user.name "O Seu Nome"
git config --global user.email "o-seu-email@exemplo.com"
```

---

### Passo 4 — Ligar o projeto ao GitHub

Copiar e colar estes comandos **um de cada vez**.
Substituir o URL pelo copiado no Passo 1:

```bash
git init
git add .
git commit -m "versao inicial comprasnet"
git branch -M main
git remote add origin https://github.com/SEU-USERNAME/comprasnet.git
git push -u origin main
```

O GitHub vai pedir utilizador e password (ou token).
Se pedir token: GitHub → Settings → Developer Settings → Personal Access Tokens → Generate new token (classic) → marcar "repo" → copiar e usar como password.

---

### Passo 5 — Verificar

Aceder a `https://github.com/SEU-USERNAME/comprasnet` no browser.
Deve ver todos os ficheiros do projeto. ✅

---

## RECEBER ATUALIZAÇÕES (fluxo normal)

Quando pedir uma alteração ao ComprasNet, vou entregar:

```
patch_v1.1_descricao.diff   ← ficheiro com as alterações
```

Para aplicar no servidor:

```bash
# 1. Aplicar o patch (substitui só os ficheiros alterados)
git apply patch_v1.1_descricao.diff

# 2. Atualizar dependências e migrar BD (preserva todos os dados)
atualizar.bat

# 3. Guardar no repositório
git add .
git commit -m "v1.1 descricao da alteracao"
git push
```

**Só estes 3 passos.** Os dados, orçamentos e configurações ficam intactos.

---

## SE ALGO CORRER MAL (rollback)

Para reverter completamente uma atualização:

```bash
# Ver histórico de versões
git log --oneline

# Reverter para a versão anterior (substituir HASH pelo código da versão)
git revert HEAD
atualizar.bat
```

Ou mais simples — o `atualizar.bat` faz backup automático da BD antes de cada update,
na pasta `backups/`. Pode restaurar manualmente se necessário.

---

## ESTRUTURA DE VERSÕES

| Versão | Commit | Descrição |
|--------|--------|-----------|
| 1.0.0  | inicial | Versão base — pedidos, orçamentos, PHC, LM Studio |
| 1.x.x  | ...     | Próximas iterações |

---

## NOTAS IMPORTANTES

- A pasta `instance/` (base de dados) está no `.gitignore` — **nunca vai para o GitHub**
- A pasta `uploads/` (PDFs) também está excluída
- Chaves API e passwords nunca são guardadas no repositório
- O repositório é **privado** — só você tem acesso
