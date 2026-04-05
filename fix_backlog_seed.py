"""fix_backlog_seed.py - Popula o backlog com os dados originais"""
import sqlite3, os

db_path = 'compras.db'
if not os.path.exists(db_path):
    print("ERRO: compras.db nao encontrado")
    exit()

conn = sqlite3.connect(db_path)

# Create table if needed
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

# Check existing items
count = conn.execute("SELECT COUNT(*) FROM backlog_item").fetchone()[0]
print(f"Items existentes: {count}")

items = [
    # CONCLUIDAS
    ('Calendario dashboard - gravar evento', 'Erro None.strip e sessao corrigidos', 'bug', 'done', 1),
    ('Calendario multi-dia', 'Eventos com inicio/fim mostram barra continua', 'small', 'done', 2),
    ('Pesquisa de fornecedor no evento', 'Campo com sugestoes do PHC', 'small', 'done', 3),
    ('Reposicao server-side', 'Paginacao, pesquisa e ordenacao rapidas', 'large', 'done', 4),
    ('Analise IA por artigo', 'Recomendacao com justificacao detalhada', 'medium', 'done', 5),
    ('Historico vendas com nr factura', 'Data, factura e cliente por linha', 'medium', 'done', 6),
    ('Ajuda interactiva nos filtros', 'Modal com exemplos para cada parametro', 'small', 'done', 7),
    ('Agrupamento por fornecedor', 'Artigos a encomendar agrupados por fornecedor PHC', 'large', 'done', 8),
    ('Barra de estado Por Fornecedor', 'Loading modal funcional', 'bug', 'done', 9),
    ('Ligacao PHC tabela fn/fo', 'Fornecedor real por artigo via facturas de compra', 'medium', 'done', 10),
    ('API reposicao com paginacao', 'Endpoint server-side com filtros e sort', 'large', 'done', 11),
    ('Modal loading global', 'Barra de progresso em base.html', 'small', 'done', 12),
    # FIXES PENDENTES
    ('Auto-update ao iniciar servidor', 'Servidor puxa actualizacoes do GitHub antes de arrancar, sem intervencao manual', 'bug', 'pending', 20),
    ('Historico de versoes desactualizado', 'Changelog parado na v1.8 - actualizar com todas as funcionalidades recentes', 'bug', 'pending', 21),
    # PEQUENAS
    ('Editor de logotipo melhorado', 'Controlo de posicao, tamanho, filtros e preview em tempo real', 'small', 'pending', 30),
    ('Assinatura de email', 'Editor de assinatura com suporte a imagens para emails de consulta', 'small', 'pending', 31),
    ('Score e alertas no artigo', 'Badge de score mais visual e alertas de mono-cliente, preco alto', 'small', 'pending', 32),
    # MEDIAS
    ('Email de consulta ao fornecedor', 'Janela com assunto, designacoes, quantidades e envio directo. Gerada a partir da lista de compras', 'medium', 'pending', 40),
    ('Menu Embarcacoes', 'Associar cliente + dados do motor (marca, modelo, nr serie) e caixa redutora. Listagem de artigos frequentes', 'medium', 'pending', 41),
    ('Menu Tecnico - Catalogos PDF', 'Upload de PDFs de pecas associados a nr de serie. Pesquisa por nr serie, visualizacao e download', 'medium', 'pending', 42),
    ('Analise de stock - Excesso e Obsoletos', 'Identifica artigos com stock excessivo, sem vendas recentes e classificacao ABC automatica', 'medium', 'pending', 43),
    ('IA global de reposicao', 'Analise de toda a carteira de artigos com recomendacoes priorizadas, nao apenas artigo a artigo', 'medium', 'pending', 44),
    # GRANDES
    ('Painel global de gestao de stock', '20+ metricas: valor total custo/venda, margem, GMROI, DIO, rotacao, ABC, top/bottom produtos, fornecedores, alertas', 'large', 'pending', 50),
    ('Dashboard financeiro', 'KPIs financeiros avancados: capital imobilizado, stock parado, ROI, sell-through rate, variacao de precos', 'large', 'pending', 51),
    # EPICAS
    ('Motor de previsao avancado', 'Previsao de vendas com machine learning, sazonalidade automatica, alertas preditivos e optimizacao de encomendas', 'epic', 'pending', 60),
]

added = 0
for titulo, descricao, tipo, estado, prioridade in items:
    exists = conn.execute("SELECT id FROM backlog_item WHERE titulo=?", (titulo,)).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO backlog_item (titulo,descricao,tipo,estado,prioridade) VALUES (?,?,?,?,?)",
            (titulo, descricao, tipo, estado, prioridade)
        )
        added += 1

conn.commit()
conn.close()
print(f"OK: {added} items adicionados. Total: {count+added}")
