from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    nome          = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin      = db.Column(db.Boolean, default=False)
    email         = db.Column(db.String(200))
    must_change_password = db.Column(db.Boolean, default=False)
    departamento  = db.Column(db.String(100))
    data_criacao  = db.Column(db.DateTime, default=datetime.utcnow)
    pedidos_criados       = db.relationship('PedidoCompra', foreign_keys='PedidoCompra.criado_por', backref='criador', lazy=True)
    orcamentos_carregados = db.relationship('Orcamento', backref='carregador', lazy=True)

class ArtigoPHC(db.Model):
    __tablename__ = 'artigos_phc'
    id                    = db.Column(db.Integer, primary_key=True)
    referencia            = db.Column(db.String(50), unique=True, nullable=False, index=True)
    designacao            = db.Column(db.String(300))
    stock_atual           = db.Column(db.Float, default=0)
    preco_custo           = db.Column(db.Float, default=0)
    preco_custo_ponderado = db.Column(db.Float, default=0)
    unidade               = db.Column(db.String(20), default='un')
    familia               = db.Column(db.String(100))
    taxa_iva              = db.Column(db.Float, default=23)
    pvp                   = db.Column(db.Float, default=0)
    ultimo_preco_entrada  = db.Column(db.Float, default=0)
    ultima_sync           = db.Column(db.DateTime)
    aliases               = db.relationship('AliasArtigo', backref='artigo', lazy=True, cascade='all, delete-orphan')

class AliasArtigo(db.Model):
    """Maps supplier descriptions to PHC articles. Learned over time."""
    __tablename__ = 'aliases_artigo'
    id             = db.Column(db.Integer, primary_key=True)
    artigo_ref     = db.Column(db.String(50), db.ForeignKey('artigos_phc.referencia'), nullable=False, index=True)
    fornecedor     = db.Column(db.String(200))          # supplier name (nullable = any supplier)
    descricao_orig = db.Column(db.String(500))          # exact description from supplier PDF
    descricao_norm = db.Column(db.String(500))          # normalised lowercase for matching
    referencia_forn= db.Column(db.String(100))          # supplier's own reference code
    confianca      = db.Column(db.Float, default=1.0)   # 1.0=manual, 0.x=auto-learned
    criado_por     = db.Column(db.Integer, db.ForeignKey('users.id'))
    data_criacao   = db.Column(db.DateTime, default=datetime.utcnow)
    vezes_usado    = db.Column(db.Integer, default=0)

class FornecedorPHC(db.Model):
    __tablename__ = 'fornecedores_phc'
    id          = db.Column(db.Integer, primary_key=True)
    numero      = db.Column(db.Integer, unique=True, nullable=False, index=True)
    nome        = db.Column(db.String(200))
    nif         = db.Column(db.String(20))
    morada      = db.Column(db.String(300))
    localidade  = db.Column(db.String(100))
    cod_postal  = db.Column(db.String(20))
    telefone    = db.Column(db.String(50))
    email       = db.Column(db.String(150))
    ultima_sync = db.Column(db.DateTime)
    marcas      = db.Column(db.Text, default='')  # comma-separated brands this supplier handles
    # NAV fields (manual, never overwritten by PHC sync)
    nav_telefone  = db.Column(db.String(50),  default='')
    nav_email     = db.Column(db.String(150), default='')
    nav_morada    = db.Column(db.String(300), default='')
    nav_notas     = db.Column(db.Text,        default='')

class ConfigPHC(db.Model):
    __tablename__ = 'config_phc'
    id           = db.Column(db.Integer, primary_key=True)
    servidor     = db.Column(db.String(200), default='localhost')
    porta        = db.Column(db.Integer, default=1433)
    base_dados   = db.Column(db.String(100), default='PHC')
    autenticacao = db.Column(db.String(20), default='sql')
    utilizador   = db.Column(db.String(100), default='sa')
    password     = db.Column(db.String(200), default='')
    ultima_sync  = db.Column(db.DateTime)
    sync_auto    = db.Column(db.Boolean, default=False)
    sync_hora    = db.Column(db.String(5), default='06:00')
    driver       = db.Column(db.String(100), default='ODBC Driver 17 for SQL Server')

class PedidoCompra(db.Model):
    __tablename__ = 'pedidos_compra'
    id             = db.Column(db.Integer, primary_key=True)
    titulo         = db.Column(db.String(200), nullable=False)
    descricao      = db.Column(db.Text)
    departamento   = db.Column(db.String(100))
    prioridade     = db.Column(db.String(20), default='normal')
    estado         = db.Column(db.String(30), default='aberto')
    cliente_id     = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    criado_por     = db.Column(db.Integer, db.ForeignKey('users.id'))
    aprovado_por   = db.Column(db.Integer, db.ForeignKey('users.id'))
    aprovador      = db.relationship('User', foreign_keys=[aprovado_por])
    cliente        = db.relationship('Cliente', foreign_keys=[cliente_id])
    data_criacao   = db.Column(db.DateTime, default=datetime.utcnow)
    data_aprovacao = db.Column(db.DateTime)
    linhas         = db.relationship('LinhaPedido', backref='pedido', lazy=True,
                                     cascade='all, delete-orphan', order_by='LinhaPedido.ordem')
    orcamentos     = db.relationship('Orcamento', backref='pedido', lazy=True,
                                     cascade='all, delete-orphan')

