import sqlite3, os

paths = ['instance/compras.db', 'compras.db']
db_path = next((p for p in paths if os.path.exists(p)), None)
if not db_path:
    print("ERRO: BD nao encontrada")
    exit(1)
print("BD:", db_path)

conn = sqlite3.connect(db_path)
conn.execute("""CREATE TABLE IF NOT EXISTS backlog_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descricao TEXT DEFAULT '',
    tipo TEXT DEFAULT 'medium',
    estado TEXT DEFAULT 'pending',
    prioridade INTEGER DEFAULT 10,
    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()

count = conn.execute("SELECT COUNT(*) FROM backlog_item").fetchone()[0]
print(f"Items existentes: {count}")

items = [
    ('Calendario dashboard - gravar evento','Erro None.strip e sessao corrigidos','bug','done',1),
    ('Calendario multi-dia','Eventos com inicio/fim mostram barra continua','small','done',2),
    ('Pesquisa fornecedor/cliente no evento','Campos com sugestoes do PHC no modal','small','done',3),
    ('Reposicao server-side','Paginacao, pesquisa e ordenacao rapidas','large','done',4),
    ('Analise IA por artigo','Recomendacao com justificacao detalhada','medium','done',5),
    ('Historico vendas com nr factura','Data, factura e cliente por linha','medium','done',6),
    ('Ajuda interactiva nos filtros','Modal com exemplos para cada parametro','small','done',7),
    ('Agrupamento por fornecedor','Artigos agrupados por fornecedor PHC','large','done',8),
    ('Barra de estado Por Fornecedor','Loading modal funcional','bug','done',9),
    ('Ligacao PHC tabela fn/fo','Fornecedor real por artigo via facturas','medium','done',10),
    ('API reposicao com paginacao','Endpoint server-side com filtros e sort','large','done',11),
    ('Modal loading global','Barra de progresso em base.html','small','done',12),
    ('Backlog editavel','Menu backlog com CRUD completo','medium','done',13),
    ('Auto-update ao iniciar servidor','Servidor puxa actualizacoes do GitHub antes de arrancar','bug','pending',20),
    ('Historico de versoes desactualizado','Actualizar changelog com funcionalidades recentes','bug','pending',21),
    ('Editor de logotipo melhorado','Controlo de posicao, tamanho e preview em tempo real','small','pending',30),
    ('Assinatura de email','Editor de assinatura com imagens para emails de consulta','small','pending',31),
    ('Score e alertas no artigo','Badge de score visual e alertas de risco','small','pending',32),
    ('Email de consulta ao fornecedor','Janela com artigos, quantidades e envio directo','medium','pending',40),
    ('Menu Embarcacoes','Cliente, motor, caixa redutora, artigos frequentes','medium','pending',41),
    ('Menu Tecnico - Catalogos PDF','Upload PDFs associados a nr serie, visualizacao e download','medium','pending',42),
    ('Analise stock - Excesso e Obsoletos','Stock excessivo, sem vendas recentes, ABC','medium','pending',43),
    ('IA global de reposicao','Analise de toda a carteira com recomendacoes priorizadas','medium','pending',44),
    ('Painel global de gestao de stock','20+ metricas: valor, margem, GMROI, ABC, alertas','large','pending',50),
    ('Dashboard financeiro','Capital imobilizado, ROI, sell-through, variacao precos','large','pending',51),
    ('Motor de previsao avancado','ML, sazonalidade automatica, alertas preditivos','epic','pending',60),
]

added = 0
for titulo, descricao, tipo, estado, prioridade in items:
    exists = conn.execute("SELECT id FROM backlog_item WHERE titulo=?", (titulo,)).fetchone()
    if not exists:
        conn.execute("INSERT INTO backlog_item (titulo,descricao,tipo,estado,prioridade) VALUES (?,?,?,?,?)",
                     (titulo, descricao, tipo, estado, prioridade))
        added += 1

conn.commit()
conn.close()
print(f"OK: {added} items adicionados. Total: {count+added}")
