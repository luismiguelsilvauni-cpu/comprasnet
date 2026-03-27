# Guia de Migrações — ComprasNet

## Conceito

O ComprasNet usa **Alembic** (via Flask-Migrate) para versionar a base de dados.
Cada alteração ao modelo de dados gera um ficheiro de migração numerado na pasta `migrations/versions/`.

Quando um utilizador executa `atualizar.bat`, o Alembic aplica apenas as migrações
que ainda não foram aplicadas na sua BD — os dados existentes ficam **sempre intactos**.

```
migrations/
  versions/
    0001_versao_inicial.py       ← tabelas originais
    0002_adicionar_campo_xyz.py  ← nova coluna adicionada na v1.1
    0003_tabela_encomendas.py    ← nova tabela na v1.2
```

---

## Como fazer uma alteração ao modelo

### Exemplo: adicionar um campo `codigo_interno` à tabela `pedidos_compra`

**Passo 1 — Alterar o modelo em `models.py`**
```python
class PedidoCompra(db.Model):
    ...
    codigo_interno = db.Column(db.String(50))   # ← linha nova
```

**Passo 2 — Gerar a migração**
```bash
# Ativar o ambiente virtual primeiro
venv\Scripts\activate

# Gerar o ficheiro de migração automaticamente
flask db migrate -m "adicionar_codigo_interno_pedido"
```
Isto cria um ficheiro em `migrations/versions/` com o código SQL de upgrade e downgrade.

**Passo 3 — Rever o ficheiro gerado**
Abrir o ficheiro criado e confirmar que o `upgrade()` faz o que é esperado.
O Alembic deteta adições/remoções de colunas e tabelas automaticamente.

**Passo 4 — Testar localmente**
```bash
flask db upgrade     # aplica a migração
flask db downgrade   # reverte (para testar rollback)
flask db upgrade     # volta a aplicar
```

**Passo 5 — Incluir na entrega**
Incluir o novo ficheiro `migrations/versions/XXXX_....py` no ZIP de atualização.
Os utilizadores executam `atualizar.bat` e a migração é aplicada automaticamente.

---

## Comandos úteis

```bash
# Ver versão atual da BD
flask db current

# Ver historial de migrações
flask db history

# Ver migrações pendentes
flask db show

# Aplicar todas as migrações pendentes
flask db upgrade

# Reverter uma migração
flask db downgrade

# Reverter para versão específica
flask db downgrade 0001
```

---

## Casos especiais

### Nova tabela
O Alembic deteta automaticamente — só precisa de fazer `flask db migrate`.

### Remover coluna
⚠️ SQLite não suporta `DROP COLUMN` antes da versão 3.35.
Para SQLite, a migração faz recreate da tabela. O Alembic gere isso automaticamente
mas convém sempre testar antes de distribuir.

### Renomear coluna
O Alembic **não deteta** renames — interpreta como drop + add.
Edite o ficheiro de migração gerado para usar `op.alter_column()` manualmente:
```python
op.alter_column('pedidos_compra', 'titulo_antigo', new_column_name='titulo_novo')
```

### Dados de seed em migrações
Se uma nova funcionalidade precisa de dados iniciais, adicione-os na migração:
```python
def upgrade():
    op.add_column('config_ia', sa.Column('timeout', sa.Integer(), default=120))
    # Seed default value for existing rows
    op.execute("UPDATE config_ia SET timeout = 120 WHERE timeout IS NULL")
```

---

## Backups automáticos

O `atualizar.bat` faz backup automático antes de cada migração para `backups/`.
Os ficheiros têm o formato `compras_backup_YYYY-MM-DD_HH-MM.db`.

Recomenda-se também backup periódico da pasta `instance/` e `uploads/`
para um NAS ou pasta partilhada na rede.

---

## Estrutura de versões sugerida

| Versão | Ficheiro migração              | Descrição                    |
|--------|-------------------------------|------------------------------|
| 1.0    | `0001_versao_inicial.py`      | Tabelas base                 |
| 1.0    | `0002_tabelas_phc_ia.py`      | Integração PHC + IA          |
| 1.1    | `0003_...py`                  | Próxima iteração             |
| 1.2    | `0004_...py`                  | Iteração seguinte            |