class LinhaPedido(db.Model):
    __tablename__ = 'linhas_pedido'
    id              = db.Column(db.Integer, primary_key=True)
    pedido_id       = db.Column(db.Integer, db.ForeignKey('pedidos_compra.id'), nullable=False)
    ordem           = db.Column(db.Integer, default=0)
    artigo_ref      = db.Column(db.String(50), db.ForeignKey('artigos_phc.referencia'), nullable=True, index=True)
    referencia      = db.Column(db.String(50))
    designacao      = db.Column(db.String(300))
    unidade         = db.Column(db.String(20), default='un')
    quantidade      = db.Column(db.Float, default=1)
    stock_atual     = db.Column(db.Float, default=0)
    preco_custo_ref = db.Column(db.Float, default=0)
    preco_pcp_ref   = db.Column(db.Float, default=0)
    fornecedor_hab  = db.Column(db.String(200))
    observacoes     = db.Column(db.String(500))
    cliente_id      = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    fornecedores_json = db.Column(db.Text, default='[]')  # JSON list [{id,nome,nif}]
    status          = db.Column(db.String(20), default='nao_encomendado')  # nao_encomendado/pendente/recebido/cancelado
    # back-ref to PHC article for live data
    artigo          = db.relationship('ArtigoPHC', foreign_keys=[artigo_ref], lazy=True)

class Orcamento(db.Model):
    __tablename__ = 'orcamentos'
    id                   = db.Column(db.Integer, primary_key=True)
    pedido_id            = db.Column(db.Integer, db.ForeignKey('pedidos_compra.id'), nullable=False)
    empresa              = db.Column(db.String(200))
    nif                  = db.Column(db.String(20))
    numero_orcamento     = db.Column(db.String(50))
    contacto             = db.Column(db.String(200))
    data_orcamento       = db.Column(db.Date)
    validade             = db.Column(db.Date)
    subtotal             = db.Column(db.Float, default=0)
    desconto_total       = db.Column(db.Float, default=0)
    desconto_percentagem = db.Column(db.Float, default=0)
    iva_valor            = db.Column(db.Float, default=0)
    total                = db.Column(db.Float, default=0)
    moeda                = db.Column(db.String(10), default='EUR')
    observacoes          = db.Column(db.Text)
    ficheiro_pdf         = db.Column(db.String(300))
    dados_brutos         = db.Column(db.Text)
    selecionado          = db.Column(db.Boolean, default=False)
    carregado_por        = db.Column(db.Integer, db.ForeignKey('users.id'))
    data_upload          = db.Column(db.DateTime, default=datetime.utcnow)
    items                = db.relationship('ItemOrcamento', backref='orcamento', lazy=True,
                                           cascade='all, delete-orphan')

class ItemOrcamento(db.Model):
    __tablename__ = 'items_orcamento'
    id             = db.Column(db.Integer, primary_key=True)
    orcamento_id   = db.Column(db.Integer, db.ForeignKey('orcamentos.id'), nullable=False)
    descricao      = db.Column(db.String(500))
    referencia     = db.Column(db.String(100))
    quantidade     = db.Column(db.Float, default=1)
    unidade        = db.Column(db.String(20), default='un')
    preco_unitario = db.Column(db.Float, default=0)
    desconto_item  = db.Column(db.Float, default=0)
    total_item     = db.Column(db.Float, default=0)
    # Matched PHC article (set after alias matching)
    artigo_ref_match = db.Column(db.String(50), nullable=True)
    match_confianca  = db.Column(db.Float, default=0)   # 0=no match, 1=exact

class ConfigIA(db.Model):
    __tablename__ = 'config_ia'
    id             = db.Column(db.Integer, primary_key=True)
    provider       = db.Column(db.String(20), default='lmstudio')  # lmstudio|ollama|claude|gemini
    # LM Studio / Ollama
    lm_host        = db.Column(db.String(100), default='localhost')
    lm_port        = db.Column(db.Integer, default=1234)
    lm_model       = db.Column(db.String(200), default='')
    # Claude API
    claude_api_key = db.Column(db.String(200), default='')
    # Gemini API
    gemini_api_key = db.Column(db.String(200), default='')
    gemini_model   = db.Column(db.String(100), default='gemini-1.5-flash')
    # Meta
    ultimo_teste   = db.Column(db.DateTime)
    teste_ok       = db.Column(db.Boolean, default=False)

class ConfigReposicao(db.Model):
    """User-editable replenishment parameters (one row per article or global)."""
    __tablename__ = 'config_reposicao'
    id                          = db.Column(db.Integer, primary_key=True)
    artigo_ref                  = db.Column(db.String(50), nullable=True, index=True)  # NULL = global
    meses_historico             = db.Column(db.Integer, default=24)
    lead_time_dias              = db.Column(db.Float, default=7)
    fator_seguranca             = db.Column(db.Float, default=1.5)
    meses_cobertura             = db.Column(db.Integer, default=2)
    custo_encomenda             = db.Column(db.Float, default=25.0)
    taxa_posse_anual            = db.Column(db.Float, default=0.20)
    quantidade_minima_encomenda = db.Column(db.Float, default=1)
    alertar_dias_cobertura      = db.Column(db.Integer, default=30)
    ignorar_parados_dias        = db.Column(db.Integer, default=365)
    min_anos_historico          = db.Column(db.Float,   default=2.0)
    min_meses_com_venda         = db.Column(db.Integer, default=3)
    min_total_vendido           = db.Column(db.Float,   default=3.0)
    ignorar_sem_movimento_anos  = db.Column(db.Float,   default=3.0)
    min_facturas_sugerir        = db.Column(db.Integer, default=8)
    min_facturas_sugerir        = db.Column(db.Integer, default=5)
    atualizado_em               = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_por              = db.Column(db.Integer, db.ForeignKey('users.id'))

