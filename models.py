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
    num_serie        = db.Column(db.String(100))
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