class PendingMatch(db.Model):
    """Supplier line matches that need human confirmation."""
    __tablename__ = 'pending_matches'
    id                  = db.Column(db.Integer, primary_key=True)
    pedido_id           = db.Column(db.Integer, db.ForeignKey('pedidos_compra.id'), nullable=False)
    orcamento_id        = db.Column(db.Integer, db.ForeignKey('orcamentos.id'), nullable=False)
    item_id             = db.Column(db.Integer, db.ForeignKey('items_orcamento.id'), nullable=False)
    # Supplier side
    descricao_forn      = db.Column(db.String(500))
    referencia_forn     = db.Column(db.String(100))
    fornecedor          = db.Column(db.String(200))
    # AI/fuzzy suggestion
    artigo_ref_sugerido = db.Column(db.String(50), nullable=True)
    confianca_sugerido  = db.Column(db.Float, default=0)
    metodo              = db.Column(db.String(30))
    # Operator decision
    confirmado          = db.Column(db.Boolean, default=False)
    artigo_ref_final    = db.Column(db.String(50), nullable=True)
    confirmado_por      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    data_confirmacao    = db.Column(db.DateTime, nullable=True)
    criado_em           = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
#  CLIENTES + EMBARCAÇÕES
# ══════════════════════════════════════════════════════════════

class Cliente(db.Model):
    """Client profile — synced from PHC ec table + manual complement."""
    __tablename__ = 'clientes'
    id               = db.Column(db.Integer, primary_key=True)
    # PHC link
    phc_no           = db.Column(db.Integer, unique=True, nullable=True, index=True)
    # Core fields (from PHC or manual)
    nome             = db.Column(db.String(200), nullable=False)
    abreviatura      = db.Column(db.String(50))
    nif              = db.Column(db.String(20))
    morada           = db.Column(db.String(300))
    localidade       = db.Column(db.String(100))
    cod_postal       = db.Column(db.String(20))
    pais             = db.Column(db.String(50), default='Portugal')
    telefone         = db.Column(db.String(50))
    telemovel        = db.Column(db.String(50))
    email            = db.Column(db.String(150))
    website          = db.Column(db.String(200))
    # Extra manual fields
    notas            = db.Column(db.Text)
    ativo            = db.Column(db.Boolean, default=True)
    # Meta
    criado_em        = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em    = db.Column(db.DateTime, default=datetime.utcnow)
    ultima_sync_phc  = db.Column(db.DateTime)
    embarcacoes      = db.relationship('Embarcacao', backref='cliente',
                                       lazy=True, cascade='all, delete-orphan')


class Embarcacao(db.Model):
    """Vessel belonging to a client."""
    __tablename__ = 'embarcacoes'
    id               = db.Column(db.Integer, primary_key=True)
    cliente_id       = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    nome             = db.Column(db.String(200), nullable=False)
    matricula        = db.Column(db.String(50))
    tipo             = db.Column(db.String(100))   # Lancha, Veleiro, etc.
    ano_construcao   = db.Column(db.Integer)
    comprimento      = db.Column(db.Float)          # metros
    largura          = db.Column(db.Float)
    ativo            = db.Column(db.Boolean, default=True)
    notas            = db.Column(db.Text)
    criado_em        = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em    = db.Column(db.DateTime, default=datetime.utcnow)
    foto_path        = db.Column(db.String(300))   # main photo
    componentes      = db.relationship('ComponenteEmbarcacao', backref='embarcacao',
                                       lazy=True, cascade='all, delete-orphan')


class ComponenteEmbarcacao(db.Model):
    """Any mechanical component of a vessel (engine, gearbox, shaft, etc.)."""
    __tablename__ = 'componentes_embarcacao'
    id               = db.Column(db.Integer, primary_key=True)
    embarcacao_id    = db.Column(db.Integer, db.ForeignKey('embarcacoes.id'), nullable=False)
    categoria        = db.Column(db.String(100))   # Motor, Caixa Inversora, Veio, etc.
    label            = db.Column(db.String(200))   # display name
    marca            = db.Column(db.String(100))
    modelo           = db.Column(db.String(100))
    potencia         = db.Column(db.String(50))    # kW / CV
    num_serie        = db.Column(db.String(100))
    catalogo         = db.Column(db.String(100))   # catalog ref
    base_code        = db.Column(db.String(100))   # base/build code
    ano              = db.Column(db.Integer)
    # Flexible extra fields stored as JSON: [{"campo":"Diâmetro","valor":"50mm"}, ...]
    campos_extra     = db.Column(db.Text, default='[]')
    notas            = db.Column(db.Text)
    ordem            = db.Column(db.Integer, default=0)
    criado_em        = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em    = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
#  CONFIGURAÇÃO GERAL (tema, empresa, backup)
# ══════════════════════════════════════════════════════════════

class ConfigGeral(db.Model):
    """App-wide settings: theme, company info, backup."""
    __tablename__ = 'config_geral'
    id                    = db.Column(db.Integer, primary_key=True)
    # Company
    empresa_nome          = db.Column(db.String(200), default='ComprasNet')
    empresa_abrev         = db.Column(db.String(50),  default='CN')
    empresa_nif           = db.Column(db.String(20))
    empresa_morada        = db.Column(db.String(300))
    empresa_tel           = db.Column(db.String(50))
    empresa_email         = db.Column(db.String(150))
    empresa_logo_path     = db.Column(db.String(300))
    # Theme
    cor_accent            = db.Column(db.String(7),   default='#3b6ef0')
    cor_bg                = db.Column(db.String(7),   default='#0f1117')
    cor_surface           = db.Column(db.String(7),   default='#171b25')
    tema_nome             = db.Column(db.String(50),  default='dark')
    # Backup
    backup_local_path     = db.Column(db.String(500), default='backups')
    backup_rede_path      = db.Column(db.String(500))
    backup_hora           = db.Column(db.String(5),   default='02:00')
    backup_manter_dias    = db.Column(db.Integer,     default=30)
    backup_auto_ativo     = db.Column(db.Boolean,     default=True)
    ultimo_backup         = db.Column(db.DateTime)
    dashboard_layouts     = db.Column(db.Text, default='{}')
    logo_altura           = db.Column(db.Integer, default=48)
    logo_largura          = db.Column(db.Integer, default=180)
    # SMTP
    smtp_host             = db.Column(db.String(200))
    smtp_port             = db.Column(db.Integer, default=587)
    smtp_user             = db.Column(db.String(200))
    smtp_pass             = db.Column(db.String(200))
    smtp_from             = db.Column(db.String(200))
    smtp_tls              = db.Column(db.Integer, default=1)
    logo_filtro           = db.Column(db.String(100), default='')
    ultimo_backup_ok      = db.Column(db.Boolean)
    # Claude chat
    claude_chat_ativo     = db.Column(db.Boolean,     default=True)
    claude_chat_sistema   = db.Column(db.Text,        default='És um assistente técnico especializado em equipamentos navais e hidráulicos. Responde sempre em português.')
    salarios_pin          = db.Column(db.String(10),    default='')  # PIN to access salarios (legacy)
    salarios_senha        = db.Column(db.String(50))  # Password to access salarios


class NotaArtigo(db.Model):
    """Manual notes attached to a PHC article."""
    __tablename__ = 'notas_artigo'
    id          = db.Column(db.Integer, primary_key=True)
    artigo_ref  = db.Column(db.String(50), nullable=False, index=True)
    texto       = db.Column(db.Text, nullable=False)
    criado_por  = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em   = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow)


class EventoCalendario(db.Model):
    """Calendar events — purchases, deliveries, manual."""
    __tablename__ = 'eventos_calendario'
    id              = db.Column(db.Integer, primary_key=True)
    titulo          = db.Column(db.String(200), nullable=False)
    tipo            = db.Column(db.String(30), default='manual')
    # manual | compra | entrega_prevista | entrega_real | manutencao
    data_inicio     = db.Column(db.Date, nullable=False)
    data_fim        = db.Column(db.Date, nullable=True)
    hora            = db.Column(db.String(5), nullable=True)   # "HH:MM"
    descricao       = db.Column(db.Text)
    artigos_json    = db.Column(db.Text, default='[]')  # [{ref, design, qtt}]
    pedido_id       = db.Column(db.Integer, db.ForeignKey('pedidos_compra.id'), nullable=True)
    fornecedor      = db.Column(db.String(200))
    concluido       = db.Column(db.Boolean, default=False)
    criado_por      = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em   = db.Column(db.DateTime, default=datetime.utcnow)

class EntradaEquipamento(db.Model):
    __tablename__ = 'entradas_equipamento'
    id              = db.Column(db.Integer, primary_key=True)
    numero          = db.Column(db.Integer, nullable=False, unique=True)  # sequential ID
    data_rececao    = db.Column(db.Date, nullable=False)
    cliente_nome    = db.Column(db.String(200), nullable=False)
    marca           = db.Column(db.String(100))
    marca_grupo     = db.Column(db.String(100))
    modelo          = db.Column(db.String(100))
    modelo_grupo    = db.Column(db.String(100))
    num_serie       = db.Column(db.String(100))
    num_serie_grupo = db.Column(db.String(100))
    observacoes     = db.Column(db.Text, default='')
    status          = db.Column(db.String(50), default='rececionado')
    data_status     = db.Column(db.DateTime)          # when status was registered
    data_status_real = db.Column(db.Date, nullable=True)  # real date of current status
    data_orcamento        = db.Column(db.Date, nullable=True)  # real date of budget emission
    data_material_pedido  = db.Column(db.Date, nullable=True)  # when material was ordered
    data_pre_orcamento    = db.Column(db.Date, nullable=True)  # pre-budget
    data_material_stock   = db.Column(db.Date, nullable=True)  # material arrived in stock
    data_em_reparacao     = db.Column(db.Date, nullable=True)  # when repair started
    data_reparacao_concluida = db.Column(db.Date, nullable=True)  # repair completed
    data_faturado         = db.Column(db.Date, nullable=True)  # when invoiced
    data_fecho            = db.Column(db.Date, nullable=True)  # real closing date
    # Computed durations (days)
    dias_total            = db.Column(db.Integer, nullable=True)  # R→CF
    dias_rec_orcamento    = db.Column(db.Integer, nullable=True)  # R→ORC
    dias_rec_faturado     = db.Column(db.Integer, nullable=True)  # R→F
    dias_orc_reparacao    = db.Column(db.Integer, nullable=True)  # ORC→RP
    dias_mat_reparacao    = db.Column(db.Integer, nullable=True)  # CM→RP
    dias_mat_stock        = db.Column(db.Integer, nullable=True)  # CM→STOCK
    dias_stock_reparacao  = db.Column(db.Integer, nullable=True)  # STOCK→RP
    dias_reparacao_concluida = db.Column(db.Integer, nullable=True)  # RP→RC
    dias_reparacao_fat    = db.Column(db.Integer, nullable=True)  # RP→F
    criado_por      = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em   = db.Column(db.DateTime, default=datetime.utcnow)
    historico       = db.relationship('EntradaHistorico', backref='entrada',
                                      cascade='all, delete-orphan',
                                      order_by='EntradaHistorico.criado_em.desc()')

class EntradaHistorico(db.Model):
    __tablename__ = 'entrada_historico'
    id          = db.Column(db.Integer, primary_key=True)
    entrada_id  = db.Column(db.Integer, db.ForeignKey('entradas_equipamento.id'), nullable=False)
    status_ant  = db.Column(db.String(50))
    status_novo = db.Column(db.String(50), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'))
    user_nome   = db.Column(db.String(120))
    notas       = db.Column(db.String(400), default='')
    data_real   = db.Column(db.Date, nullable=True)  # real date of event (can differ from criado_em)
    criado_em   = db.Column(db.DateTime, default=datetime.utcnow)


class EntradaDocumento(db.Model):
    __tablename__ = 'entrada_documentos'
    id            = db.Column(db.Integer, primary_key=True)
    entrada_id    = db.Column(db.Integer, db.ForeignKey('entradas_equipamento.id'), nullable=False)
    nome_original = db.Column(db.String(255), nullable=False)
    nome_ficheiro = db.Column(db.String(255), nullable=False)
    descricao     = db.Column(db.String(300), default='')
    tamanho       = db.Column(db.Integer, default=0)
    mime          = db.Column(db.String(100), default='')
    criado_por    = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em     = db.Column(db.DateTime, default=datetime.utcnow)
    uploader      = db.relationship('User', foreign_keys=[criado_por])

# ── ASSISTÊNCIAS ─────────────────────────────────────────────────────────────

class Assistencia(db.Model):
    __tablename__ = 'assistencias'
    id              = db.Column(db.Integer, primary_key=True)
    numero          = db.Column(db.Integer, nullable=False, unique=True)
    # Requerente (fornecedor PHC ou texto livre)
    requerente_nome = db.Column(db.String(200), nullable=False)
    requerente_nif  = db.Column(db.String(30), default='')
    num_requisicao  = db.Column(db.String(100), default='')
    local_obra      = db.Column(db.String(300), default='')
    observacoes     = db.Column(db.Text, default='')
    # Status
    status          = db.Column(db.String(30), default='rececionado')
    # Real dates per status (set manually)
    data_rececionado   = db.Column(db.Date, nullable=True)
    data_em_execucao   = db.Column(db.Date, nullable=True)
    data_obra_concluida= db.Column(db.Date, nullable=True)
    data_comunicado    = db.Column(db.Date, nullable=True)
    data_faturado      = db.Column(db.Date, nullable=True)
    # Computed durations
    dias_recepcao_conclusao  = db.Column(db.Integer, nullable=True)
    dias_conclusao_comunicado = db.Column(db.Integer, nullable=True)  # obra→comunicado
    dias_conclusao_faturado   = db.Column(db.Integer, nullable=True)
    # Meta
    criado_por      = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em   = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationships
    historico       = db.relationship('AssistenciaHistorico', backref='assistencia',
                        cascade='all, delete-orphan',
                        order_by='AssistenciaHistorico.criado_em.desc()')
    documentos      = db.relationship('AssistenciaDocumento', backref='assistencia',
                        cascade='all, delete-orphan',
                        order_by='AssistenciaDocumento.criado_em.desc()')

class AssistenciaHistorico(db.Model):
    __tablename__ = 'assistencia_historico'
    id          = db.Column(db.Integer, primary_key=True)
    assist_id   = db.Column(db.Integer, db.ForeignKey('assistencias.id'), nullable=False)
    status_ant  = db.Column(db.String(30))
    status_novo = db.Column(db.String(30), nullable=False)
    data_real   = db.Column(db.Date, nullable=True)
    user_nome   = db.Column(db.String(120))
    notas       = db.Column(db.String(400), default='')
    criado_em   = db.Column(db.DateTime, default=datetime.utcnow)

class AssistenciaDocumento(db.Model):
    __tablename__ = 'assistencia_documentos'
    id            = db.Column(db.Integer, primary_key=True)
    assist_id     = db.Column(db.Integer, db.ForeignKey('assistencias.id'), nullable=False)
    tipo          = db.Column(db.String(20), default='documento')  # 'email' or 'documento'
    nome_original = db.Column(db.String(255), nullable=False)
    nome_ficheiro = db.Column(db.String(255), nullable=False)
    descricao     = db.Column(db.String(400), default='')
    tamanho       = db.Column(db.Integer, default=0)
    mime          = db.Column(db.String(100), default='')
    criado_por    = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em     = db.Column(db.DateTime, default=datetime.utcnow)
    uploader      = db.relationship('User', foreign_keys=[criado_por])

# ── FICHAS TÉCNICAS ────────────────────────────────────────────────────────────

class FichaTecnica(db.Model):
    __tablename__ = 'fichas_tecnicas'
    id              = db.Column(db.Integer, primary_key=True)
    numero          = db.Column(db.Integer, nullable=False, unique=True)
    # Grupo (gerador, embarcação, máquina, etc.)
    grupo_designacao= db.Column(db.String(200), nullable=False)
    grupo_marca     = db.Column(db.String(100), default='')
    grupo_modelo    = db.Column(db.String(100), default='')
    grupo_serie     = db.Column(db.String(100), default='')
    grupo_ano       = db.Column(db.String(10),  default='')
    # Motor / Equipamento principal
    motor_marca     = db.Column(db.String(100), default='')
    motor_modelo    = db.Column(db.String(100), default='')
    motor_serie     = db.Column(db.String(100), default='')
    motor_potencia  = db.Column(db.String(50),  default='')
    motor_cilindros = db.Column(db.String(20),  default='')
    # Info extra
    cliente_nome    = db.Column(db.String(200), default='')
    observacoes     = db.Column(db.Text, default='')
    # Meta
    criado_por      = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em   = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationships
    componentes     = db.relationship('FichaComponente', backref='ficha',
                        cascade='all, delete-orphan',
                        order_by='FichaComponente.categoria, FichaComponente.ordem')
    documentos      = db.relationship('FichaDocumento', backref='ficha',
                        cascade='all, delete-orphan',
                        order_by='FichaDocumento.criado_em.desc()')

class FichaComponente(db.Model):
    __tablename__ = 'ficha_componentes'
    id          = db.Column(db.Integer, primary_key=True)
    ficha_id    = db.Column(db.Integer, db.ForeignKey('fichas_tecnicas.id'), nullable=False)
    categoria   = db.Column(db.String(100), default='Geral')  # Filtros, Correias, Fluidos...
    ordem       = db.Column(db.Integer, default=0)
    designacao  = db.Column(db.String(200), nullable=False)
    part_number = db.Column(db.String(100), default='')
    marca       = db.Column(db.String(100), default='')
    referencia_equiv = db.Column(db.String(200), default='')  # equivalent refs
    quantidade  = db.Column(db.String(20),  default='1')
    unidade     = db.Column(db.String(20),  default='un')
    intervalo   = db.Column(db.String(100), default='')  # e.g. "10 000h / 1 ano"
    notas       = db.Column(db.String(400), default='')

class FichaDocumento(db.Model):
    __tablename__ = 'ficha_documentos'
    id            = db.Column(db.Integer, primary_key=True)
    ficha_id      = db.Column(db.Integer, db.ForeignKey('fichas_tecnicas.id'), nullable=False)
    tipo          = db.Column(db.String(20),  default='documento')  # documento / foto
    nome_original = db.Column(db.String(255), nullable=False)
    nome_ficheiro = db.Column(db.String(255), nullable=False)
    descricao     = db.Column(db.String(300), default='')
    tamanho       = db.Column(db.Integer,     default=0)
    mime          = db.Column(db.String(100), default='')
    criado_por    = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em     = db.Column(db.DateTime, default=datetime.utcnow)
    uploader      = db.relationship('User', foreign_keys=[criado_por])

# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO ASSIDUIDADE & PRÉ-PROCESSAMENTO SALARIAL
# ══════════════════════════════════════════════════════════════════════════════

class PeriodoSalarial(db.Model):
    """Período de processamento salarial por mês de referência."""
    __tablename__ = 'periodos_salariais'
    id            = db.Column(db.Integer, primary_key=True)
    ano           = db.Column(db.Integer, nullable=False, index=True)
    mes           = db.Column(db.Integer, nullable=False)          # 1-12 (mês de referência)
    data_inicio   = db.Column(db.Date, nullable=False)
    data_fim      = db.Column(db.Date, nullable=False)
    estado        = db.Column(db.String(10), default='aberto')     # aberto / fechado
    notas         = db.Column(db.Text, default='')
    criado_por    = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em     = db.Column(db.DateTime, default=datetime.utcnow)
    fechado_por   = db.Column(db.Integer, db.ForeignKey('users.id'))
    fechado_em    = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('ano', 'mes', name='uq_periodo_ano_mes'),)

class HoraExtra(db.Model):
    """Registo de horas extra por funcionário."""
    __tablename__ = 'horas_extra'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False, index=True)
    periodo_id      = db.Column(db.Integer, db.ForeignKey('periodos_salariais.id'))
    data            = db.Column(db.Date, nullable=False)
    hora_inicio     = db.Column(db.String(5), nullable=False)   # HH:MM
    hora_fim        = db.Column(db.String(5), nullable=False)
    total_horas     = db.Column(db.Float, default=0)
    categoria       = db.Column(db.String(20), default='dia_util')  # dia_util / fds / feriado
    estado          = db.Column(db.String(20), default='pendente')  # pendente / aprovado / rejeitado
    observacoes     = db.Column(db.Text, default='')
    criado_por      = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    alterado_por    = db.Column(db.Integer, db.ForeignKey('users.id'))
    alterado_em     = db.Column(db.DateTime)
    funcionario     = db.relationship('Funcionario', foreign_keys=[funcionario_id])
    periodo         = db.relationship('PeriodoSalarial', foreign_keys=[periodo_id])

class ConfigHorario(db.Model):
    """Configuração do horário laboral normal da empresa."""
    __tablename__ = 'config_horario'
    id          = db.Column(db.Integer, primary_key=True)
    hora_inicio = db.Column(db.String(5), default='08:30')
    hora_fim    = db.Column(db.String(5), default='17:30')
    horas_dia   = db.Column(db.Float, default=8.0)
    pausa_almoco = db.Column(db.Float, default=1.0)  # horas de pausa


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO FÉRIAS / FALTAS — AUSÊNCIAS
# ══════════════════════════════════════════════════════════════════════════════

# Tipos de ausência com cor e impacto
TIPOS_AUSENCIA = {
    'ferias':           {'label': 'Férias',                   'cor': '#22c55e',  'icon': '🏖',  'conta_ferias': True,  'conta_falta': False, 'desconta_salario': False},
    'ponte':            {'label': 'Ponte',                    'cor': '#3b6ef0',  'icon': '🌉',  'conta_ferias': True,  'conta_falta': False, 'desconta_salario': False},
    'fecho_empresa':    {'label': 'Fecho Empresa',            'cor': '#94a3b8',  'icon': '🏢',  'conta_ferias': True,  'conta_falta': False, 'desconta_salario': False},
    'falta_justificada':{'label': 'Falta Justificada',        'cor': '#f59e0b',  'icon': '📋',  'conta_ferias': False, 'conta_falta': True,  'desconta_salario': False},
    'falta_injustificada':{'label':'Falta Injustificada',     'cor': '#ef4444',  'icon': '🚫',  'conta_ferias': False, 'conta_falta': True,  'desconta_salario': True},
    'baixa_medica':     {'label': 'Baixa Médica',             'cor': '#a855f7',  'icon': '🏥',  'conta_ferias': False, 'conta_falta': False, 'desconta_salario': False},
    'consulta_medica':  {'label': 'Consulta Médica',          'cor': '#f97316',  'icon': '🩺',  'conta_ferias': False, 'conta_falta': False, 'desconta_salario': False},
    'assistencia_familia':{'label':'Assistência Família/Filho','cor': '#06b6d4', 'icon': '👨‍👩‍👧',  'conta_ferias': False, 'conta_falta': False, 'desconta_salario': False},
    'formacao':         {'label': 'Formação',                 'cor': '#8b5cf6',  'icon': '📚',  'conta_ferias': False, 'conta_falta': False, 'desconta_salario': False},
    'teletrabalho':     {'label': 'Teletrabalho',             'cor': '#0891b2',  'icon': '💻',  'conta_ferias': False, 'conta_falta': False, 'desconta_salario': False},
    'licenca_sem_venc': {'label': 'Licença sem Vencimento',   'cor': '#64748b',  'icon': '📄',  'conta_ferias': False, 'conta_falta': False, 'desconta_salario': True},
    'trabalho_externo': {'label': 'Trabalho Externo/Serviço', 'cor': '#10b981',  'icon': '🔧',  'conta_ferias': False, 'conta_falta': False, 'desconta_salario': False},
    'trabalho_ponte':   {'label': 'Trabalhou na Ponte',         'cor': '#06b6d4',  'icon': '💼',  'conta_ferias': False, 'conta_falta': False, 'desconta_salario': False},  # override bridge day
}

class AusenciaRegisto(db.Model):
    """Registo individual de ausência de um funcionário."""
    __tablename__ = 'ausencia_registos'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False, index=True)
    tipo            = db.Column(db.String(30), nullable=False)  # key of TIPOS_AUSENCIA
    data_inicio     = db.Column(db.Date, nullable=False)
    data_fim        = db.Column(db.Date, nullable=False)
    ano             = db.Column(db.Integer, nullable=False, index=True)
    # Formato: 'dia', 'manha', 'tarde', 'horas'
    formato         = db.Column(db.String(10), default='dia')
    horas           = db.Column(db.Float, default=0)  # only for formato='horas'
    # Dias úteis calculados
    dias_uteis      = db.Column(db.Float, default=0)
    # Aprovação
    estado          = db.Column(db.String(20), default='aprovado')  # pendente/aprovado/rejeitado/cancelado
    aprovado_por    = db.Column(db.Integer, db.ForeignKey('users.id'))
    aprovado_em     = db.Column(db.DateTime)
    # Info
    observacoes     = db.Column(db.Text, default='')
    tem_documento   = db.Column(db.Boolean, default=False)
    documento_path  = db.Column(db.String(300))
    # Auditoria
    criado_por      = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    alterado_por    = db.Column(db.Integer, db.ForeignKey('users.id'))
    alterado_em     = db.Column(db.DateTime)
    # Relationships
    funcionario     = db.relationship('Funcionario', foreign_keys=[funcionario_id])
    aprovador       = db.relationship('User', foreign_keys=[aprovado_por])
    criador         = db.relationship('User', foreign_keys=[criado_por])

class AusenciaSaldoAnual(db.Model):
    """Saldo anual de férias por funcionário."""
    __tablename__ = 'ausencia_saldos'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False)
    ano             = db.Column(db.Integer, nullable=False)
    dias_direito    = db.Column(db.Float, default=22)   # dias de férias a que tem direito
    dias_ajuste     = db.Column(db.Float, default=0)    # ajuste manual (transitados, acerto)
    notas_ajuste    = db.Column(db.String(300), default='')
    # calculados
    dias_gozados    = db.Column(db.Float, default=0)
    dias_restantes  = db.Column(db.Float, default=0)
    __table_args__  = (db.UniqueConstraint('funcionario_id', 'ano'),)
    funcionario     = db.relationship('Funcionario', foreign_keys=[funcionario_id])

class EmpresaFecho(db.Model):
    """Períodos de fecho geral da empresa (contam como férias para todos)."""
    __tablename__ = 'empresa_fechos'
    id          = db.Column(db.Integer, primary_key=True)
    ano         = db.Column(db.Integer, nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim    = db.Column(db.Date, nullable=False)
    descricao   = db.Column(db.String(200), default='')
    criado_por  = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em   = db.Column(db.DateTime, default=datetime.utcnow)

# ── MAPA DE FÉRIAS ─────────────────────────────────────────────────────────────

class FeriasPeriodo(db.Model):
    __tablename__ = 'ferias_periodos'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False)
    ano             = db.Column(db.Integer, nullable=False)
    data_inicio     = db.Column(db.Date, nullable=False)
    data_fim        = db.Column(db.Date, nullable=False)
    tipo            = db.Column(db.String(20), default='ferias')  # ferias / ponte
    notas           = db.Column(db.String(200), default='')
    cor             = db.Column(db.String(7), default='')  # hex color per employee
    criado_por      = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    funcionario     = db.relationship('Funcionario', foreign_keys=[funcionario_id])

class FeriasFeriado(db.Model):
    __tablename__ = 'ferias_feriados'
    id      = db.Column(db.Integer, primary_key=True)
    ano     = db.Column(db.Integer, nullable=False)
    data    = db.Column(db.Date, nullable=False, unique=True)
    nome    = db.Column(db.String(100), nullable=False)
    tipo    = db.Column(db.String(20), default='nacional')  # nacional / local / ponte

# ── STATUS UTILIZADORES ────────────────────────────────────────────────────────

class UserSession(db.Model):
    __tablename__ = 'user_sessions'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    last_seen   = db.Column(db.DateTime, default=datetime.utcnow)
    user        = db.relationship('User', foreign_keys=[user_id])

class EmpresaDocumento(db.Model):
    __tablename__ = 'empresa_documentos'
    id            = db.Column(db.Integer, primary_key=True)
    tipo          = db.Column(db.String(50), nullable=False)   # certidao, nao_divida_financas, nao_divida_ss, iban, outro
    titulo        = db.Column(db.String(200), nullable=False)
    numero_acesso = db.Column(db.String(100))   # certidão permanente access number
    notas         = db.Column(db.Text)
    pdf_path      = db.Column(db.String(300))
    data_emissao  = db.Column(db.Date)
    data_validade = db.Column(db.Date)   # NULL = sem prazo
    data_upload   = db.Column(db.DateTime, default=datetime.utcnow)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'))

class EmpresaInfo(db.Model):
    __tablename__ = 'empresa_info'
    id               = db.Column(db.Integer, primary_key=True)
    # Identificação
    nome_completo    = db.Column(db.String(200))
    nome_comercial   = db.Column(db.String(200))
    nif              = db.Column(db.String(20))
    nipc             = db.Column(db.String(20))
    cae              = db.Column(db.String(20))
    forma_juridica   = db.Column(db.String(100))
    # Contactos
    morada           = db.Column(db.String(300))
    codigo_postal    = db.Column(db.String(20))
    localidade       = db.Column(db.String(100))
    telefone         = db.Column(db.String(30))
    email            = db.Column(db.String(200))
    website          = db.Column(db.String(200))
    # Bancários
    banco            = db.Column(db.String(100))
    iban             = db.Column(db.String(30))
    swift            = db.Column(db.String(20))
    # Registos
    conservatoria    = db.Column(db.String(200))
    num_registo      = db.Column(db.String(50))
    capital_social   = db.Column(db.String(50))
    # Seguros
    seguradora       = db.Column(db.String(100))
    apolice          = db.Column(db.String(50))
    seguro_validade  = db.Column(db.Date)

# ══════════════════════════════════════════════════════════════════════
# EQUIPAMENTOS INDUSTRIAIS
# ══════════════════════════════════════════════════════════════════════
class EquipamentoIndustrial(db.Model):
    __tablename__ = 'equipamentos_industriais'
    id                  = db.Column(db.Integer, primary_key=True)
    cliente_id          = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    # Identificação
    nome                = db.Column(db.String(200), nullable=False)
    tipo                = db.Column(db.String(50))   # gerador, grupo_hidraulico, motor, outro
    referencia_interna  = db.Column(db.String(50))
    local_instalacao    = db.Column(db.String(200))
    data_instalacao     = db.Column(db.Date)
    data_fabricacao     = db.Column(db.Date)
    estado              = db.Column(db.String(30), default='ativo')  # ativo, inativo, abate
    notas               = db.Column(db.Text)
    foto_path           = db.Column(db.String(300))
    criado_em           = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationships
    cliente             = db.relationship('Cliente', backref='equipamentos_industriais')
    componentes         = db.relationship('EqIndComponente', backref='equipamento', lazy='dynamic', cascade='all, delete-orphan')
    documentos          = db.relationship('EqIndDocumento', backref='equipamento', lazy='dynamic', cascade='all, delete-orphan')

class EqIndComponente(db.Model):
    __tablename__ = 'eq_ind_componentes'
    id              = db.Column(db.Integer, primary_key=True)
    equipamento_id  = db.Column(db.Integer, db.ForeignKey('equipamentos_industriais.id'), nullable=False)
    tipo            = db.Column(db.String(30), nullable=False)  # motor, alternador, quadro, outro
    # Motor / Grupo
    marca_grupo         = db.Column(db.String(100))
    modelo_grupo        = db.Column(db.String(100))
    nserie_grupo        = db.Column(db.String(100))
    dados_grupo         = db.Column(db.Text)
    marca_motor         = db.Column(db.String(100))
    modelo_motor        = db.Column(db.String(100))
    nserie_motor        = db.Column(db.String(100))
    familia_motor       = db.Column(db.String(100))
    tipo_motor          = db.Column(db.String(100))
    potencia_motor_kw   = db.Column(db.Float)
    potencia_motor_cv   = db.Column(db.Float)
    rpm_motor           = db.Column(db.Integer)
    cilindros           = db.Column(db.Integer)
    combustivel         = db.Column(db.String(50))   # diesel, gas, gasolina
    instalacao_eletrica = db.Column(db.String(100))  # 230V, 400V, etc
    dados_motor         = db.Column(db.Text)
    # Alternador
    marca_alternador    = db.Column(db.String(100))
    nserie_alternador   = db.Column(db.String(100))
    potencia_kva        = db.Column(db.Float)
    potencia_kw_alt     = db.Column(db.Float)
    tensao_saida        = db.Column(db.String(50))   # 230V, 400V, 230/400V
    frequencia          = db.Column(db.Integer)      # 50Hz, 60Hz
    fator_potencia      = db.Column(db.String(20))   # 0.8, 1.0
    dados_alternador    = db.Column(db.Text)
    # Outros
    descricao           = db.Column(db.String(200))
    dados_outros        = db.Column(db.Text)
    criado_em           = db.Column(db.DateTime, default=datetime.utcnow)
    medias              = db.relationship("EqIndComponenteMedia", backref="componente", lazy="dynamic", cascade="all, delete-orphan")

class EqIndComponenteMedia(db.Model):
    __tablename__ = "eq_ind_comp_media"
    id              = db.Column(db.Integer, primary_key=True)
    componente_id   = db.Column(db.Integer, db.ForeignKey("eq_ind_componentes.id"), nullable=False)
    tipo            = db.Column(db.String(10))  # foto, pdf
    ficheiro_path   = db.Column(db.String(300))
    titulo          = db.Column(db.String(200))
    data_upload     = db.Column(db.DateTime, default=datetime.utcnow)

class EqIndDocumento(db.Model):
    __tablename__ = 'eq_ind_documentos'
    id              = db.Column(db.Integer, primary_key=True)
    equipamento_id  = db.Column(db.Integer, db.ForeignKey('equipamentos_industriais.id'), nullable=False)
    tipo            = db.Column(db.String(30))   # manual, ficha_tecnica, foto, certificado, outro
    titulo          = db.Column(db.String(200), nullable=False)
    ficheiro_path   = db.Column(db.String(300))
    notas           = db.Column(db.Text)
    data_upload     = db.Column(db.DateTime, default=datetime.utcnow)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'))
