import os, json, threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import pdfplumber
from models import db, User, PedidoCompra, LinhaPedido, Orcamento, ItemOrcamento, ArtigoPHC, AliasArtigo, FornecedorPHC, ConfigPHC, ConfigIA, ConfigReposicao, PendingMatch, Cliente, Embarcacao, ComponenteEmbarcacao, ConfigGeral, NotaArtigo, EventoCalendario, EntradaEquipamento, EntradaHistorico, EntradaDocumento

app = Flask(__name__)
app.permanent_session_lifetime = __import__('datetime').timedelta(days=30)
app.config['SECRET_KEY'] = 'comprasnet-2024-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///compras.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['BAK_FOLDER'] = os.path.join(os.path.dirname(__file__), 'bak_uploads')
os.makedirs(app.config['BAK_FOLDER'], exist_ok=True)

db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor faça login para aceder.'

def user_pode_aceder(endpoint):
    """Check if current user can access the given menu endpoint."""
    if not current_user.is_authenticated:
        return False
    if current_user.is_admin:
        return True
    perfil_id = getattr(current_user, 'perfil_id', None)
    if not perfil_id:
        return True  # no perfil = full access (backwards compat)
    perfil = Perfil.query.get(perfil_id)
    if not perfil:
        return True
    return perfil.pode_aceder(endpoint)


@app.context_processor
def inject_perfil():
    def pode_aceder(endpoint):
        from flask_login import current_user
        if not current_user.is_authenticated: return False
        if current_user.is_admin: return True
        pid = get_user_perfil_id(current_user)
        if not pid: return True
        p = Perfil.query.get(pid)
        if not p: return True
        return p.pode_aceder(endpoint)
    return dict(pode_aceder=pode_aceder)

@app.before_request
def refresh_session():
    """Keep session alive on every request."""
    from flask_login import current_user
    if current_user.is_authenticated:
        session.permanent = True
        session.modified = True


@login_manager.unauthorized_handler
def handle_unauthorized():
    """Return JSON for API calls, redirect for normal pages."""
    if (request.is_json or 
        request.path.startswith('/api/') or
        request.method == 'POST'):
        return jsonify({'error': 'Sessão expirada. Recarregue a página e faça login.'}), 401
    from flask import redirect, url_for
    return redirect(url_for('login'))


@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

def allowed_file(f): return '.' in f and f.rsplit('.',1)[1].lower() == 'pdf'

# ── PDF helpers ────────────────────────────────────────────────────────────────

def extract_pdf_text(filepath):
    text = ""
    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text += t + "\n"
                for table in page.extract_tables():
                    for row in table:
                        if row: text += " | ".join([str(c) if c else "" for c in row]) + "\n"
    except Exception as e:
        text = f"Erro: {e}"
    return text

def analyze_pdf_with_claude(pdf_text, filename):
    """Wrapper: delegates to ai_provider using current ConfigIA from DB."""
    from ai_provider import analyze_pdf
    cfg = ConfigIA.query.first()
    if not cfg:
        # Auto-create default LM Studio config
        cfg = ConfigIA(); db.session.add(cfg); db.session.commit()
    return analyze_pdf(cfg, pdf_text, filename)

# ── AUTH ───────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username','')).first()
        if u and check_password_hash(u.password_hash, request.form.get('password','')):
            login_user(u, remember=True)
            if getattr(u, 'must_change_password', False):
                return redirect(url_for('alterar_password'))
            return redirect(url_for('dashboard'))
        flash('Utilizador ou palavra-passe incorretos.', 'error')
    return render_template('login.html', cfg=ConfigGeral.query.first())

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('login'))

# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    total_pedidos    = PedidoCompra.query.count()
    pedidos_abertos  = PedidoCompra.query.filter_by(estado='aberto').count()
    pedidos_aprovados= PedidoCompra.query.filter_by(estado='aprovado').count()
    total_orcamentos = Orcamento.query.count()
    pedidos_recentes = PedidoCompra.query.filter(PedidoCompra.estado.in_(['aberto','aprovado','pendente'])).order_by(PedidoCompra.data_criacao.desc()).limit(8).all()

    # Artigos pedidos para dashboard - pendentes/não encomendados primeiro, recebidos no fim
    from sqlalchemy import case
    artigos_pedidos = (db.session.query(LinhaPedido, PedidoCompra, User)
        .join(PedidoCompra, LinhaPedido.pedido_id == PedidoCompra.id)
        .join(User, PedidoCompra.criado_por == User.id, isouter=True)
        .filter(PedidoCompra.estado.in_(['aberto','aprovado','pendente']))
        .order_by(
            case(
                (LinhaPedido.status == 'recebido', 2),
                (LinhaPedido.status == 'cancelado', 3),
                else_=0
            ),
            PedidoCompra.data_criacao.desc()
        )
        .all()
    )
    # Stock baixo: stock > 0 mas abaixo de threshold (excluir negativos)
    artigos_stock_baixo = ArtigoPHC.query.filter(
        ArtigoPHC.stock_atual > 0,
        ArtigoPHC.stock_atual <= 3
    ).order_by(ArtigoPHC.stock_atual).limit(10).all()
    # Check entradas in estadia
    try:
        _verificar_estadias()
        entradas_estadia_list = EntradaEquipamento.query.filter(
            EntradaEquipamento.status.in_(['orcamentado_estadia','concluido_estadia'])
        ).order_by(EntradaEquipamento.data_status).all()
        entradas_estadia = len(entradas_estadia_list)
    except: entradas_estadia = 0; entradas_estadia_list = []
    return render_template('dashboard.html',
        entradas_estadia=entradas_estadia,
        entradas_estadia_list=entradas_estadia_list,
        total_pedidos=total_pedidos,
        pedidos_abertos=pedidos_abertos,
        pedidos_aprovados=pedidos_aprovados,
        total_orcamentos=total_orcamentos,
        pedidos_recentes=pedidos_recentes,
        artigos_stock_baixo=artigos_stock_baixo,
        artigos_pedidos=artigos_pedidos,
    )


@app.route('/api/dashboard/artigos-pedidos')
@login_required
def api_dashboard_artigos_pedidos():
    from sqlalchemy import case as sa_case
    artigos = (db.session.query(LinhaPedido, PedidoCompra, User)
        .join(PedidoCompra, LinhaPedido.pedido_id == PedidoCompra.id)
        .join(User, PedidoCompra.criado_por == User.id, isouter=True)
        .filter(PedidoCompra.estado.in_(["aberto","aprovado","pendente"]))
        .order_by(
            sa_case(
                (LinhaPedido.status == "recebido", 2),
                (LinhaPedido.status == "cancelado", 3),
                else_=0
            ),
            PedidoCompra.data_criacao.desc()
        ).all()
    )
    STATUS_INFO = {
        "nao_encomendado": ("🔴 Não Enc.",  "#ef4444", "rgba(239,68,68,.15)"),
        "pendente":         ("⏳ Pendente",  "#f59e0b", "rgba(245,158,11,.15)"),
        "recebido":         ("✅ Recebido",  "#22c55e", "rgba(34,197,94,.15)"),
        "cancelado":        ("❌ Cancelado", "#a855f7", "rgba(168,85,247,.15)"),
    }
    rows = []
    for linha, pedido, user in artigos:
        s = linha.status or "nao_encomendado"
        lbl, col, bg = STATUS_INFO.get(s, STATUS_INFO["nao_encomendado"])
        # Get last status change
        hist = LinhaPedidoHistorico.query.filter_by(linha_id=linha.id)            .order_by(LinhaPedidoHistorico.data.desc()).first()
        rows.append({
            "linha_id": linha.id,
            "pedido_id": pedido.id,
            "designacao": linha.designacao or linha.referencia or "—",
            "referencia": linha.referencia or "",
            "quantidade": int(linha.quantidade or 1),
            "unidade": linha.unidade or "un",
            "data_pedido": pedido.data_criacao.strftime("%d/%m/%Y"),
            "criado_por": user.nome[:20] if user else "—",
            "status": s,
            "status_label": lbl,
            "status_color": col,
            "status_bg": bg,
            "dim": s in ["recebido","cancelado"],
            "data_status": hist.data.strftime("%d/%m/%Y %H:%M") if hist else "—",
            "alterado_por": hist.user_nome[:20] if hist else "—",
        })
    return jsonify(rows)


@app.route('/pedidos')
@login_required
def pedidos():
    estado = request.args.get('estado','aberto')
    q = PedidoCompra.query
    if estado and estado != 'todos': q = q.filter_by(estado=estado)
    return render_template('pedidos.html', pedidos=q.order_by(PedidoCompra.data_criacao.desc()).all(), estado_filtro=estado)

@app.route('/pedidos/novo', methods=['GET','POST'])
@login_required
def novo_pedido():
    if request.method == 'POST':
        titulo = request.form.get('titulo','').strip()
        if not titulo:
            flash('O artigo a comprar é obrigatório.','error')
            clientes_list = Cliente.query.order_by(Cliente.nome).all()
            return render_template('novo_pedido.html', clientes=clientes_list)
        cliente_id = request.form.get('cliente_id','').strip()
        p = PedidoCompra(titulo=titulo,
            descricao=request.form.get('descricao','').strip(),
            prioridade=request.form.get('prioridade','normal'),
            departamento=request.form.get('departamento','Compras').strip(),
            cliente_id=int(cliente_id) if cliente_id else None,
            estado='aberto', criado_por=current_user.id,
            data_criacao=datetime.now())
        db.session.add(p); db.session.flush()

        # Save lines from form
        import json as _json
        linhas_json = request.form.get('linhas_json','[]')
        try:
            linhas = _json.loads(linhas_json)
        except: linhas = []
        for i, l in enumerate(linhas):
            ref = l.get('referencia','').strip()
            artigo = ArtigoPHC.query.filter_by(referencia=ref).first() if ref else None
            db.session.add(LinhaPedido(
                pedido_id=p.id, ordem=i,
                artigo_ref=ref if artigo else None,
                referencia=ref or l.get('designacao','')[:50],
                designacao=l.get('designacao','').strip(),
                unidade=l.get('unidade','un'),
                quantidade=float(l.get('quantidade',1)),
                stock_atual=float(artigo.stock_atual if artigo else 0),
                preco_custo_ref=float(artigo.preco_custo if artigo else 0),
                preco_pcp_ref=float(artigo.preco_custo_ponderado if artigo else 0),
                observacoes=l.get('observacoes','').strip(),
                cliente_id=int(l.get('cliente_id')) if l.get('cliente_id') else None
            ))
        db.session.commit()
        flash('Pedido criado!','success')
        return redirect(url_for('pedido_detalhe', pid=p.id))
    clientes_list = Cliente.query.order_by(Cliente.nome).all()
    return render_template('novo_pedido.html', clientes=clientes_list)

def _get_fornecedores_artigo(artigo_ref):
    """Get habitual suppliers for an article from PHC data."""
    if not artigo_ref:
        return []
    try:
        cfg = ConfigPHC.query.first()
        if not cfg or not cfg.server:
            return []
        import pyodbc
        conn_str = (f"DRIVER={{SQL Server}};SERVER={cfg.server};DATABASE={cfg.database};"
                    f"UID={cfg.username};PWD={cfg.password}")
        conn = pyodbc.connect(conn_str, timeout=3)
        cur = conn.cursor()
        # Query PHC for suppliers of this article
        cur.execute("""
            SELECT DISTINCT f.nome, f.ncont, sl.epv
            FROM sl WITH(NOLOCK)
            JOIN fornecedor f WITH(NOLOCK) ON sl.no = f.no
            WHERE sl.ref = ? AND sl.ativo = 1
            ORDER BY sl.epv DESC
        """, artigo_ref)
        rows = cur.fetchall()
        conn.close()
        return [{'nome': r[0], 'nif': r[1] or '', 'preco': float(r[2] or 0)} for r in rows[:5]]
    except Exception as ex:
        return []


@app.route('/pedidos/<int:pid>')
@login_required
def pedido_detalhe(pid):
    p = PedidoCompra.query.get_or_404(pid)
    orcs = Orcamento.query.filter_by(pedido_id=pid).order_by(Orcamento.total).all()
    # Get fornecedores habituais from PHC for each line
    from models import FornecedorPHC
    linhas_json = json.dumps([{
        'id': l.id, 'referencia': l.referencia or '', 'designacao': l.designacao or '',
        'unidade': l.unidade or 'un', 'quantidade': l.quantidade,
        'stock_atual': l.stock_atual, 'preco_custo_ref': l.preco_custo_ref,
        'preco_pcp_ref': l.preco_pcp_ref, 'fornecedor_hab': l.fornecedor_hab or '',
        'observacoes': l.observacoes or '', 'artigo_ref': l.artigo_ref or '',
        'status': l.status or 'nao_encomendado',
        'cliente_id': l.cliente_id or '',
        'fornecedores_phc': _get_fornecedores_artigo(l.artigo_ref),
    } for l in p.linhas])
    return render_template('pedido_detalhe.html', pedido=p, orcamentos=orcs,
                           melhor=orcs[0] if orcs else None, linhas_json=linhas_json)

@app.route('/pedidos/<int:pid>/linha/<int:lid>/status', methods=['POST'])
@login_required
def linha_status(pid, lid):
    l = LinhaPedido.query.filter_by(id=lid, pedido_id=pid).first_or_404()
    data = request.json or {}
    novo_status = data.get('status', 'nao_encomendado')
    notas = data.get('notas', '')
    status_ant = l.status or 'nao_encomendado'
    if novo_status != status_ant:
        hist = LinhaPedidoHistorico(
            linha_id=lid, pedido_id=pid,
            status_ant=status_ant, status_novo=novo_status,
            user_id=current_user.id, user_nome=current_user.nome,
            notas=notas, data=datetime.now()
        )
        db.session.add(hist)
        l.status = novo_status
        db.session.commit()
    return jsonify({'ok': True, 'status': l.status})

@app.route('/pedidos/<int:pid>/linha/<int:lid>/historico')
@login_required
def linha_historico(pid, lid):
    hist = LinhaPedidoHistorico.query.filter_by(linha_id=lid).order_by(
        LinhaPedidoHistorico.data.desc()).all()
    return jsonify([{
        'status_ant': h.status_ant, 'status_novo': h.status_novo,
        'user_nome': h.user_nome, 'notas': h.notas or '',
        'data': h.data.strftime('%d/%m/%Y %H:%M')
    } for h in hist])


# ── LINHAS DO PEDIDO ──────────────────────────────────────────────────────────

@app.route('/pedidos/<int:pid>/linhas', methods=['POST'])
@login_required
def salvar_linhas(pid):
    """Save/replace all lines of a purchase order (JSON body)."""
    p = PedidoCompra.query.get_or_404(pid)
    if p.estado in ['aprovado','cancelado']:
        return jsonify({'error':'Pedido fechado.'}), 400
    data = request.get_json()
    if not data or 'linhas' not in data:
        return jsonify({'error':'Dados inválidos.'}), 400

    LinhaPedido.query.filter_by(pedido_id=pid).delete()
    for i, l in enumerate(data['linhas']):
        ref = l.get('referencia','').strip()
        artigo = ArtigoPHC.query.filter_by(referencia=ref).first() if ref else None
        linha = LinhaPedido(
            pedido_id=pid, ordem=i,
            artigo_ref      = ref if artigo else None,
            referencia      = ref or l.get('designacao','')[:50],
            designacao      = l.get('designacao','').strip(),
            unidade         = l.get('unidade','un'),
            quantidade      = float(l.get('quantidade',1)),
            stock_atual     = float(artigo.stock_atual if artigo else 0),
            preco_custo_ref = float(artigo.preco_custo if artigo else 0),
            preco_pcp_ref   = float(artigo.preco_custo_ponderado if artigo else 0),
            fornecedor_hab  = l.get('fornecedor_hab','').strip(),
            observacoes     = l.get('observacoes','').strip(),
            cliente_id      = int(l.get('cliente_id')) if l.get('cliente_id') else None
        )
        db.session.add(linha)
    db.session.commit()
    return jsonify({'ok': True, 'total_linhas': len(data['linhas'])})

@app.route('/pedidos/<int:pid>/linhas/<int:lid>', methods=['DELETE'])
@login_required
def apagar_linha(pid, lid):
    l = LinhaPedido.query.filter_by(id=lid, pedido_id=pid).first_or_404()
    db.session.delete(l); db.session.commit()
    return jsonify({'ok': True})

# ── ARTIGOS PHC API ───────────────────────────────────────────────────────────

@app.route('/api/artigos')
@login_required
def api_artigos():
    """Search PHC articles — used by the live search in pedido form."""
    q = request.args.get('q','').strip()
    if len(q) < 2:
        return jsonify([])
    like = f"%{q}%"
    rows = (ArtigoPHC.query
            .filter(db.or_(
                ArtigoPHC.referencia.ilike(like),
                ArtigoPHC.designacao.ilike(like),
                ArtigoPHC.familia.ilike(like)))
            .order_by(ArtigoPHC.referencia)
            .limit(30).all())
    return jsonify([{
        'referencia':   a.referencia,
        'designacao':   a.designacao,
        'stock_atual':  a.stock_atual,
        'unidade':      a.unidade,
        'preco_custo':  a.preco_custo,
        'pcp':          a.preco_custo_ponderado,
        'familia':      a.familia,
    } for a in rows])

@app.route('/api/artigos/<ref>')
@login_required
def api_artigo_detalhe(ref):
    a = ArtigoPHC.query.filter_by(referencia=ref).first()
    if not a: return jsonify({'error':'Não encontrado'}), 404
    # Try to get purchase history if PHC is configured
    historico = []
    try:
        cfg = ConfigPHC.query.first()
        if cfg and cfg.ultima_sync:
            from phc_sync import get_historico_compras
            historico = get_historico_compras(cfg, ref)
    except Exception:
        pass
    # Get known suppliers for this article from purchase history + FornecedorPHC
    fornecedores = []
    seen = set()
    for h in historico:
        nome = h.get('fornecedor_nome', '')
        if nome and nome not in seen:
            seen.add(nome)
            # Try to find email in local FornecedorPHC cache
            forn_db = FornecedorPHC.query.filter(
                FornecedorPHC.nome.ilike(f'%{nome}%')
            ).first()
            fornecedores.append({
                'nome':   nome,
                'no':     h.get('fornecedor_no'),
                'email':  forn_db.email if forn_db else '',
                'tel':    forn_db.telefone if forn_db else '',
                'ultimo_preco': h.get('preco', 0),
                'ultima_compra': h.get('data_compra', ''),
            })

    return jsonify({
        'referencia':  a.referencia,
        'designacao':  a.designacao,
        'stock_atual': a.stock_atual,
        'unidade':     a.unidade,
        'preco_custo': a.preco_custo,
        'pcp':         a.preco_custo_ponderado,
        'familia':     a.familia,
        'taxa_iva':    a.taxa_iva,
        'historico':   historico,
        'fornecedores': fornecedores,
    })

# ── ORÇAMENTOS ────────────────────────────────────────────────────────────────

@app.route('/pedidos/<int:pid>/upload', methods=['POST'])
@login_required
def upload_orcamento(pid):
    p = PedidoCompra.query.get_or_404(pid)
    if p.estado not in ['aberto','em_analise']:
        return jsonify({'error':'Pedido não permite orçamentos neste estado.'}), 400
    if Orcamento.query.filter_by(pedido_id=pid).count() >= 3:
        return jsonify({'error':'Já existem 3 orçamentos neste pedido.'}), 400
    if 'pdf' not in request.files:
        return jsonify({'error':'Nenhum ficheiro.'}), 400
    file = request.files['pdf']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({'error':'Apenas PDFs são aceites.'}), 400

    fname = secure_filename(f"pc{pid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
    fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
    file.save(fpath)

    dados, erro = analyze_pdf_with_claude(extract_pdf_text(fpath), file.filename)
    forn_manual = request.form.get('fornecedor','').strip()
    if not dados:
        dados = {'empresa': forn_manual or 'Fornecedor Desconhecido',
                 'total':0,'subtotal':0,'desconto_total':0,'desconto_percentagem':0,
                 'iva_valor':0,'numero_orcamento':None,'data_orcamento':None,
                 'validade':None,'contacto':None,'nif':None,'observacoes':erro,'items':[]}
    if forn_manual: dados['empresa'] = forn_manual

    orc = Orcamento(
        pedido_id=pid,
        empresa=dados.get('empresa','Desconhecido'),
        nif=dados.get('nif'),
        numero_orcamento=dados.get('numero_orcamento'),
        data_orcamento=datetime.strptime(dados['data_orcamento'],'%Y-%m-%d').date() if dados.get('data_orcamento') else None,
        validade=datetime.strptime(dados['validade'],'%Y-%m-%d').date() if dados.get('validade') else None,
        subtotal=float(dados.get('subtotal') or 0),
        desconto_total=float(dados.get('desconto_total') or 0),
        desconto_percentagem=float(dados.get('desconto_percentagem') or 0),
        iva_valor=float(dados.get('iva_valor') or 0),
        total=float(dados.get('total') or 0),
        moeda=dados.get('moeda','EUR'),
        contacto=dados.get('contacto'),
        observacoes=dados.get('observacoes'),
        ficheiro_pdf=fname,
        carregado_por=current_user.id,
        data_upload=datetime.now(),
        dados_brutos=json.dumps(dados))
    db.session.add(orc); db.session.flush()

    for item in dados.get('items',[]):
        db.session.add(ItemOrcamento(
            orcamento_id=orc.id,
            descricao=item.get('descricao',''),
            referencia=item.get('referencia'),
            quantidade=float(item.get('quantidade') or 1),
            unidade=item.get('unidade','un'),
            preco_unitario=float(item.get('preco_unitario') or 0),
            desconto_item=float(item.get('desconto_item') or 0),
            total_item=float(item.get('total_item') or 0)))

    if p.estado == 'aberto': p.estado = 'em_analise'
    db.session.commit()
    return jsonify({'success':True,'orcamento_id':orc.id,'empresa':orc.empresa,
                    'total':orc.total,'num_items':len(dados.get('items',[]))})


# ── ALIAS MATCHING ────────────────────────────────────────────────────────────

@app.route('/pedidos/<int:pid>/match', methods=['POST'])
@login_required
def match_orcamento(pid):
    """Run alias matching on all orcamentos of a pedido."""
    p = PedidoCompra.query.get_or_404(pid)
    aliases = AliasArtigo.query.all()
    results = []
    for orc in p.orcamentos:
        from alias_matcher import match_orcamento_items
        r = match_orcamento_items(orc, p, aliases)
        results.extend(r)
    db.session.commit()
    return jsonify({'ok': True, 'matches': len([r for r in results if r['artigo_ref']]),'total': len(results)})


@app.route('/api/alias', methods=['POST'])
@login_required
def criar_alias():
    """Manually link a supplier description to a PHC article."""
    data = request.get_json()
    artigo_ref     = data.get('artigo_ref', '').strip()
    descricao_orig = data.get('descricao_orig', '').strip()
    fornecedor     = data.get('fornecedor', '').strip()
    referencia_forn= data.get('referencia_forn', '').strip()
    item_id        = data.get('item_id')

    if not artigo_ref or not descricao_orig:
        return jsonify({'error': 'artigo_ref e descricao_orig são obrigatórios'}), 400

    artigo = ArtigoPHC.query.filter_by(referencia=artigo_ref).first()
    if not artigo:
        return jsonify({'error': f'Artigo {artigo_ref} não encontrado'}), 404

    from alias_matcher import save_alias
    save_alias(db, artigo_ref, descricao_orig, fornecedor,
               referencia_forn, current_user.id, confianca=1.0)

    # Update the item if provided
    if item_id:
        item = ItemOrcamento.query.get(item_id)
        if item:
            item.artigo_ref_match = artigo_ref
            item.match_confianca  = 1.0
            db.session.commit()

    return jsonify({'ok': True, 'artigo_ref': artigo_ref, 'designacao': artigo.designacao})


@app.route('/api/alias/<int:alias_id>', methods=['DELETE'])
@login_required
def apagar_alias(alias_id):
    alias = AliasArtigo.query.get_or_404(alias_id)
    db.session.delete(alias)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/aliases')
@login_required
def listar_aliases():
    """List all aliases, optionally filtered by artigo_ref."""
    ref = request.args.get('ref', '').strip()
    q = AliasArtigo.query
    if ref:
        q = q.filter_by(artigo_ref=ref)
    aliases = q.order_by(AliasArtigo.vezes_usado.desc()).all()
    return jsonify([{
        'id':             a.id,
        'artigo_ref':     a.artigo_ref,
        'fornecedor':     a.fornecedor,
        'descricao_orig': a.descricao_orig,
        'referencia_forn':a.referencia_forn,
        'confianca':      a.confianca,
        'vezes_usado':    a.vezes_usado,
        'data_criacao':   a.data_criacao.strftime('%d/%m/%Y') if a.data_criacao else '',
    } for a in aliases])


@app.route('/pedidos/<int:pid>/comparacao')
@login_required
def comparacao_pedido(pid):
    """Comparison matrix page: pedido lines vs orcamento items."""
    p    = PedidoCompra.query.get_or_404(pid)
    orcs = Orcamento.query.filter_by(pedido_id=pid).all()
    from alias_matcher import build_comparison_matrix
    matrix = build_comparison_matrix(p, orcs)
    return render_template('comparacao.html', pedido=p, orcamentos=orcs, matrix=matrix)


# ── PDF PREVIEW ───────────────────────────────────────────────────────────────

@app.route('/uploads/preview/<filename>')
@login_required
def preview_pdf(filename):
    """Serve PDF for inline preview."""
    return send_from_directory(
        app.config['UPLOAD_FOLDER'], filename,
        mimetype='application/pdf',
        as_attachment=False
    )

@app.route('/pedidos/<int:pid>/aprovar', methods=['POST'])
@login_required
def aprovar_pedido(pid):
    p = PedidoCompra.query.get_or_404(pid)
    oid = request.form.get('orcamento_id')
    if oid:
        for o in p.orcamentos: o.selecionado = False
        o2 = Orcamento.query.get(oid)
        if o2: o2.selecionado = True
    p.estado = 'aprovado'; p.aprovado_por = current_user.id; p.data_aprovacao = datetime.now()
    db.session.commit(); flash('Pedido aprovado!','success')
    return redirect(url_for('pedido_detalhe', pid=pid))

@app.route('/pedidos/<int:pid>/cancelar', methods=['POST'])
@login_required
def cancelar_pedido(pid):
    p = PedidoCompra.query.get_or_404(pid)
    p.estado = 'cancelado'; db.session.commit(); flash('Pedido cancelado.','info')
    return redirect(url_for('pedido_detalhe', pid=pid))

@app.route('/orcamentos/<int:oid>')
@login_required
def orcamento_detalhe(oid):
    return render_template('orcamento_detalhe.html', orc=Orcamento.query.get_or_404(oid))

@app.route('/orcamentos/<int:oid>/apagar', methods=['POST'])
@login_required
def apagar_orcamento(oid):
    orc = Orcamento.query.get_or_404(oid); pid = orc.pedido_id
    fp = os.path.join(app.config['UPLOAD_FOLDER'], orc.ficheiro_pdf)
    if os.path.exists(fp): os.remove(fp)
    ItemOrcamento.query.filter_by(orcamento_id=oid).delete()
    db.session.delete(orc); db.session.commit()
    flash('Orçamento removido.','info')
    return redirect(url_for('pedido_detalhe', pid=pid))

@app.route('/uploads/<filename>')
def download_pdf(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)



# ── REPOSIÇÃO ─────────────────────────────────────────────────────────────────

@app.route('/reposicao')
@login_required
def reposicao():
    from reposicao import CONFIG_PADRAO, analisar_todos
    cfg_phc    = ConfigPHC.query.first()
    cfg_global = ConfigReposicao.query.filter_by(artigo_ref=None).first()
    if not cfg_global:
        cfg_global = ConfigReposicao()
        db.session.add(cfg_global)
        db.session.commit()

    # Build config dict
    config = dict(CONFIG_PADRAO)
    if cfg_global:
        config.update({
            'meses_historico':             cfg_global.meses_historico or 60,
            'lead_time_dias':              cfg_global.lead_time_dias or 7,
            'fator_seguranca':             cfg_global.fator_seguranca or 1.5,
            'meses_cobertura':             cfg_global.meses_cobertura or 2,
            'custo_encomenda':             cfg_global.custo_encomenda or 25,
            'taxa_posse_anual':            cfg_global.taxa_posse_anual or 0.20,
            'quantidade_minima_encomenda': cfg_global.quantidade_minima_encomenda or 1,
            'alertar_dias_cobertura':      cfg_global.alertar_dias_cobertura or 30,
            'min_anos_historico':          getattr(cfg_global, 'min_anos_historico', 2) or 2,
            'min_meses_com_venda':         getattr(cfg_global, 'min_meses_com_venda', 3) or 3,
            'min_total_vendido':           getattr(cfg_global, 'min_total_vendido', 3) or 3,
            'ignorar_sem_movimento_anos':  getattr(cfg_global, 'ignorar_sem_movimento_anos', 3) or 3,
            'min_facturas_sugerir':        getattr(cfg_global, 'min_facturas_sugerir', 8) or 8,
            'min_facturas_sugerir':        getattr(cfg_global, 'min_facturas_sugerir', 5) or 5,
        })

    # Run analysis only if requested
    analise = request.args.get('analise') == '1'
    resultados = []
    erro = None
    if analise:
        try:
            artigos = ArtigoPHC.query.filter(ArtigoPHC.stock_atual >= 0).all()
            resultados = analisar_todos(cfg_phc, config, artigos)
        except Exception as e:
            import traceback
            erro = str(e)
            logger.error(traceback.format_exc())

    total_artigos    = ArtigoPHC.query.count()
    precisam         = [r for r in resultados if r.get('precisa_encomendar')]
    criticos         = [r for r in resultados if r.get('urgencia') == 'critico']
    sem_dados        = [r for r in resultados if not r.get('tem_dados')]

    return render_template('reposicao.html',
        cfg=cfg_global,
        config_padrao=config,
        total_artigos=total_artigos,
        resultados=resultados,
        analise_feita=analise,
        precisam=precisam,
        criticos=criticos,
        sem_dados=sem_dados,
        erro=erro,
    )


@app.route('/reposicao/config', methods=['POST'])
@login_required
def salvar_config_reposicao():
    """Save global or per-article replenishment config."""
    artigo_ref = request.form.get('artigo_ref', '').strip() or None
    cfg = ConfigReposicao.query.filter_by(artigo_ref=artigo_ref).first()
    if not cfg:
        cfg = ConfigReposicao(artigo_ref=artigo_ref)
        db.session.add(cfg)

    cfg.meses_historico             = int(request.form.get('meses_historico', 24))
    cfg.lead_time_dias              = float(request.form.get('lead_time_dias', 7))
    cfg.fator_seguranca             = float(request.form.get('fator_seguranca', 1.5))
    cfg.meses_cobertura             = int(request.form.get('meses_cobertura', 2))
    cfg.custo_encomenda             = float(request.form.get('custo_encomenda', 25))
    taxa_raw = float(request.form.get('taxa_posse_anual', 20))
    # Accept both 0.20 and 20 (percent) - if > 1, treat as percentage
    cfg.taxa_posse_anual = taxa_raw / 100 if taxa_raw > 1 else taxa_raw
    cfg.quantidade_minima_encomenda = float(request.form.get('quantidade_minima_encomenda', 1))
    cfg.alertar_dias_cobertura      = int(request.form.get('alertar_dias_cobertura', 30))
    cfg.ignorar_parados_dias        = int(request.form.get('ignorar_parados_dias', 365))
    cfg.min_anos_historico          = float(request.form.get('min_anos_historico', 2) or 2)
    cfg.min_meses_com_venda         = int(request.form.get('min_meses_com_venda', 3) or 3)
    cfg.min_total_vendido           = float(request.form.get('min_total_vendido', 3) or 3)
    cfg.ignorar_sem_movimento_anos  = float(request.form.get('ignorar_sem_movimento_anos', 3) or 3)
    cfg.min_facturas_sugerir        = int(request.form.get('min_facturas_sugerir', 8) or 8)
    cfg.min_facturas_sugerir        = int(request.form.get('min_facturas_sugerir', 5) or 5)
    cfg.atualizado_em               = datetime.now()
    cfg.atualizado_por              = current_user.id
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True})
    flash('Configuração de reposição guardada.', 'success')
    # If requested, redirect to analysis
    if request.args.get('redirect_analise') == '1':
        return redirect(url_for('reposicao') + '?analise=1')
    return redirect(url_for('reposicao'))


@app.route('/reposicao/analisar/<ref>')
@login_required
def analisar_artigo(ref):
    """Analyse one article and show detailed breakdown page."""
    from reposicao import CONFIG_PADRAO, calcular_metricas, SQL_VENDAS_ARTIGO

    cfg_phc    = ConfigPHC.query.first()
    cfg_global = ConfigReposicao.query.filter_by(artigo_ref=None).first()
    artigo     = ArtigoPHC.query.filter_by(referencia=ref).first_or_404()

    config = dict(CONFIG_PADRAO)
    if cfg_global:
        for k in list(CONFIG_PADRAO.keys()) + ['min_anos_historico','min_meses_com_venda',
                                                'min_total_vendido','ignorar_sem_movimento_anos']:
            v = getattr(cfg_global, k, None)
            if v is not None:
                config[k] = v

    # Fetch per-month sales and diversity from PHC
    vendas_por_mes = {}
    vendas_lista   = []
    diversidade    = {}

    if cfg_phc and cfg_phc.ultima_sync:
        try:
            from phc_sync import get_phc_connection
            from reposicao import SQL_DIVERSIDADE_ARTIGO
            conn   = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            meses  = config.get('meses_historico', 60)
            cursor.execute(SQL_VENDAS_ARTIGO, ref, meses)
            for row in cursor.fetchall():
                ano, mes, total, nfat = row[0], row[1], float(row[2]), row[3]
                vendas_por_mes[(ano, mes)] = total
                vendas_lista.append({'ano':ano,'mes':mes,'total':total,'nfat':nfat})
            # Fetch invoice detail
            from reposicao import SQL_DETALHE_VENDAS
            cursor.execute(SQL_DETALHE_VENDAS, ref, meses)
            vendas_detalhe = []
            for row in cursor.fetchall():
                vendas_detalhe.append({
                    'num_fatura':   str(row[0]) if row[0] else '-',
                    'cliente_nome': (row[1] or '').strip(),
                    'data':         row[2].strftime('%d/%m/%Y') if row[2] else '',
                    'quantidade':   float(row[3]),
                    'preco_venda':  float(row[4] or 0),
                })
            # Diversity
            cursor.execute(SQL_DIVERSIDADE_ARTIGO, ref)
            row = cursor.fetchone()
            if row:
                diversidade = {'num_clientes': int(row[0] or 0),
                               'num_facturas': int(row[1] or 0)}
            conn.close()
        except Exception as e:
            app.logger.warning(f'PHC error analisar_artigo: {e}')

    stock  = artigo.stock_atual or 0
    preco  = artigo.preco_custo_ponderado or artigo.preco_custo or 0
    result = calcular_metricas(vendas_por_mes, stock, preco, config)
    result['referencia'] = ref
    result['designacao'] = artigo.designacao or ''
    result['stock_atual'] = stock
    result['preco_custo'] = preco
    result['unidade']    = artigo.unidade or 'un'

    # Compute period info for display
    periodo = {}
    if vendas_por_mes:
        chaves = sorted(vendas_por_mes.keys())
        primeiro = chaves[0]
        ultimo   = chaves[-1]
        from datetime import datetime as _dt
        meses_periodo = (_dt.now().year - primeiro[0])*12 + (_dt.now().month - primeiro[1]) + 1
        total_vendido = sum(vendas_por_mes.values())
        periodo = {
            'primeiro_mes': f"{primeiro[1]:02d}/{primeiro[0]}",
            'ultimo_mes':   f"{ultimo[1]:02d}/{ultimo[0]}",
            'meses_periodo': meses_periodo,
            'anos_periodo':  round(meses_periodo/12, 1),
            'total_vendido': total_vendido,
            'meses_com_venda': len([v for v in vendas_por_mes.values() if v>0]),
            'media_mensal':  round(total_vendido/meses_periodo, 3),
            'media_anual':   round(total_vendido/meses_periodo*12, 2),
        }

    # Sort vendas_lista by date
    vendas_lista.sort(key=lambda x: (x['ano'], x['mes']))

    # Compute relevance score
    score_info = {}
    previsoes  = {}
    if periodo:
        from reposicao import score_relevancia, calcular_todos_metodos
        previsoes = calcular_todos_metodos(vendas_por_mes, periodo.get('meses_periodo', 1))
        score_info = score_relevancia(
            total_vendido = periodo.get('total_vendido', 0),
            num_clientes  = diversidade.get('num_clientes', 0),
            num_facturas  = diversidade.get('num_facturas', 0),
            meses_periodo = periodo.get('meses_periodo', 1),
            preco_custo   = preco,
            config        = config,
        )

    return render_template('reposicao_artigo.html',
        artigo=artigo, result=result, vendas_lista=vendas_lista,
        periodo=periodo, config=config, score_info=score_info,
        diversidade=diversidade, previsoes=previsoes,
        vendas_detalhe=vendas_detalhe if 'vendas_detalhe' in dir() else [])


@app.route('/reposicao/lista')
@login_required
def lista_reposicao():
    """Return all articles needing replenishment as JSON (for table)."""
    from reposicao import analisar_artigo as _analisar, CONFIG_PADRAO

    cfg_phc    = ConfigPHC.query.first()
    cfg_global = ConfigReposicao.query.filter_by(artigo_ref=None).first()

    config = dict(CONFIG_PADRAO)
    if cfg_global:
        for k in CONFIG_PADRAO:
            v = getattr(cfg_global, k, None)
            if v is not None:
                config[k] = v

    familia = request.args.get('familia', '').strip()
    apenas_alertas = request.args.get('alertas', '0') == '1'

    query = ArtigoPHC.query
    if familia:
        query = query.filter_by(familia=familia)

    artigos = query.order_by(ArtigoPHC.referencia).limit(200).all()
    resultados = []
    for a in artigos:
        cfg_art = ConfigReposicao.query.filter_by(artigo_ref=a.referencia).first()
        cfg_final = dict(config)
        if cfg_art:
            for k in CONFIG_PADRAO:
                v = getattr(cfg_art, k, None)
                if v is not None: cfg_final[k] = v

        r = _analisar(cfg_phc, cfg_final, a.referencia,
                      stock_atual=a.stock_atual,
                      preco_custo=a.preco_custo_ponderado or a.preco_custo)

        if apenas_alertas and not r.get('precisa_encomendar'):
            continue
        # Skip completely inactive articles
        dias_sem_mov = r.get('dias_sem_movimento', 0) or 0
        if dias_sem_mov > cfg_final.get('ignorar_parados_dias', 365):
            continue

        resultados.append(r)

    # Sort: needs ordering first, then by coverage days
    resultados.sort(key=lambda x: (
        not x.get('precisa_encomendar', False),
        x.get('dias_cobertura_atual') or 9999
    ))

    return jsonify(resultados)


@app.route('/reposicao/gerar_pedido', methods=['POST'])
@login_required
def gerar_pedido_reposicao():
    """Create a PedidoCompra from selected replenishment suggestions."""
    data = request.get_json()
    artigos_sel = data.get('artigos', [])
    if not artigos_sel:
        return jsonify({'error': 'Nenhum artigo selecionado.'}), 400

    titulo = data.get('titulo') or f"Reposição de stock — {datetime.now().strftime('%d/%m/%Y')}"
    p = PedidoCompra(
        titulo=titulo,
        descricao='Gerado automaticamente pelo motor de reposição.',
        prioridade='normal',
        estado='aberto',
        criado_por=current_user.id,
        data_criacao=datetime.now()
    )
    db.session.add(p)
    db.session.flush()

    for i, a in enumerate(artigos_sel):
        artigo = ArtigoPHC.query.filter_by(referencia=a['referencia']).first()
        linha = LinhaPedido(
            pedido_id=p.id, ordem=i,
            artigo_ref=a['referencia'],
            referencia=a['referencia'],
            designacao=a.get('designacao', ''),
            unidade=a.get('unidade', 'un'),
            quantidade=float(a.get('quantidade_sugerida', 1)),
            stock_atual=float(artigo.stock_atual if artigo else 0),
            preco_custo_ref=float(artigo.preco_custo if artigo else 0),
            preco_pcp_ref=float(artigo.preco_custo_ponderado if artigo else 0),
        )
        db.session.add(linha)

    db.session.commit()
    return jsonify({'ok': True, 'pedido_id': p.id, 'titulo': titulo})

# ── BAK UPLOAD & RESTORE ──────────────────────────────────────────────────────

@app.route('/admin/phc/upload_bak', methods=['POST'])
@login_required
def upload_bak():
    if not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403
    if 'bak' not in request.files:
        return jsonify({'error': 'Nenhum ficheiro enviado.'}), 400
    file = request.files['bak']
    if not file.filename.lower().endswith('.bak'):
        return jsonify({'error': 'Apenas ficheiros .bak são aceites.'}), 400
    bak_path = os.path.join(app.config['BAK_FOLDER'], 'phc_backup.bak')
    file.save(bak_path)
    cfg = ConfigPHC.query.first()
    if not cfg:
        return jsonify({'error': 'Configure primeiro a ligação ao SQL Server.'}), 400
    win_path = os.path.abspath(bak_path)
    messages = []
    def progress(msg): messages.append(msg)
    try:
        from bak_restore import restore_bak, verify_phc_database
        ok, msg = restore_bak(cfg, win_path, progress_callback=progress)
        if not ok:
            return jsonify({'error': msg, 'log': messages}), 500
        valid, vmsg, stats = verify_phc_database(cfg)
        if not valid:
            return jsonify({'error': vmsg, 'log': messages}), 500
        messages.append(vmsg)
        from phc_sync import sync_all
        sync_stats = sync_all(app, cfg)
        messages.append(
            f"Sincronização: {sync_stats['artigos']['inseridos']} artigos novos / "
            f"{sync_stats['artigos']['atualizados']} atualizados"
        )
        return jsonify({
            'success': True, 'log': messages,
            'stats': {
                'artigos': sync_stats['artigos']['inseridos'] + sync_stats['artigos']['atualizados'],
                'fornecedores': sync_stats['fornecedores']['inseridos'] + sync_stats['fornecedores']['atualizados'],
            }
        })
    except ImportError as e:
        return jsonify({'error': f'Módulo em falta: {e}. Instale pyodbc.'}), 500
    except Exception as e:
        messages.append(f'Erro: {e}')
        return jsonify({'error': str(e), 'log': messages}), 500


@app.route('/admin/phc/check_sqlserver')
@login_required
def check_sqlserver():
    if not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403
    cfg = ConfigPHC.query.first()
    if not cfg:
        return jsonify({'ok': False, 'msg': 'Sem configuração SQL Server.'})
    try:
        from bak_restore import check_sqlserver_available
        ok, msg = check_sqlserver_available(cfg)
        return jsonify({'ok': ok, 'msg': msg})
    except ImportError:
        return jsonify({'ok': False, 'msg': 'pyodbc não instalado.'})

# ── PHC CONFIG & SYNC ─────────────────────────────────────────────────────────

@app.route('/admin/phc', methods=['GET','POST'])
@login_required
def admin_phc():
    if not current_user.is_admin:
        flash('Sem permissão.','error'); return redirect(url_for('dashboard'))
    cfg = ConfigPHC.query.first() or ConfigPHC()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save':
            cfg.servidor     = request.form.get('servidor', r'.\SQLEXPRESS').strip()
            cfg.porta        = int(request.form.get('porta', 1433))
            cfg.base_dados   = request.form.get('base_dados','PHC').strip()
            cfg.autenticacao = request.form.get('autenticacao','sql')
            cfg.utilizador   = request.form.get('utilizador','sa').strip()
            pw = request.form.get('password','')
            if pw: cfg.password = pw
            cfg.sync_auto = request.form.get('sync_auto') == 'on'
            cfg.sync_hora = request.form.get('sync_hora','06:00')
            if not cfg.id: db.session.add(cfg)
            db.session.commit()
            flash('Configuração guardada.','success')

        elif action == 'test':
            if not cfg.id:
                flash('Guarde primeiro a configuração.','error')
            else:
                try:
                    from phc_sync import test_connection
                    ok, msg = test_connection(cfg)
                    flash(msg, 'success' if ok else 'error')
                except ImportError:
                    flash('pyodbc não instalado. Instale com: pip install pyodbc','error')

        elif action == 'sync':
            if not cfg.id:
                flash('Configure e guarde a ligação primeiro.','error')
            else:
                try:
                    from phc_sync import sync_artigos, sync_fornecedores
                    ins_a, upd_a, err_a = sync_artigos(cfg)
                    ins_f, upd_f, err_f = sync_fornecedores(cfg)
                    from phc_sync import sync_clientes
                    ins_c, upd_c, err_c = sync_clientes(cfg)
                    cfg.ultima_sync = datetime.now()
                    db.session.commit()
                    msg = (f"✅ Sync concluída — "
                           f"Artigos: {ins_a}+{upd_a} | "
                           f"Fornecedores: {ins_f}+{upd_f} | "
                           f"Clientes: {ins_c}+{upd_c}")
                    if err_a or err_f or err_c:
                        msg += f" | {len(err_a+err_f+err_c)} erros"
                    flash(msg, 'success')
                except Exception as e:
                    import traceback
                    flash(f'Erro na sincronização: {e}', 'error')
                    logger.error(traceback.format_exc())

        return redirect(url_for('admin_phc'))

    total_artigos  = ArtigoPHC.query.count()
    total_forn     = FornecedorPHC.query.count()
    total_clientes = Cliente.query.count()
    return render_template('admin_phc.html', cfg=cfg,
                           total_artigos=total_artigos,
                           total_forn=total_forn,
                           total_clientes=total_clientes)

@app.route('/admin/utilizadores')
@login_required
def admin_utilizadores():
    if not current_user.is_admin:
        flash('Sem permissão.','error'); return redirect(url_for('dashboard'))
    perfis = Perfil.query.order_by(Perfil.nome).all()
    return render_template('admin_utilizadores.html', utilizadores=User.query.all(), perfis=perfis, get_user_perfil_id=get_user_perfil_id)

@app.route('/admin/utilizadores/novo', methods=['POST'])
@login_required
def novo_utilizador():
    if not current_user.is_admin: return jsonify({'error':'Sem permissão'}), 403
    username = request.form.get('username','').strip()
    if User.query.filter_by(username=username).first():
        flash('Username já existe.','error')
        return redirect(url_for('admin_utilizadores'))
    db.session.add(User(
        username=username, nome=request.form.get('nome','').strip(),
        password_hash=generate_password_hash(request.form.get('password','')),
        is_admin=request.form.get('is_admin')=='on',
        email=request.form.get('email','').strip(),
        departamento=request.form.get('departamento','').strip()))
    db.session.commit(); flash('Utilizador criado.','success')
    return redirect(url_for('admin_utilizadores'))

@app.route('/admin/utilizadores/<int:uid>/apagar', methods=['POST'])
@login_required
def apagar_utilizador(uid):
    if not current_user.is_admin: return jsonify({'error':'Sem permissão'}), 403
    if uid == current_user.id:
        flash('Não pode apagar a sua conta.','error')
        return redirect(url_for('admin_utilizadores'))
    db.session.delete(User.query.get_or_404(uid)); db.session.commit()
    flash('Utilizador removido.','info')
    return redirect(url_for('admin_utilizadores'))

# ── INIT ──────────────────────────────────────────────────────────────────────

# ── CHANGELOG ─────────────────────────────────────────────────────────────────

@app.route('/changelog')
@login_required
def changelog():
    try:
        entries = ChangelogEntry.query.order_by(ChangelogEntry.criado_em.desc()).limit(100).all()
    except Exception:
        entries = []
    return render_template('changelog.html', entries=entries)


# ── EMAIL CONSULTA ─────────────────────────────────────────────────────────────

@app.route('/api/email_consulta', methods=['POST'])
@login_required
def gerar_email_consulta():
    """Generate a quote request email text for a list of articles."""
    data       = request.get_json()
    fornecedor = data.get('fornecedor', '')
    artigos    = data.get('artigos', [])   # [{referencia, designacao, quantidade, unidade}]
    empresa    = data.get('empresa_propria', 'a nossa empresa')

    if not artigos:
        return jsonify({'error': 'Sem artigos'}), 400

    linhas_artigos = '\n'.join([
        f"  - {a.get('referencia','')} | {a.get('designacao','')} | Qtd: {a.get('quantidade',1)} {a.get('unidade','un')}"
        for a in artigos
    ])

    texto = f"""Boa tarde,

Gostaríamos de solicitar orçamento para os seguintes artigos/materiais:

{linhas_artigos}

Agradecemos o envio do vosso melhor preço, incluindo condições de pagamento, prazo de entrega e validade da proposta.

Para qualquer esclarecimento, estamos disponíveis.

Com os melhores cumprimentos,
{current_user.nome}
{empresa}"""

    return jsonify({
        'ok': True,
        'texto': texto,
        'assunto': f'Pedido de Orçamento — {len(artigos)} referência(s)',
        'para': data.get('email_fornecedor', ''),
    })


# ── PENDING MATCHES ───────────────────────────────────────────────────────────

@app.route('/pendentes')
@login_required
def pendentes():
    """All unconfirmed matches across all pedidos."""
    pedido_id = request.args.get('pedido_id', type=int)
    q = PendingMatch.query.filter_by(confirmado=False)
    if pedido_id:
        q = q.filter_by(pedido_id=pedido_id)
    pendentes = q.order_by(PendingMatch.criado_em.desc()).all()

    # Count by pedido for sidebar badge
    total = PendingMatch.query.filter_by(confirmado=False).count()
    artigos_phc = ArtigoPHC.query.order_by(ArtigoPHC.referencia).all()
    artigos_phc_json = json.dumps([{
        'referencia': a.referencia, 'designacao': a.designacao
    } for a in artigos_phc])
    return render_template('pendentes.html', pendentes=pendentes,
                           total=total, pedido_id_filtro=pedido_id,
                           artigos_phc=artigos_phc,
                           artigos_phc_json=artigos_phc_json)


@app.route('/pendentes/<int:pm_id>/confirmar', methods=['POST'])
@login_required
def confirmar_match(pm_id):
    """Confirm a pending match — saves alias and updates item."""
    pm = PendingMatch.query.get_or_404(pm_id)
    data = request.get_json()
    artigo_ref = data.get('artigo_ref', '').strip()

    if not artigo_ref:
        return jsonify({'error': 'artigo_ref obrigatório'}), 400

    # Verify article exists
    artigo = ArtigoPHC.query.filter_by(referencia=artigo_ref).first()
    if not artigo:
        return jsonify({'error': f'Artigo {artigo_ref} não encontrado'}), 404

    # Update pending match
    pm.confirmado        = True
    pm.artigo_ref_final  = artigo_ref
    pm.confirmado_por    = current_user.id
    pm.data_confirmacao  = datetime.now()

    # Update the item
    from models import ItemOrcamento
    item = ItemOrcamento.query.get(pm.item_id)
    if item:
        item.artigo_ref_match = artigo_ref
        item.match_confianca  = 1.0

    # Save alias so it learns
    from alias_matcher import save_alias
    save_alias(db, artigo_ref,
               pm.descricao_forn, pm.fornecedor,
               pm.referencia_forn, current_user.id, confianca=1.0)

    db.session.commit()
    return jsonify({'ok': True, 'artigo_ref': artigo_ref,
                    'designacao': artigo.designacao})


@app.route('/pendentes/<int:pm_id>/ignorar', methods=['POST'])
@login_required
def ignorar_match(pm_id):
    """Mark as confirmed with no match (intentionally unlinked)."""
    pm = PendingMatch.query.get_or_404(pm_id)
    pm.confirmado       = True
    pm.artigo_ref_final = None
    pm.confirmado_por   = current_user.id
    pm.data_confirmacao = datetime.now()
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/pendentes/count')
@login_required
def count_pendentes():
    """Badge count for sidebar."""
    n = PendingMatch.query.filter_by(confirmado=False).count()
    return jsonify({'count': n})


# ══════════════════════════════════════════════════════════════
#  CONFIG GERAL (tema, empresa, backup)
# ══════════════════════════════════════════════════════════════

def get_config_geral():
    cfg = ConfigGeral.query.first()
    if not cfg:
        cfg = ConfigGeral()
        db.session.add(cfg)
        db.session.commit()
    return cfg


@app.context_processor
def inject_config():
    """Make ConfigGeral and datetime available in all templates."""
    from datetime import datetime as _dt
    try:
        return {
            'cfg_geral': get_config_geral(),
            'cfg_ia': ConfigIA.query.first(),
            'now': _dt.now
        }
    except Exception:
        return {'cfg_geral': None, 'cfg_ia': None, 'now': _dt.now}


@app.route('/admin/config', methods=['GET', 'POST'])
@login_required
def admin_config():
    if not current_user.is_admin:
        flash('Sem permissão.', 'error')
        return redirect(url_for('dashboard'))
    # Ensure all columns exist (safe for older DBs)
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            for col, typ in [('dashboard_layouts','TEXT')]:
                try:
                    conn.execute(text(f"ALTER TABLE config_geral ADD COLUMN {col} {typ}"))
                    conn.commit()
                except Exception:
                    pass
    except Exception:
        pass
    cfg = get_config_geral()
    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action == 'save':
            cfg.empresa_nome       = request.form.get('empresa_nome', '').strip() or 'ComprasNet'
            cfg.empresa_abrev      = request.form.get('empresa_abrev', '').strip()
            cfg.empresa_nif        = request.form.get('empresa_nif', '').strip()
            cfg.empresa_morada     = request.form.get('empresa_morada', '').strip()
            cfg.empresa_tel        = request.form.get('empresa_tel', '').strip()
            cfg.empresa_email      = request.form.get('empresa_email', '').strip()
            cfg.cor_accent         = request.form.get('cor_accent', '#3b6ef0')
            cfg.cor_bg             = request.form.get('cor_bg', '#0f1117')
            cfg.cor_surface        = request.form.get('cor_surface', '#171b25')
            cfg.backup_local_path  = request.form.get('backup_local_path', 'backups').strip()
            cfg.backup_rede_path   = request.form.get('backup_rede_path', '').strip()
            cfg.backup_hora        = request.form.get('backup_hora', '02:00')
            cfg.backup_manter_dias = int(request.form.get('backup_manter_dias', 30))
            cfg.backup_auto_ativo  = request.form.get('backup_auto_ativo') == 'on'
            cfg.claude_chat_ativo  = request.form.get('claude_chat_ativo') == 'on'
            cfg.claude_chat_sistema= request.form.get('claude_chat_sistema', '').strip()
            try:
                cfg.logo_altura    = int(request.form.get('logo_altura', 48) or 48)
                cfg.logo_largura   = int(request.form.get('logo_largura', 180) or 180)
                cfg.logo_filtro    = request.form.get('logo_filtro', '').strip()
            except Exception:
                # Columns may not exist yet - run fix_db.py
                from sqlalchemy import text
                with db.engine.connect() as conn:
                    for col, typ, default in [
                        ('logo_altura','INTEGER','48'),
                        ('logo_largura','INTEGER','180'),
                        ('logo_filtro','VARCHAR(100)',"''"),
                    ]:
                        try:
                            conn.execute(text(f"ALTER TABLE config_geral ADD COLUMN {col} {typ} DEFAULT {default}"))
                            conn.commit()
                        except Exception:
                            pass
                cfg.logo_altura    = int(request.form.get('logo_altura', 48) or 48)
                cfg.logo_largura   = int(request.form.get('logo_largura', 180) or 180)
                cfg.logo_filtro    = request.form.get('logo_filtro', '').strip()
            # SMTP
            cfg.smtp_host = request.form.get('smtp_host', '').strip()
            cfg.smtp_port = int(request.form.get('smtp_port', 587) or 587)
            cfg.smtp_user = request.form.get('smtp_user', '').strip()
            smtp_pass_input = request.form.get('smtp_pass', '').strip()
            if smtp_pass_input:  # only update if not empty
                cfg.smtp_pass = smtp_pass_input
            cfg.smtp_from = request.form.get('smtp_from', '').strip()
            cfg.smtp_tls  = 1 if request.form.get('smtp_tls') else 0
            # Logo upload
            if 'logo' in request.files and request.files['logo'].filename:
                logo = request.files['logo']
                logo_path = os.path.join(app.config['UPLOAD_FOLDER'], 'logo_empresa.png')
                logo.save(logo_path)
                cfg.empresa_logo_path = 'logo_empresa.png'
            try:
                db.session.commit()
                flash('Configurações guardadas com sucesso! ✅', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao guardar: {e}', 'error')
        elif action == 'backup':
            from backup_manager import fazer_backup
            ok, msg = fazer_backup(app, cfg)
            flash(msg, 'success' if ok else 'error')
        return redirect(url_for('admin_config'))

    from backup_manager import listar_backups
    backups = listar_backups(app, cfg)
    return render_template('admin_config.html', cfg=cfg, backups=backups)


# ══════════════════════════════════════════════════════════════
#  CLIENTES
# ══════════════════════════════════════════════════════════════

@app.route('/clientes')
@login_required
def clientes():
    q = request.args.get('q', '').strip()
    query = Cliente.query.filter_by(ativo=True)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Cliente.nome.ilike(like),
            Cliente.abreviatura.ilike(like),
            Cliente.nif.ilike(like),
        ))
    todos = query.order_by(Cliente.nome).all()
    return render_template('clientes.html', clientes=todos, q=q)


@app.route('/clientes/sync_phc', methods=['POST'])
@login_required
def sync_clientes_phc():
    """Sync clients from PHC ec table (clientes only)."""
    if not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403
    cfg_phc = ConfigPHC.query.first()
    if not cfg_phc:
        return jsonify({'error': 'PHC não configurado'}), 400
    try:
        from phc_sync import get_phc_connection
        conn = get_phc_connection(cfg_phc)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT no, nome, ISNULL(abrev,'') abrev, ISNULL(ncont,'') nipc,
                   ISNULL(morada,'') morada, ISNULL(local,'') local,
                   ISNULL(codpost,'') codpost, ISNULL(pais,'Portugal') pais,
                   ISNULL(telefone,'') tel, ISNULL(tlm,'') tlm,
                   ISNULL(email,'') email, ISNULL(www,'') www
            FROM ec
            WHERE cliente=1 AND ISNULL(inactivo,0)=0
            ORDER BY nome
        """)
        rows = cursor.fetchall()
        conn.close()
        inseridos = atualizados = 0
        for r in rows:
            c = Cliente.query.filter_by(phc_no=int(r[0])).first()
            if c:
                c.nome=r[1];c.abreviatura=r[2];c.nif=r[3];c.morada=r[4]
                c.localidade=r[5];c.cod_postal=r[6];c.pais=r[7]
                c.telefone=r[8];c.telemovel=r[9];c.email=r[10];c.website=r[11]
                c.ultima_sync_phc=datetime.now(); atualizados+=1
            else:
                db.session.add(Cliente(phc_no=int(r[0]),nome=r[1],abreviatura=r[2],
                    nif=r[3],morada=r[4],localidade=r[5],cod_postal=r[6],pais=r[7],
                    telefone=r[8],telemovel=r[9],email=r[10],website=r[11],
                    ultima_sync_phc=datetime.now())); inseridos+=1
        db.session.commit()
        return jsonify({'ok':True,'inseridos':inseridos,'atualizados':atualizados})
    except Exception as e:
        return jsonify({'error':str(e)}), 500


@app.route('/clientes/novo', methods=['GET','POST'])
@login_required
def novo_cliente():
    if request.method == 'POST':
        nome = request.form.get('nome','').strip()
        if not nome:
            flash('Nome é obrigatório.','error')
            return render_template('cliente_form.html', cliente=None)
        c = Cliente(nome=nome,
            abreviatura=request.form.get('abreviatura','').strip(),
            nif=request.form.get('nif','').strip(),
            morada=request.form.get('morada','').strip(),
            localidade=request.form.get('localidade','').strip(),
            cod_postal=request.form.get('cod_postal','').strip(),
            pais=request.form.get('pais','Portugal').strip(),
            telefone=request.form.get('telefone','').strip(),
            telemovel=request.form.get('telemovel','').strip(),
            email=request.form.get('email','').strip(),
            website=request.form.get('website','').strip(),
            notas=request.form.get('notas','').strip())
        db.session.add(c); db.session.commit()
        flash(f'Cliente {nome} criado.','success')
        return redirect(url_for('cliente_detalhe', cid=c.id))
    return render_template('cliente_form.html', cliente=None)


@app.route('/clientes/<int:cid>')
@login_required
def cliente_detalhe(cid):
    c = Cliente.query.get_or_404(cid)
    # Get articles sold to this client from PHC
    consumiveis = []
    cfg_phc = ConfigPHC.query.first()
    if cfg_phc and cfg_phc.ultima_sync:
        try:
            from phc_sync import get_phc_connection
            conn = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP 200
                    fl.ref, fl.design, fl.qtt, fl.preco,
                    ft.data, ft.fno, ft.serie
                FROM fl
                INNER JOIN ft ON ft.ftstamp=fl.ftstamp
                INNER JOIN ec ON ec.no=ft.no
                WHERE ec.no=? AND ft.anulado=0
                  AND fl.ref IS NOT NULL AND fl.ref<>''
                ORDER BY ft.data DESC
            """, c.phc_no or -1)
            rows = cursor.fetchall()
            conn.close()
            consumiveis = [{'ref':r[0],'design':r[1],'qtt':float(r[2] or 0),
                            'preco':float(r[3] or 0),
                            'data':r[4].strftime('%d/%m/%Y') if r[4] else '—',
                            'doc':f"{r[6]}{r[5]}"} for r in rows]
        except Exception:
            pass
    return render_template('cliente_detalhe.html', cliente=c, consumiveis=consumiveis)


@app.route('/clientes/<int:cid>/editar', methods=['GET','POST'])
@login_required
def editar_cliente(cid):
    c = Cliente.query.get_or_404(cid)
    if request.method == 'POST':
        c.nome=request.form.get('nome','').strip()
        c.abreviatura=request.form.get('abreviatura','').strip()
        c.nif=request.form.get('nif','').strip()
        c.morada=request.form.get('morada','').strip()
        c.localidade=request.form.get('localidade','').strip()
        c.cod_postal=request.form.get('cod_postal','').strip()
        c.pais=request.form.get('pais','Portugal').strip()
        c.telefone=request.form.get('telefone','').strip()
        c.telemovel=request.form.get('telemovel','').strip()
        c.email=request.form.get('email','').strip()
        c.website=request.form.get('website','').strip()
        c.notas=request.form.get('notas','').strip()
        c.atualizado_em=datetime.now()
        db.session.commit()
        flash('Cliente atualizado.','success')
        return redirect(url_for('cliente_detalhe', cid=cid))
    return render_template('cliente_form.html', cliente=c)


# ── Embarcações ──────────────────────────────────────────────

@app.route('/clientes/<int:cid>/embarcacoes/nova', methods=['GET','POST'])
@login_required
def nova_embarcacao(cid):
    cliente = Cliente.query.get_or_404(cid)
    if request.method == 'POST':
        e = Embarcacao(
            cliente_id=cid,
            nome=request.form.get('nome','').strip(),
            matricula=request.form.get('matricula','').strip(),
            tipo=request.form.get('tipo','').strip(),
            ano_construcao=request.form.get('ano_construcao') or None,
            comprimento=request.form.get('comprimento') or None,
            largura=request.form.get('largura') or None,
            notas=request.form.get('notas','').strip()
        )
        db.session.add(e); db.session.flush()
        # Default components
        for cat in ['Motor Propulsor','Caixa Inversora/Redutora','Veio Propulsor','Hélice']:
            db.session.add(ComponenteEmbarcacao(
                embarcacao_id=e.id, categoria=cat,
                label=cat, campos_extra='[]', ordem=['Motor Propulsor','Caixa Inversora/Redutora','Veio Propulsor','Hélice'].index(cat)
            ))
        db.session.commit()
        flash(f'Embarcação {e.nome} criada.','success')
        return redirect(url_for('embarcacao_detalhe', cid=cid, eid=e.id))
    return render_template('embarcacao_form.html', cliente=cliente, embarcacao=None)


@app.route('/clientes/<int:cid>/embarcacoes/<int:eid>')
@login_required
def embarcacao_detalhe(cid, eid):
    cliente = Cliente.query.get_or_404(cid)
    emb = Embarcacao.query.filter_by(id=eid, cliente_id=cid).first_or_404()
    return render_template('embarcacao_detalhe.html', cliente=cliente, embarcacao=emb)


@app.route('/clientes/<int:cid>/embarcacoes/<int:eid>/componente', methods=['POST'])
@login_required
def salvar_componente(cid, eid):
    data = request.get_json()
    comp_id = data.get('id')
    if comp_id:
        comp = ComponenteEmbarcacao.query.get_or_404(comp_id)
    else:
        comp = ComponenteEmbarcacao(embarcacao_id=eid)
        db.session.add(comp)
    comp.categoria   = data.get('categoria','').strip()
    comp.label       = data.get('label','').strip()
    comp.marca       = data.get('marca','').strip()
    comp.modelo      = data.get('modelo','').strip()
    comp.num_serie   = data.get('num_serie','').strip()
    comp.ano         = data.get('ano') or None
    comp.campos_extra= json.dumps(data.get('campos_extra', []))
    comp.notas       = data.get('notas','').strip()
    comp.atualizado_em = datetime.now()
    db.session.commit()
    return jsonify({'ok': True, 'id': comp.id})


@app.route('/componentes/<int:comp_id>', methods=['DELETE'])
@login_required
def apagar_componente(comp_id):
    comp = ComponenteEmbarcacao.query.get_or_404(comp_id)
    db.session.delete(comp); db.session.commit()
    return jsonify({'ok': True})


# ── PHC Consumíveis search ───────────────────────────────────

@app.route('/api/clientes/<int:cid>/consumiveis')
@login_required
def api_consumiveis_cliente(cid):
    cliente = Cliente.query.get_or_404(cid)
    q = request.args.get('q','').strip()
    cfg_phc = ConfigPHC.query.first()
    if not cfg_phc or not cfg_phc.ultima_sync or not cliente.phc_no:
        return jsonify([])
    try:
        from phc_sync import get_phc_connection
        conn = get_phc_connection(cfg_phc)
        cursor = conn.cursor()
        like = f'%{q}%' if q else '%'
        cursor.execute("""
            SELECT TOP 100
                fl.ref, fl.design, fl.qtt, fl.preco, ft.data, ft.fno, ft.serie
            FROM fl
            INNER JOIN ft ON ft.ftstamp=fl.ftstamp
            WHERE ft.no=? AND ft.anulado=0
              AND (fl.ref LIKE ? OR fl.design LIKE ?)
              AND fl.ref IS NOT NULL AND fl.ref<>''
            ORDER BY ft.data DESC
        """, cliente.phc_no, like, like)
        rows = cursor.fetchall()
        conn.close()
        return jsonify([{
            'ref':r[0],'design':r[1],'qtt':float(r[2] or 0),
            'preco':float(r[3] or 0),
            'data':r[4].strftime('%d/%m/%Y') if r[4] else '—',
            'doc':f"{r[6]}{r[5]}"
        } for r in rows])
    except Exception as e:
        return jsonify({'error':str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  CLAUDE CHAT
# ══════════════════════════════════════════════════════════════

@app.route('/chat')
@login_required
def chat_claude():
    cfg = get_config_geral()
    cfg_ia = ConfigIA.query.first()
    return render_template('chat_claude.html', cfg=cfg, cfg_ia=cfg_ia)


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    """Chat using the configured AI provider (Gemini, Claude, LM Studio, Ollama)."""
    data       = request.get_json()
    # Support both 'messages' array and single 'message' string
    single_msg = data.get('message')
    messages   = data.get('messages', [])
    if single_msg and not messages:
        messages = [{'role': 'user', 'content': single_msg}]
    imagem_b64 = data.get('imagem_b64')
    imagem_tipo= data.get('imagem_tipo', 'image/jpeg')

    cfg_ia  = ConfigIA.query.first()
    cfg     = get_config_geral()
    # Allow caller to override system prompt (e.g. from backlog AI agent)
    _sys_override = data.get('system', '').strip()
    if _sys_override:
        sistema = _sys_override
    else:
        sistema = (cfg.claude_chat_sistema if cfg else None) or \
                  'Es um assistente tecnico especializado em equipamentos e compras industriais. Responde sempre em portugues.'

    if not cfg_ia:
        return jsonify({'error': 'IA não configurada. Configure em Admin → Provedor IA.'}), 400

    provider = cfg_ia.provider

    try:
        # ── Gemini ────────────────────────────────────────────────────────────
        if provider == 'gemini':
            from ai_provider import _get_best_gemini_model
            api_key = cfg_ia.gemini_api_key or ''
            if not api_key:
                return jsonify({'error': 'Chave API Gemini não configurada.'}), 400
            model = cfg_ia.gemini_model or _get_best_gemini_model(api_key)
            # Build conversation history for Gemini
            contents = []
            if sistema:
                contents.append({'role':'user','parts':[{'text': sistema}]})
                contents.append({'role':'model','parts':[{'text': 'Entendido. Estou pronto para ajudar.'}]})
            for m in messages:
                role = 'user' if m['role'] == 'user' else 'model'
                parts = []
                if imagem_b64 and m == messages[-1]:
                    parts.append({'inline_data':{'mime_type': imagem_tipo, 'data': imagem_b64}})
                parts.append({'text': m['content']})
                contents.append({'role': role, 'parts': parts})
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = json.dumps({
                'contents': contents,
                'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 1500}
            }).encode()
            import urllib.request
            req = urllib.request.Request(url, data=payload,
                headers={'Content-Type':'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            text = resp['candidates'][0]['content']['parts'][0]['text']
            return jsonify({'ok': True, 'text': text, 'provider': 'gemini', 'model': model})

        # ── Claude API ────────────────────────────────────────────────────────
        elif provider == 'claude':
            import anthropic
            client = anthropic.Anthropic(api_key=cfg_ia.claude_api_key or '')
            last = messages[-1] if messages else {'role':'user','content':'Olá'}
            content = []
            if imagem_b64:
                content.append({'type':'image','source':{
                    'type':'base64','media_type':imagem_tipo,'data':imagem_b64}})
            content.append({'type':'text','text':last.get('content','')})
            api_msgs = [{'role':m['role'],'content':m['content']} for m in messages[:-1]]
            api_msgs.append({'role':last['role'],'content':content})
            resp = client.messages.create(
                model='claude-sonnet-4-20250514', max_tokens=1500,
                system=sistema, messages=api_msgs)
            return jsonify({'ok':True,'text':resp.content[0].text, 'provider':'claude'})

        # ── LM Studio / Ollama ────────────────────────────────────────────────
        elif provider in ('lmstudio', 'ollama'):
            import urllib.request
            base = f"http://{cfg_ia.lm_host}:{cfg_ia.lm_port}"
            api_msgs = [{'role':'system','content':sistema}] + [
                {'role':m['role'],'content':m['content']} for m in messages]
            payload = json.dumps({
                'model': cfg_ia.lm_model or 'default',
                'messages': api_msgs,
                'temperature': 0.7, 'max_tokens': 1500, 'stream': False
            }).encode()
            req = urllib.request.Request(base + '/v1/chat/completions', data=payload,
                headers={'Content-Type':'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            return jsonify({'ok':True,'text':resp['choices'][0]['message']['content'],
                           'provider':provider})

        else:
            return jsonify({'error': f'Provedor "{provider}" não suportado no chat.'}), 400

    except Exception as e:
        err = str(e)
        # Friendlier error messages
        if 'Connection refused' in err or 'recusou' in err.lower():
            prov = cfg_ia.provider if cfg_ia else 'local'
            msg = f'Não foi possível ligar ao servidor {prov.upper()}. Verifique se está a correr em {cfg_ia.lm_host}:{cfg_ia.lm_port}.'
        elif 'API_KEY_INVALID' in err or 'invalid' in err.lower():
            msg = 'Chave API inválida. Verifique em Admin → Provedor IA.'
        else:
            msg = err
        return jsonify({'ok': False, 'error': msg})


# ── AUTO-UPDATE ────────────────────────────────────────────────────────────────

@app.route('/admin/update', methods=['GET', 'POST'])
@login_required
def admin_update():
    if not current_user.is_admin:
        flash('Sem permissão.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('admin_update.html')


@app.route('/api/update/check')
@login_required
def update_check():
    """Check if there are updates available on GitHub."""
    if not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403
    import subprocess
    cwd = os.path.dirname(os.path.abspath(__file__))

    def run(cmd):
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=30, cwd=cwd)

    try:
        # Init git if not present
        if not os.path.exists(os.path.join(cwd, '.git')):
            run(['git', 'init'])
            run(['git', 'remote', 'add', 'origin',
                 'https://github.com/luismiguelsilvauni-cpu/comprasnet.git'])
        else:
            # Ensure remote exists
            r = run(['git', 'remote', 'get-url', 'origin'])
            if r.returncode != 0:
                run(['git', 'remote', 'add', 'origin',
                     'https://github.com/luismiguelsilvauni-cpu/comprasnet.git'])

        # Fetch remote without merging
        result = run(['git', 'fetch', 'origin', 'main'])
        if result.returncode != 0:
            return jsonify({'error': f'Erro ao verificar: {result.stderr.strip()}'}), 500

        # Compare local vs remote
        local = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))
        ).stdout.strip()

        remote = subprocess.run(
            ['git', 'rev-parse', 'origin/main'],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))
        ).stdout.strip()

        # Get list of new commits
        log = subprocess.run(
            ['git', 'log', f'HEAD..origin/main', '--oneline'],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))
        ).stdout.strip()

        tem_updates = local != remote
        commits = [l for l in log.split('\n') if l.strip()] if log else []

        return jsonify({
            'tem_updates': tem_updates,
            'commits_pendentes': len(commits),
            'commits': commits[:10],
            'versao_local':  local[:8],
            'versao_remota': remote[:8],
        })
    except FileNotFoundError:
        return jsonify({'error': 'Git não encontrado. Instale o Git.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/update/apply', methods=['POST'])
@login_required
def update_apply():
    """Apply updates from GitHub (git pull + db upgrade)."""
    if not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403
    import subprocess
    cwd = os.path.dirname(os.path.abspath(__file__))

    def run(cmd):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=cwd)
        return r.returncode == 0, r.stdout + r.stderr

    steps = []

    # 1. Backup first
    try:
        from backup_manager import fazer_backup
        ok, msg = fazer_backup(app)
        steps.append({'passo': 'Backup', 'ok': ok, 'msg': msg.split("\n")[0]})
    except Exception as e:
        steps.append({'passo': 'Backup', 'ok': False, 'msg': str(e)})

    # 0. Init git if not present
    git_dir = os.path.join(cwd, '.git')
    if not os.path.exists(git_dir):
        ok0, out0 = run(['git', 'init'])
        run(['git', 'remote', 'add', 'origin',
             'https://github.com/luismiguelsilvauni-cpu/comprasnet.git'])
        steps.append({'passo': 'Git inicializado', 'ok': ok0, 'msg': 'Repositório Git criado'})
    else:
        # Ensure remote exists
        ok_r, out_r = run(['git', 'remote', 'get-url', 'origin'])
        if not ok_r:
            run(['git', 'remote', 'add', 'origin',
                 'https://github.com/luismiguelsilvauni-cpu/comprasnet.git'])
            steps.append({'passo': 'Remote configurado', 'ok': True, 'msg': 'github.com/luismiguelsilvauni-cpu/comprasnet'})

    # 2. Git fetch
    ok, out = run(['git', 'fetch', 'origin', 'main'])
    steps.append({'passo': 'Verificar actualizações (git fetch)', 'ok': ok, 'msg': 'OK' if ok else out[:200]})

    # Force checkout all tracked files from origin/main (no merge conflicts)
    ok, out = run(['git', 'checkout', 'origin/main', '--', '.'])
    steps.append({'passo': 'Aplicar ficheiros actualizados', 'ok': ok, 'msg': 'OK' if ok else out[:200]})
    if not ok:
        # Fallback: try pull with unrelated histories
        ok, out = run(['git', 'pull', 'origin', 'main', '--allow-unrelated-histories'])
        steps.append({'passo': 'Download (fallback pull)', 'ok': ok, 'msg': out[:200]})
        if not ok:
            return jsonify({'ok': False, 'steps': steps, 'msg': 'Falhou na actualização'})

    # Auto-register commits in changelog and backlog
    try:
        log_r = subprocess.run(
            ['git', 'log', 'ORIG_HEAD..HEAD', '--oneline', '--no-merges'],
            capture_output=True, text=True, cwd=cwd
        )
        for line in log_r.stdout.strip().splitlines():
            if ' ' in line:
                commit_msg = line.split(' ', 1)[1].strip()
                auto_registar_commit(commit_msg)
    except Exception as e:
        app.logger.warning(f"Auto-register error: {e}")

    # 3. pip install
    import sys
    ok, out = run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '-q'])
    steps.append({'passo': 'Dependências Python', 'ok': ok, 'msg': 'OK' if ok else out[:200]})

    # 4. DB migrations
    ok, out = run([sys.executable, '-m', 'flask', 'db', 'upgrade'])
    steps.append({'passo': 'Migração base de dados', 'ok': ok, 'msg': 'OK' if ok else out[:200]})

    # 5. Restart — try service first, fallback to process restart
    steps.append({'passo': 'Reiniciar servidor', 'ok': True, 'msg': 'A reiniciar em 3 segundos...'})

    def restart():
        import time, subprocess, sys
        time.sleep(3)
        # Try NSSM service restart first
        nssm = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nssm.exe')
        if os.path.exists(nssm):
            subprocess.Popen([nssm, 'restart', 'ComprasNet'],
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            # Restart as standalone process
            subprocess.Popen([sys.executable, os.path.abspath(__file__)],
                           cwd=os.path.dirname(os.path.abspath(__file__)),
                           creationflags=subprocess.CREATE_NO_WINDOW
                           if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            import signal
            os.kill(os.getpid(), signal.SIGTERM)

    import threading
    threading.Thread(target=restart, daemon=True).start()

    return jsonify({'ok': True, 'steps': steps,
                    'msg': 'Actualização aplicada. O servidor irá reiniciar automaticamente.'})


# ── TUNNEL STATUS ─────────────────────────────────────────────────────────────

# Global variable to store tunnel URL
_tunnel_url = None

def set_tunnel_url(url: str):
    global _tunnel_url
    _tunnel_url = url

def detect_tunnel_url() -> str | None:
    """Try to detect active Cloudflare Tunnel URL from cloudflared process."""
    global _tunnel_url
    if _tunnel_url:
        return _tunnel_url
    try:
        import subprocess, re
        # Try to read cloudflared log from temp file if arrancar_externo.bat writes it
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tunnel.log')
        if os.path.exists(log_path):
            with open(log_path, 'r', errors='ignore') as f:
                content = f.read()
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', content)
            if match:
                _tunnel_url = match.group(0)
                return _tunnel_url
        # Try cloudflared metrics API
        import urllib.request
        with urllib.request.urlopen('http://localhost:20241/metrics', timeout=2) as r:
            metrics = r.read().decode()
        # Parse hostname from metrics
        match = re.search(r'cloudflared_tunnel_user_hostnames_counts\{[^}]*hostname="([^"]+)"', metrics)
        if match:
            hostname = match.group(1)
            if hostname and '.' in hostname:
                _tunnel_url = f'https://{hostname}'
                return _tunnel_url
    except Exception:
        pass
    return _tunnel_url


@app.route('/conectividade')
@login_required
def conectividade():
    tunnel_url = None
    try:
        import subprocess
        r = subprocess.run(['curl', '-s', 'http://localhost:4040/api/tunnels'],
            capture_output=True, text=True, timeout=2)
        import json as _j
        data = _j.loads(r.stdout)
        tunnels = data.get('tunnels', [])
        if tunnels:
            tunnel_url = tunnels[0].get('public_url', '')
    except: pass
    return render_template('conectividade.html', tunnel_url=tunnel_url)

@app.route('/acesso-externo')
@login_required
def acesso_externo():
    tunnel_url = detect_tunnel_url()
    return render_template('acesso_externo.html', tunnel_url=tunnel_url)


@app.route('/api/tunnel/url', methods=['GET', 'POST'])
@login_required
def api_tunnel_url():
    global _tunnel_url
    if request.method == 'POST':
        data = request.get_json()
        url = data.get('url', '').strip()
        if url.startswith('https://') and 'trycloudflare.com' in url:
            _tunnel_url = url
            return jsonify({'ok': True, 'url': url})
        return jsonify({'error': 'URL inválido'}), 400
    return jsonify({'url': _tunnel_url, 'ativo': _tunnel_url is not None})


@app.route('/api/gemini/models')
@login_required
def api_gemini_models():
    """Fetch available Gemini models from Google API in real-time."""
    cfg_ia = ConfigIA.query.first()
    if not cfg_ia or not cfg_ia.gemini_api_key:
        return jsonify({'error': 'Chave API Gemini não configurada'}), 400
    try:
        import urllib.request, json as _json
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={cfg_ia.gemini_api_key}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
        # Filter only models that support generateContent
        models = []
        for m in data.get('models', []):
            methods = m.get('supportedGenerationMethods', [])
            if 'generateContent' in methods:
                name = m['name'].replace('models/', '')
                # Only include flash/pro variants (skip embedding etc)
                if any(x in name for x in ['flash', 'pro', 'ultra']):
                    models.append({
                        'id': name,
                        'label': m.get('displayName', name),
                        'description': m.get('description', '')[:80],
                    })
        # Sort: flash first, then pro
        models.sort(key=lambda x: (0 if 'flash' in x['id'] else 1, x['id']))
        return jsonify({'models': models})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return jsonify({'error': f'Erro HTTP {e.code}: {body[:150]}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── PWA + MOBILE ──────────────────────────────────────────────────────────────

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json',
                               mimetype='application/manifest+json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js',
                               mimetype='application/javascript')

@app.route('/mobile')
@login_required
def mobile_home():
    total_artigos  = ArtigoPHC.query.count()
    pedidos_abertos = PedidoCompra.query.filter_by(estado='aberto').count()
    total_clientes = Cliente.query.filter_by(ativo=True).count()
    return render_template('mobile/home.html',
        total_artigos=total_artigos,
        pedidos_abertos=pedidos_abertos,
        total_clientes=total_clientes)

@app.route('/mobile/artigos')
@login_required
def mobile_artigos():
    q = request.args.get('q', '').strip()
    artigos = []
    if q and len(q) >= 2:
        like = f'%{q}%'
        artigos = ArtigoPHC.query.filter(db.or_(
            ArtigoPHC.referencia.ilike(like),
            ArtigoPHC.designacao.ilike(like),
        )).order_by(ArtigoPHC.referencia).limit(30).all()
    return render_template('mobile/artigos.html', artigos=artigos, q=q)

@app.route('/mobile/artigos/<ref>')
@login_required
def mobile_artigo_detalhe(ref):
    artigo = ArtigoPHC.query.filter_by(referencia=ref).first_or_404()
    historico = []
    try:
        cfg_phc = ConfigPHC.query.first()
        if cfg_phc and cfg_phc.ultima_sync:
            from phc_sync import get_historico_compras
            historico = get_historico_compras(cfg_phc, ref)[:5]
    except Exception:
        pass
    return render_template('mobile/artigo_detalhe.html', artigo=artigo, historico=historico)

@app.route('/mobile/pedidos')
@login_required
def mobile_pedidos():
    estado = request.args.get('estado', '')
    q = PedidoCompra.query
    if estado:
        q = q.filter_by(estado=estado)
    pedidos = q.order_by(PedidoCompra.data_criacao.desc()).limit(30).all()
    return render_template('mobile/pedidos.html', pedidos=pedidos, estado=estado)

@app.route('/mobile/clientes')
@login_required
def mobile_clientes():
    q_str = request.args.get('q', '').strip()
    query = Cliente.query.filter_by(ativo=True)
    if q_str:
        like = f'%{q_str}%'
        query = query.filter(db.or_(
            Cliente.nome.ilike(like),
            Cliente.nif.ilike(like),
        ))
    clientes = query.order_by(Cliente.nome).limit(30).all()
    return render_template('mobile/clientes.html', clientes=clientes, q=q_str)

@app.route('/mobile/clientes/<int:cid>')
@login_required
def mobile_cliente_detalhe(cid):
    cliente = Cliente.query.get_or_404(cid)
    return render_template('mobile/cliente_detalhe.html', cliente=cliente)

@app.route('/mobile/chat')
@login_required
def mobile_chat():
    cfg_ia = ConfigIA.query.first()
    return render_template('mobile/chat.html', cfg_ia=cfg_ia)


# ══════════════════════════════════════════════════════════════
#  STOCK
# ══════════════════════════════════════════════════════════════

@app.route('/stock')
@login_required
def stock():
    q = request.args.get('q', '').strip()
    if q and len(q) >= 2:
        like = f'%{q}%'
        artigos = ArtigoPHC.query.filter(db.or_(
            ArtigoPHC.referencia.ilike(like),
            ArtigoPHC.designacao.ilike(like),
            ArtigoPHC.familia.ilike(like),
        )).order_by(ArtigoPHC.referencia).limit(500).all()
    else:
        artigos = ArtigoPHC.query.order_by(ArtigoPHC.referencia).limit(200).all()
    return render_template('stock.html', artigos=artigos, q=q, total=ArtigoPHC.query.count())


@app.route('/stock/<ref>')
@login_required
def stock_artigo(ref):
    artigo = ArtigoPHC.query.filter_by(referencia=ref).first_or_404()
    historico = []
    vendas = []
    try:
        cfg_phc = ConfigPHC.query.first()
        if cfg_phc and cfg_phc.ultima_sync:
            from phc_sync import get_historico_compras, get_phc_connection
            historico = get_historico_compras(cfg_phc, ref)
            # Get sales history
            try:
                conn = get_phc_connection(cfg_phc)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT TOP 30 fl.preco, fl.qtt, ft.data, ec.nome
                    FROM fl
                    INNER JOIN ft ON ft.ftstamp=fl.ftstamp
                    LEFT JOIN ec ON ec.no=ft.no
                    WHERE fl.ref=? AND ft.anulado=0
                    ORDER BY ft.data DESC
                """, ref)
                rows = cursor.fetchall()
                conn.close()
                vendas = [{'preco': float(r[0] or 0), 'qtt': float(r[1] or 0),
                           'data': r[2].strftime('%Y-%m-%d') if r[2] else '',
                           'cliente': r[3] or ''} for r in rows]
            except Exception:
                pass
    except Exception:
        pass

    # Get notes for this article
    from models import NotaArtigo
    notas = NotaArtigo.query.filter_by(artigo_ref=ref).order_by(NotaArtigo.criado_em.desc()).all()
    return render_template('stock_artigo.html', artigo=artigo,
                           historico=historico, vendas=vendas, notas=notas)


@app.route('/stock/<ref>/nota', methods=['POST'])
@login_required
def stock_artigo_nota(ref):
    artigo = ArtigoPHC.query.filter_by(referencia=ref).first_or_404()
    from models import NotaArtigo
    texto = request.form.get('texto', '').strip()
    if texto:
        nota = NotaArtigo(artigo_ref=ref, texto=texto,
                          criado_por=current_user.id)
        db.session.add(nota)
        db.session.commit()
        flash('Nota guardada.', 'success')
    return redirect(url_for('stock_artigo', ref=ref))


@app.route('/stock/<ref>/nota/<int:nid>/apagar', methods=['POST'])
@login_required
def stock_apagar_nota(ref, nid):
    from models import NotaArtigo
    nota = NotaArtigo.query.get_or_404(nid)
    db.session.delete(nota); db.session.commit()
    return jsonify({'ok': True})




# ── DASHBOARD WIDGETS ─────────────────────────────────────────────────────────

@app.route('/api/dashboard/layout', methods=['GET'])
@login_required
def get_dashboard_layout():
    """Get saved widget layout for current user."""
    from models import ConfigGeral
    cfg = get_config_geral()
    key = f'dashboard_layout_{current_user.id}'
    layout_json = getattr(cfg, 'dashboard_layouts', None)
    # Store per-user layouts in a simple JSON field
    try:
        import json as _json
        layouts = _json.loads(cfg.dashboard_layouts or '{}') if hasattr(cfg, 'dashboard_layouts') else {}
        return jsonify(layouts.get(str(current_user.id), []))
    except Exception:
        return jsonify([])

@app.route('/api/dashboard/layout', methods=['POST'])
@login_required
def save_dashboard_layout():
    """Save widget layout for current user."""
    data = request.get_json()
    try:
        from models import ConfigGeral
        cfg = get_config_geral()
        if not hasattr(cfg, 'dashboard_layouts') or cfg.dashboard_layouts is None:
            cfg.dashboard_layouts = '{}'
        layouts = json.loads(cfg.dashboard_layouts)
        layouts[str(current_user.id)] = data
        cfg.dashboard_layouts = json.dumps(layouts)
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  CALENDÁRIO
# ══════════════════════════════════════════════════════════════

@app.route('/api/calendario/eventos')
@login_required
def api_calendario_eventos():
    """Return events for a given month/range."""
    ano  = request.args.get('ano',  type=int, default=datetime.now().year)
    mes  = request.args.get('mes',  type=int, default=datetime.now().month)
    from datetime import date
    inicio = date(ano, mes, 1)
    # Last day of month
    import calendar as cal
    ultimo = cal.monthrange(ano, mes)[1]
    fim    = date(ano, mes, ultimo)

    eventos = EventoCalendario.query.filter(
        EventoCalendario.data_inicio >= inicio,
        EventoCalendario.data_inicio <= fim
    ).order_by(EventoCalendario.data_inicio).all()

    return jsonify([{
        'id':          e.id,
        'titulo':      e.titulo,
        'tipo':        e.tipo,
        'data_inicio': e.data_inicio.strftime('%Y-%m-%d'),
        'data_fim':    e.data_fim.strftime('%Y-%m-%d') if e.data_fim else None,
        'hora':        e.hora,
        'descricao':   e.descricao,
        'artigos':     json.loads(e.artigos_json or '[]'),
        'pedido_id':   e.pedido_id,
        'fornecedor':  e.fornecedor,
        'concluido':   e.concluido,
        'criado_por':  e.criado_por,
        'criado_nome': User.query.get(e.criado_por).nome if e.criado_por else '—',
    } for e in eventos])


@app.route('/api/calendario/eventos', methods=['POST'])
@login_required
def api_criar_evento():
    if not current_user.is_authenticated:
        return jsonify({'error': 'Sessão expirada'}), 401
    if not current_user.is_authenticated:
        return jsonify({'error': 'Sessão expirada — recarregue a página'}), 401
    data = request.get_json()
    from datetime import date
    def parse_date(s):
        return datetime.strptime(s, '%Y-%m-%d').date() if s else None

    e = EventoCalendario(
        titulo       = data.get('titulo','').strip() or 'Sem título',
        tipo         = data.get('tipo','manual'),
        data_inicio  = parse_date(data.get('data_inicio')),
        data_fim     = parse_date(data.get('data_fim')),
        hora         = (data.get('hora') or '').strip() or None,
        descricao    = data.get('descricao','').strip(),
        artigos_json = json.dumps(data.get('artigos',[])),
        pedido_id    = data.get('pedido_id'),
        fornecedor   = data.get('fornecedor','').strip(),
        concluido    = data.get('concluido', False),
        criado_por   = current_user.id,
    )
    db.session.add(e)
    db.session.commit()
    return jsonify({'ok': True, 'id': e.id})


@app.route('/api/calendario/eventos/<int:eid>', methods=['PUT'])
@login_required
def api_atualizar_evento(eid):
    e    = EventoCalendario.query.get_or_404(eid)
    data = request.get_json()
    from datetime import date
    def parse_date(s):
        return datetime.strptime(s, '%Y-%m-%d').date() if s else None

    if 'titulo'      in data: e.titulo       = data['titulo']
    if 'tipo'        in data: e.tipo         = data['tipo']
    if 'data_inicio' in data: e.data_inicio  = parse_date(data['data_inicio'])
    if 'data_fim'    in data: e.data_fim     = parse_date(data['data_fim'])
    if 'hora'        in data: e.hora         = data['hora'] or None
    if 'descricao'   in data: e.descricao    = data['descricao']
    if 'artigos'     in data: e.artigos_json = json.dumps(data['artigos'])
    if 'fornecedor'  in data: e.fornecedor   = data['fornecedor']
    if 'concluido'   in data: e.concluido    = data['concluido']
    if 'pedido_id'   in data: e.pedido_id    = data['pedido_id']
    e.atualizado_em = datetime.now()
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/calendario/eventos/<int:eid>', methods=['DELETE'])
@login_required
def api_apagar_evento(eid):
    e = EventoCalendario.query.get_or_404(eid)
    db.session.delete(e)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/calendario/pedido/<int:pid>/criar_eventos', methods=['POST'])
@login_required
def api_criar_eventos_pedido(pid):
    """Create purchase + delivery events from an approved pedido."""
    pedido = PedidoCompra.query.get_or_404(pid)
    data   = request.get_json()
    from datetime import date, timedelta

    artigos = [{'ref': l.artigo_ref, 'design': l.designacao, 'qtt': l.quantidade}
               for l in pedido.linhas if l.artigo_ref]

    data_compra = datetime.strptime(data.get('data_compra', datetime.now().strftime('%Y-%m-%d')), '%Y-%m-%d').date()
    dias_entrega = int(data.get('dias_entrega', 7))
    data_entrega = data_compra + timedelta(days=dias_entrega)
    fornecedor   = data.get('fornecedor', '')

    # Create compra event
    e1 = EventoCalendario(
        titulo       = f'Compra: PC-{pid:04d} — {pedido.titulo[:40]}',
        tipo         = 'compra',
        data_inicio  = data_compra,
        artigos_json = json.dumps(artigos),
        pedido_id    = pid,
        fornecedor   = fornecedor,
        criado_por   = current_user.id,
    )
    # Create delivery event
    e2 = EventoCalendario(
        titulo       = f'Entrega prevista: PC-{pid:04d} — {pedido.titulo[:30]}',
        tipo         = 'entrega_prevista',
        data_inicio  = data_entrega,
        artigos_json = json.dumps(artigos),
        pedido_id    = pid,
        fornecedor   = fornecedor,
        criado_por   = current_user.id,
    )
    db.session.add(e1); db.session.add(e2)
    db.session.commit()
    return jsonify({'ok': True, 'id_compra': e1.id, 'id_entrega': e2.id,
                    'data_entrega': data_entrega.strftime('%Y-%m-%d')})


# ── HEALTH CHECK ──────────────────────────────────────────────────────────────

@app.route('/admin/health')
@login_required
def admin_health():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    from health_check import startup_check
    result = startup_check(app, auto_fix=True)
    return render_template('admin_health.html', result=result)


@app.route('/admin/config/remove-logo', methods=['POST'])
@login_required
def remove_logo():
    if not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403
    cfg = get_config_geral()
    if cfg.empresa_logo_path:
        logo_path = os.path.join(app.config['UPLOAD_FOLDER'], cfg.empresa_logo_path)
        try:
            if os.path.exists(logo_path):
                os.remove(logo_path)
        except Exception:
            pass
        cfg.empresa_logo_path = None
        db.session.commit()
    return jsonify({'ok': True})


@app.route('/reposicao/por-fornecedor')
@login_required
def reposicao_por_fornecedor():
    """Group articles needing replenishment by their usual supplier."""
    from reposicao import CONFIG_PADRAO, analisar_todos
    import json as _json

    cfg_phc    = ConfigPHC.query.first()
    cfg_global = ConfigReposicao.query.filter_by(artigo_ref=None).first()

    config = dict(CONFIG_PADRAO)
    if cfg_global:
        config.update({
            'meses_historico':             cfg_global.meses_historico or 60,
            'lead_time_dias':              cfg_global.lead_time_dias or 7,
            'fator_seguranca':             cfg_global.fator_seguranca or 1.5,
            'meses_cobertura':             cfg_global.meses_cobertura or 2,
            'custo_encomenda':             cfg_global.custo_encomenda or 25,
            'taxa_posse_anual':            cfg_global.taxa_posse_anual or 0.20,
            'quantidade_minima_encomenda': cfg_global.quantidade_minima_encomenda or 1,
            'alertar_dias_cobertura':      cfg_global.alertar_dias_cobertura or 30,
            'min_anos_historico':          getattr(cfg_global,'min_anos_historico',2) or 2,
            'min_meses_com_venda':         getattr(cfg_global,'min_meses_com_venda',3) or 3,
            'min_total_vendido':           getattr(cfg_global,'min_total_vendido',3) or 3,
            'ignorar_sem_movimento_anos':  getattr(cfg_global,'ignorar_sem_movimento_anos',3) or 3,
            'min_facturas_sugerir':        getattr(cfg_global,'min_facturas_sugerir',8) or 8,
        })

    # SQL: for each article, find most frequent supplier from purchase invoices (fo table)
    SQL_FORNECEDOR_ARTIGO = (
        "SELECT fi.ref, fo.nome AS fornecedor, fo.no AS fornecedor_no,"
        " COUNT(*) AS n_compras"
        " FROM fi"
        " INNER JOIN ft ON ft.ftstamp = fi.ftstamp"
        " INNER JOIN fo ON fo.no = ft.no"
        " WHERE fi.ref IS NOT NULL AND fi.ref <> ''"
        " AND fi.qtt > 0"
        " GROUP BY fi.ref, fo.nome, fo.no"
    )

    # Run bulk analysis using local DB only (no PHC connection needed here)
    artigos = ArtigoPHC.query.filter(ArtigoPHC.stock_atual >= 0).all()
    erro = None
    try:
        resultados = analisar_todos(cfg_phc, config, artigos)
    except Exception as e:
        import traceback
        erro = str(e)
        logger.error(traceback.format_exc())
        resultados = []

    app.logger.info(f"Total resultados: {len(resultados)}")
    precisam = [r for r in resultados if r.get('quantidade_sugerida', 0) > 0
                and r.get('recomendacao') != 'nao_fazer_stock']
    app.logger.info(f"Precisam encomendar: {len(precisam)}")

    # Fetch supplier per article from PHC - always try regardless of analysis
    fornecedor_por_ref = {}
    print(f"[DEBUG] A buscar fornecedores PHC, precisam={len(precisam)}, cfg_phc={cfg_phc is not None}")
    if cfg_phc:
        try:
            from phc_sync import get_phc_connection
            conn = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            # Simpler query: last purchase invoice per article
            SQL_FORN_SIMPLES = (
                "SELECT RTRIM(fn.ref) AS ref, fo.nome, fo.no"
                " FROM fn"
                " INNER JOIN fo ON fo.fostamp = fn.fostamp"
                " WHERE fn.ref IS NOT NULL AND RTRIM(fn.ref) <> ''"
                " AND fn.qtt > 0"
            )
            cursor.execute(SQL_FORN_SIMPLES)
            contagens = {}
            rows = cursor.fetchall()
            print(f'[DEBUG] Supplier rows fetched: {len(rows)}')
            for ref, forn_nome, forn_no in rows:
                ref = (ref or '').strip()
                if not ref: continue
                if ref not in contagens:
                    contagens[ref] = {}
                key = str(forn_no)
                contagens[ref][key] = contagens[ref].get(key, {'nome': forn_nome, 'no': forn_no, 'n': 0})
                contagens[ref][key]['n'] += 1
            # Pick most frequent supplier per article
            for ref, forns in contagens.items():
                best = max(forns.values(), key=lambda x: x['n'])
                fornecedor_por_ref[ref] = {'nome': best['nome'], 'no': best['no']}
            print(f'[DEBUG] Suppliers identified: {len(fornecedor_por_ref)}')
            # Debug: check if precisam refs match
            if precisam:
                sample = [r['referencia'] for r in precisam[:5]]
                print(f'[DEBUG] Sample precisam refs: {sample}')
                # Check first key in fornecedor_por_ref
                if fornecedor_por_ref:
                    first_key = next(iter(fornecedor_por_ref))
                    print(f'[DEBUG] First key in dict: {repr(first_key)}')
                for ref in sample:
                    forn = fornecedor_por_ref.get(ref)
                    forn2 = fornecedor_por_ref.get(ref.strip())
                    forn3 = fornecedor_por_ref.get(ref.upper())
                    print(f'[DEBUG]   {repr(ref)} -> direct={forn} strip={forn2} upper={forn3}')
            conn.close()
        except Exception as e:
            app.logger.warning(f"PHC supplier fetch error: {e}")

    # Group by supplier
    por_fornecedor = {}
    sem_fornecedor = []
    for r in precisam:
        ref_key = r['referencia'].strip()
        forn = fornecedor_por_ref.get(ref_key)
        if forn:
            key = forn['nome']
            if key not in por_fornecedor:
                por_fornecedor[key] = {'nome': key, 'no': forn['no'], 'artigos': []}
            por_fornecedor[key]['artigos'].append(r)
        else:
            sem_fornecedor.append(r)

    # Sort by supplier name
    fornecedores = sorted(por_fornecedor.values(), key=lambda x: x['nome'])
    if sem_fornecedor:
        fornecedores.append({'nome': 'Sem fornecedor identificado', 'no': None,
                             'artigos': sem_fornecedor})

    return render_template('reposicao_fornecedor.html',
        fornecedores=fornecedores,
        total_artigos=sum(len(f['artigos']) for f in fornecedores),
        config=config, erro=erro if 'erro' in dir() else None)


@app.route('/reposicao/criar-pedido', methods=['POST'])
@login_required
def reposicao_criar_pedido():
    """Create purchase order from replenishment suggestions for one supplier."""
    data         = request.get_json()
    fornecedor   = data.get('fornecedor', 'Fornecedor')
    artigos      = data.get('artigos', [])

    if not artigos:
        return jsonify({'error': 'Sem artigos seleccionados'}), 400

    titulo = f"Reposicao - {fornecedor} - {datetime.now().strftime('%d/%m/%Y')}"
    p = PedidoCompra(
        titulo       = titulo,
        descricao    = f"Pedido gerado automaticamente pela analise de reposicao de stock.",
        prioridade   = 'normal',
        estado       = 'aberto',
        criado_por   = current_user.id,
        data_criacao = datetime.now(),
    )
    db.session.add(p)
    db.session.flush()

    for i, a in enumerate(artigos):
        ref    = a.get('referencia', '')
        artigo = ArtigoPHC.query.filter_by(referencia=ref).first()
        linha  = LinhaPedido(
            pedido_id       = p.id,
            ordem           = i,
            artigo_ref      = ref,
            referencia      = ref,
            designacao      = a.get('designacao', ''),
            unidade         = a.get('unidade', 'un'),
            quantidade      = int(a.get('quantidade_sugerida', 1)),
            stock_atual     = a.get('stock_atual', 0),
            preco_custo_ref = artigo.preco_custo if artigo else 0,
            preco_pcp_ref   = artigo.preco_custo_ponderado if artigo else 0,
            fornecedor_hab  = fornecedor,
            observacoes     = f"EOQ sugerido pela analise de reposicao. Score: {a.get('score','-')}",
        )
        db.session.add(linha)

    db.session.commit()
    return jsonify({'ok': True, 'pedido_id': p.id,
                    'url': url_for('pedido_detalhe', pid=p.id)})


@app.route('/api/reposicao/resultados')
@login_required
def api_reposicao_resultados():
    """Return paginated replenishment results as JSON."""
    from reposicao import CONFIG_PADRAO, analisar_todos
    cfg_phc    = ConfigPHC.query.first()
    cfg_global = ConfigReposicao.query.filter_by(artigo_ref=None).first()
    config = dict(CONFIG_PADRAO)
    if cfg_global:
        config.update({
            'meses_historico':            cfg_global.meses_historico or 60,
            'lead_time_dias':             cfg_global.lead_time_dias or 7,
            'fator_seguranca':            cfg_global.fator_seguranca or 1.5,
            'meses_cobertura':            cfg_global.meses_cobertura or 2,
            'custo_encomenda':            cfg_global.custo_encomenda or 25,
            'taxa_posse_anual':           cfg_global.taxa_posse_anual or 0.20,
            'quantidade_minima_encomenda':cfg_global.quantidade_minima_encomenda or 1,
            'alertar_dias_cobertura':     cfg_global.alertar_dias_cobertura or 30,
            'min_anos_historico':         getattr(cfg_global,'min_anos_historico',2) or 2,
            'min_meses_com_venda':        getattr(cfg_global,'min_meses_com_venda',3) or 3,
            'min_total_vendido':          getattr(cfg_global,'min_total_vendido',3) or 3,
            'ignorar_sem_movimento_anos': getattr(cfg_global,'ignorar_sem_movimento_anos',3) or 3,
            'min_facturas_sugerir':       getattr(cfg_global,'min_facturas_sugerir',8) or 8,
        })

    urgencia  = request.args.get('urgencia', 'necessarios')
    pesquisa  = request.args.get('q', '').strip().lower()
    sort_col  = request.args.get('sort', '')
    sort_dir  = request.args.get('dir', 'asc')
    page      = int(request.args.get('page', 1))
    per_page  = 50

    artigos = ArtigoPHC.query.filter(ArtigoPHC.stock_atual >= 0).all()
    try:
        resultados = analisar_todos(cfg_phc, config, artigos)
    except Exception as e:
        return jsonify({'error': str(e), 'rows': [], 'total': 0})

    # Filter by urgencia
    SEM = {'parado','pouco_historico','irrelevante','sem_dados','nao_recomendado'}
    PRECISAM = {'critico','urgente','necessario'}
    def match_urg(r):
        u = r.get('urgencia','')
        if urgencia == 'todos':       return True
        if urgencia == 'necessarios': return u in PRECISAM
        if urgencia == 'sem_relevancia': return u in SEM
        return u == urgencia

    rows = [r for r in resultados if match_urg(r)]

    # Filter by search
    if pesquisa:
        rows = [r for r in rows if pesquisa in (r.get('referencia','') or '').lower()
                or pesquisa in (r.get('designacao','') or '').lower()]

    total = len(rows)

    # Sort
    if sort_col:
        rev = sort_dir == 'desc'
        key_map = {
            'referencia':   lambda r: r.get('referencia','') or '',
            'designacao':   lambda r: r.get('designacao','') or '',
            'stock':        lambda r: float(r.get('stock_atual',0) or 0),
            'media_ano':    lambda r: float(r.get('consumo_medio_mensal',0) or 0)*12,
            'score':        lambda r: float(r.get('score',0) or 0),
            'dias_cob':     lambda r: float(r.get('dias_cobertura_atual',0) or 0),
            'qtd':          lambda r: float(r.get('quantidade_sugerida',0) or 0),
        }
        fn = key_map.get(sort_col)
        if fn:
            rows.sort(key=fn, reverse=rev)

    # Paginate
    start = (page-1) * per_page
    rows_page = rows[start:start+per_page]

    return jsonify({
        'rows': rows_page,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': max(1, (total + per_page - 1) // per_page),
    })


@app.route('/api/clientes')
@login_required
def api_clientes():
    q = request.args.get('q','').strip()
    if not q or len(q) < 2:
        return jsonify([])
    # Try local Cliente table first
    try:
        clientes = Cliente.query.filter(Cliente.nome.ilike(f'%{q}%')).limit(10).all()
        if clientes:
            return jsonify([{'no': c.no if hasattr(c,'no') else c.id, 'nome': c.nome} for c in clientes])
    except Exception:
        pass
    # Query PHC directly
    try:
        cfg_phc = ConfigPHC.query.first()
        if cfg_phc:
            from phc_sync import get_phc_connection
            conn = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT no, nome FROM cl WHERE nome LIKE ? AND ISNULL(inactivo,0)=0 ORDER BY nome",
                (f'%{q}%',)
            )
            rows = [{'no': r[0], 'nome': (r[1] or '').strip()} for r in cursor.fetchmany(10)]
            conn.close()
            return jsonify(rows)
    except Exception as e:
        app.logger.warning(f"api_clientes PHC error: {e}")
    return jsonify([])

@app.route('/roadmap')
@login_required
def roadmap():
    return render_template('roadmap.html')


class ChangelogEntry(db.Model):
    __tablename__ = 'changelog_entry'
    id          = db.Column(db.Integer, primary_key=True)
    versao      = db.Column(db.String(20), nullable=False)
    descricao   = db.Column(db.Text, default='')
    tipo        = db.Column(db.String(20), default='feat')  # feat/fix/chore
    commit_msg  = db.Column(db.Text, default='')
    criado_em   = db.Column(db.DateTime, default=datetime.now)


class Equipamento(db.Model):
    __tablename__ = 'equipamento'
    id              = db.Column(db.Integer, primary_key=True)
    # Cliente / Embarcacao
    cliente_nome    = db.Column(db.String(200))
    embarcacao      = db.Column(db.String(200))
    # Motor
    motor_modelo    = db.Column(db.String(200))
    motor_potencia  = db.Column(db.String(50))
    serial_number   = db.Column(db.String(100), index=True)
    base_code       = db.Column(db.String(100))
    manufactured_date = db.Column(db.String(50))
    # Caixa Redutora
    caixa_modelo    = db.Column(db.String(200))
    caixa_ratio     = db.Column(db.String(50))
    caixa_serial    = db.Column(db.String(100))
    # Legacy / outros
    catalogo           = db.Column(db.String(100))
    material           = db.Column(db.String(200))
    manufacturing_date = db.Column(db.String(50))
    base_engine_pt     = db.Column(db.String(300))
    base_engine_eng    = db.Column(db.String(300))
    fuel_system_pt     = db.Column(db.String(300))
    fuel_system_eng    = db.Column(db.String(300))
    tipo_motor      = db.Column(db.String(20), default='principal')
    ativo           = db.Column(db.Boolean, default=True)  # principal / auxiliar
    notas           = db.Column(db.Text, default='')
    criado_em       = db.Column(db.DateTime, default=datetime.now)
    opcoes          = db.relationship('EquipamentoOpcao', backref='equipamento', lazy=True, cascade='all, delete-orphan')
    consumiveis     = db.relationship('EquipamentoConsumivel', backref='equipamento', lazy=True, cascade='all, delete-orphan')
    documentos      = db.relationship('EquipamentoDocumento', backref='equipamento', lazy=True, cascade='all, delete-orphan')
    motores_aux     = db.relationship('EquipamentoMotorAux', backref='equipamento', lazy=True, cascade='all, delete-orphan', order_by='EquipamentoMotorAux.numero')

class EquipamentoConsumivel(db.Model):
    __tablename__ = 'equipamento_consumivel'
    id              = db.Column(db.Integer, primary_key=True)
    equipamento_id  = db.Column(db.Integer, db.ForeignKey('equipamento.id'), nullable=False)
    ref             = db.Column(db.String(50))
    designacao      = db.Column(db.String(300))
    unidade         = db.Column(db.String(20))
    quantidade      = db.Column(db.Float, default=1)
    notas           = db.Column(db.String(300))
    ordem           = db.Column(db.Integer, default=0)


# ── PERFIS E PERMISSÕES ──────────────────────────────────────────────────────

MENUS_DISPONIVEIS = [
    ('dashboard',          '🏠 Dashboard'),
    ('pedidos',            '📋 Pedidos de Compra'),
    ('reposicao',          '📦 Reposição'),
    ('inventario',         '📊 Inventário'),
    ('clientes',           '👥 Clientes'),
    ('tecnico',            '🔧 Técnico'),
    ('biblioteca_modelos', '📚 Biblioteca PDF'),
    ('funcionarios',       '👤 Funcionários'),
    ('salarios',           '💶 Salários'),
    ('entradas',           '📥 Entradas'),
    ('partilha',           '📁 Partilha'),
    ('conectividade',      '🌐 Conectividade'),
    ('roadmap',            '🗺️ Roadmap'),
    ('changelog',          '📝 Changelog'),
    ('admin_config',       '⚙️ Configurações'),
    ('admin_utilizadores', '👥 Utilizadores'),
]

# ── MÓDULO ENTRADAS ───────────────────────────────────────────────────────────

ENTRADAS_STATUS = [
    ('rececionado',         '📥 Rececionado'),
    ('orcamentado',         '📋 Orçamentado'),
    ('material_pedido',     '📦 Material Pedido'),
    ('em_reparacao',        '🔧 Em Reparação'),
    ('faturado',            '🧾 Faturado'),
    ('orcamentado_estadia', '⏳ Orçamentado – Em Estadia'),
    ('concluido_estadia',   '🏁 Concluído – Em Estadia'),
]
ENTRADAS_STATUS_DICT = dict(ENTRADAS_STATUS)

# States that trigger day counting and auto-escalation
ESTADIA_RULES = {
    'orcamentado':  {'dias': 10, 'escalate': 'orcamentado_estadia'},
    'faturado':     {'dias': 5,  'escalate': 'concluido_estadia'},
}

def _dias_uteis(data_inicio, data_fim):
    """Count working days between two dates (Mon-Fri)."""
    from datetime import date, timedelta
    count = 0
    cur = data_inicio
    while cur < data_fim:
        cur += timedelta(days=1)
        if cur.weekday() < 5:  # Mon=0 ... Fri=4
            count += 1
    return count

def _verificar_estadias():
    """Check all entries and escalate status if working days exceeded."""
    from datetime import date
    changed = 0
    for e in EntradaEquipamento.query.all():
        rule = ESTADIA_RULES.get(e.status)
        if not rule:
            continue
        # Use real date if set, otherwise registration date
        ref_date = e.data_status_real or (e.data_status.date() if e.data_status else None)
        if not ref_date:
            continue
        dias = _dias_uteis(ref_date, date.today())
        if dias >= rule['dias']:
            status_ant = e.status
            e.status = rule['escalate']
            e.data_status = datetime.now()
            hist = EntradaHistorico(
                entrada_id=e.id, status_ant=status_ant,
                status_novo=e.status, user_nome='Sistema',
                notas=f'Automático: {dias} dias úteis atingidos',
                criado_em=datetime.now()
            )
            db.session.add(hist)
            changed += 1
    if changed:
        db.session.commit()
    return changed

@app.route('/entradas')
@login_required
def entradas():
    _verificar_estadias()
    status_f = request.args.get('status', '')
    q = EntradaEquipamento.query
    if status_f:
        q = q.filter_by(status=status_f)
    entradas_list = q.order_by(EntradaEquipamento.numero.desc()).all()
    from datetime import date
    # Compute dias for each entry
    for e in entradas_list:
        rule = ESTADIA_RULES.get(e.status)
        if rule:
            ref = e.data_status_real or (e.data_status.date() if e.data_status else None)
            if ref:
                e._dias_contagem = _dias_uteis(ref, date.today())
                e._dias_limite = rule['dias']
            else:
                e._dias_contagem = None
                e._dias_limite = None
        else:
            e._dias_contagem = None
            e._dias_limite = None
    em_estadia = sum(1 for e in entradas_list if e.status in ('orcamentado_estadia','concluido_estadia'))
    return render_template('entradas.html',
        entradas=entradas_list, status_list=ENTRADAS_STATUS,
        status_filtro=status_f, em_estadia=em_estadia)

@app.route('/entradas/nova', methods=['GET','POST'])
@login_required
def entrada_nova():
    if request.method == 'POST':
        from datetime import date
        # Auto increment number
        last = db.session.query(db.func.max(EntradaEquipamento.numero)).scalar() or 0
        e = EntradaEquipamento(
            numero=last+1,
            data_rececao=datetime.strptime(request.form.get('data_rececao', datetime.now().strftime('%Y-%m-%d')), '%Y-%m-%d').date(),
            cliente_nome=request.form.get('cliente_nome','').strip(),
            marca=request.form.get('marca','').strip(),
            modelo=request.form.get('modelo','').strip(),
            num_serie=request.form.get('num_serie','').strip(),
            observacoes=request.form.get('observacoes','').strip(),
            status='rececionado',
            data_status=datetime.now(),
            criado_por=current_user.id,
            criado_em=datetime.now(),
            atualizado_em=datetime.now(),
        )
        db.session.add(e)
        db.session.flush()
        db.session.add(EntradaHistorico(
            entrada_id=e.id, status_ant=None, status_novo='rececionado',
            user_id=current_user.id, user_nome=current_user.nome,
            notas='Entrada criada', criado_em=datetime.now()
        ))
        db.session.commit()
        flash(f'Entrada #{e.numero} criada com sucesso!', 'success')
        return redirect(url_for('entrada_detalhe', eid=e.id))
    from datetime import date
    return render_template('entrada_form.html', entrada=None,
        hoje=date.today().strftime('%Y-%m-%d'))

@app.route('/entradas/<int:eid>')
@login_required
def entrada_detalhe(eid):
    e = EntradaEquipamento.query.get_or_404(eid)
    from datetime import date
    rule = ESTADIA_RULES.get(e.status)
    if rule:
        ref = e.data_status_real or (e.data_status.date() if e.data_status else None)
        dias_contagem = _dias_uteis(ref, date.today()) if ref else None
    else:
        dias_contagem = None
    docs = EntradaDocumento.query.filter_by(entrada_id=eid).order_by(EntradaDocumento.criado_em.desc()).all()
    return render_template('entrada_detalhe.html', e=e,
        status_list=ENTRADAS_STATUS, dias_contagem=dias_contagem,
        status_dict=ENTRADAS_STATUS_DICT, docs=docs)

@app.route('/entradas/<int:eid>/editar', methods=['GET','POST'])
@login_required
def entrada_editar(eid):
    e = EntradaEquipamento.query.get_or_404(eid)
    if request.method == 'POST':
        e.data_rececao  = datetime.strptime(request.form['data_rececao'], '%Y-%m-%d').date()
        e.cliente_nome  = request.form.get('cliente_nome','').strip()
        e.marca         = request.form.get('marca','').strip()
        e.modelo        = request.form.get('modelo','').strip()
        e.num_serie     = request.form.get('num_serie','').strip()
        e.observacoes   = request.form.get('observacoes','').strip()
        e.atualizado_em = datetime.now()
        db.session.commit()
        flash('Entrada actualizada.', 'success')
        return redirect(url_for('entrada_detalhe', eid=eid))
    return render_template('entrada_form.html', entrada=e,
        hoje=e.data_rececao.strftime('%Y-%m-%d'))

@app.route('/entradas/<int:eid>/status', methods=['POST'])
@login_required
def entrada_status(eid):
    e = EntradaEquipamento.query.get_or_404(eid)
    data = request.get_json() or {}
    novo = data.get('status')
    notas = data.get('notas','')
    data_real_str = data.get('data_real','')
    if novo not in ENTRADAS_STATUS_DICT:
        return jsonify({'ok': False, 'error': 'Status inválido'})
    # Parse real date
    from datetime import date as date_type
    data_real = None
    if data_real_str:
        try:
            data_real = datetime.strptime(data_real_str, '%Y-%m-%d').date()
        except: pass
    if not data_real:
        data_real = date_type.today()
    ant = e.status
    e.status = novo
    e.data_status = datetime.now()
    e.data_status_real = data_real
    e.atualizado_em = datetime.now()
    db.session.add(EntradaHistorico(
        entrada_id=eid, status_ant=ant, status_novo=novo,
        user_id=current_user.id, user_nome=current_user.nome,
        notas=notas, data_real=data_real, criado_em=datetime.now()
    ))
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/entradas/<int:eid>/pdf')
@login_required
def entrada_pdf(eid):
    e = EntradaEquipamento.query.get_or_404(eid)
    cfg = ConfigGeral.query.first()
    empresa_nome = cfg.empresa_nome if cfg else 'NavTech'
    html = render_template('entrada_pdf.html', e=e, cfg=cfg, empresa_nome=empresa_nome,
        upload_url=request.host_url.rstrip('/') + '/uploads',
        status_dict=ENTRADAS_STATUS_DICT)
    # Try wkhtmltopdf
    for wk_path in [r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
                    r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe']:
        if os.path.exists(wk_path):
            try:
                import pdfkit
                pdf_bytes = pdfkit.from_string(html, False,
                    options={'page-size':'A4','margin-top':'12mm','margin-bottom':'12mm',
                             'margin-left':'12mm','margin-right':'12mm','encoding':'UTF-8','quiet':''},
                    configuration=pdfkit.configuration(wkhtmltopdf=wk_path))
                from flask import Response
                return Response(pdf_bytes, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="Entrada_{e.numero}.pdf"'})
            except: pass
    # Fallback: browser print
    from flask import make_response
    resp = make_response(html)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route('/entradas/<int:eid>/eliminar', methods=['POST'])
@login_required
def entrada_eliminar(eid):
    e = EntradaEquipamento.query.get_or_404(eid)
    if not current_user.is_admin and e.criado_por != current_user.id:
        return jsonify({'ok': False, 'error': 'Sem permissão'})
    # Delete history first
    EntradaHistorico.query.filter_by(entrada_id=eid).delete()
    db.session.delete(e)
    db.session.commit()
    flash(f'Entrada #{e.numero:04d} eliminada.', 'success')
    return jsonify({'ok': True})


@app.route('/entradas/<int:eid>/data-orcamento', methods=['POST'])
@login_required
def entrada_data_orcamento(eid):
    e = EntradaEquipamento.query.get_or_404(eid)
    data = request.get_json() or {}
    ds = data.get('data_orcamento','')
    try:
        e.data_orcamento = datetime.strptime(ds, '%Y-%m-%d').date() if ds else None
        # If status is orcamentado, also update data_status_real for day counting
        if e.status == 'orcamentado' and e.data_orcamento:
            e.data_status_real = e.data_orcamento
        e.atualizado_em = datetime.now()
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)})


@app.route('/api/entradas/estadia-count')
@login_required
def api_entradas_estadia_count():
    _verificar_estadias()
    count = EntradaEquipamento.query.filter(
        EntradaEquipamento.status.in_(['orcamentado_estadia','concluido_estadia'])
    ).count()
    return jsonify({'count': count})


# ── MÓDULO PARTILHA ───────────────────────────────────────────────────────────

UPLOAD_PARTILHA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'partilha')
os.makedirs(UPLOAD_PARTILHA, exist_ok=True)
PARTILHA_MAX_GB = 5
PARTILHA_EXTENSOES_PREVIEW = {'.pdf','.png','.jpg','.jpeg','.gif','.webp','.svg','.txt','.mp4','.mp3'}

def _tamanho_total_partilha():
    from sqlalchemy import func
    r = db.session.query(func.sum(PartilhaFicheiro.tamanho)).scalar()
    return r or 0

@app.route('/partilha')
@login_required
def partilha():
    if current_user.is_admin:
        ficheiros = PartilhaFicheiro.query.order_by(PartilhaFicheiro.criado_em.desc()).all()
    else:
        ficheiros = PartilhaFicheiro.query.filter(
            db.or_(
                PartilhaFicheiro.visibilidade == 'todos',
                PartilhaFicheiro.criado_por == current_user.id,
                PartilhaFicheiro.destinatario_id == current_user.id
            )
        ).order_by(PartilhaFicheiro.criado_em.desc()).all()
    utilizadores = User.query.order_by(User.nome).all()
    total_bytes = _tamanho_total_partilha()
    total_gb = total_bytes / (1024**3)
    return render_template('partilha.html',
        ficheiros=ficheiros, utilizadores=utilizadores,
        total_gb=total_gb, max_gb=PARTILHA_MAX_GB)

@app.route('/partilha/upload', methods=['POST'])
@login_required
def partilha_upload():
    if _tamanho_total_partilha() >= PARTILHA_MAX_GB * 1024**3:
        return jsonify({'ok': False, 'error': 'Limite de 5GB atingido'})
    f = request.files.get('ficheiro')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'Sem ficheiro'})
    import uuid, mimetypes
    ext = os.path.splitext(f.filename)[1].lower()
    nome_unico = str(uuid.uuid4()) + ext
    fpath = os.path.join(UPLOAD_PARTILHA, nome_unico)
    f.save(fpath)
    tamanho = os.path.getsize(fpath)
    mime = mimetypes.guess_type(f.filename)[0] or 'application/octet-stream'
    visib = request.form.get('visibilidade', 'todos')
    dest_id = request.form.get('destinatario_id') or None
    if dest_id: dest_id = int(dest_id)
    pf = PartilhaFicheiro(
        nome=nome_unico, nome_original=f.filename,
        descricao=request.form.get('descricao','').strip(),
        tamanho=tamanho, mime=mime, path=fpath,
        criado_por=current_user.id,
        visibilidade=visib, destinatario_id=dest_id,
        criado_em=datetime.now()
    )
    db.session.add(pf); db.session.commit()
    return jsonify({'ok': True, 'id': pf.id})

@app.route('/partilha/<int:fid>/download')
@login_required
def partilha_download(fid):
    pf = PartilhaFicheiro.query.get_or_404(fid)
    # Check access
    if not current_user.is_admin:
        if pf.visibilidade != 'todos' and pf.criado_por != current_user.id and pf.destinatario_id != current_user.id:
            return 'Sem acesso', 403
    return send_from_directory(UPLOAD_PARTILHA, pf.nome, as_attachment=True, download_name=pf.nome_original)

@app.route('/partilha/<int:fid>/preview')
@login_required
def partilha_preview(fid):
    pf = PartilhaFicheiro.query.get_or_404(fid)
    if not current_user.is_admin:
        if pf.visibilidade != 'todos' and pf.criado_por != current_user.id and pf.destinatario_id != current_user.id:
            return 'Sem acesso', 403
    ext = os.path.splitext(pf.nome_original)[1].lower()
    if ext not in PARTILHA_EXTENSOES_PREVIEW:
        return redirect(url_for('partilha_download', fid=fid))
    return send_from_directory(UPLOAD_PARTILHA, pf.nome, as_attachment=False)

@app.route('/partilha/<int:fid>/apagar', methods=['POST'])
@login_required
def partilha_apagar(fid):
    pf = PartilhaFicheiro.query.get_or_404(fid)
    if not current_user.is_admin and pf.criado_por != current_user.id:
        return jsonify({'ok': False, 'error': 'Sem permissão'})
    try: os.remove(pf.path)
    except: pass
    db.session.delete(pf); db.session.commit()
    return jsonify({'ok': True})


# ── MÓDULO FUNCIONÁRIOS ───────────────────────────────────────────────────────

UPLOAD_RH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'rh')
os.makedirs(UPLOAD_RH, exist_ok=True)

class Funcionario(db.Model):
    __tablename__ = 'funcionario'
    id                  = db.Column(db.Integer, primary_key=True)
    numero              = db.Column(db.String(20), unique=True, nullable=False)
    nome                = db.Column(db.String(200), nullable=False)
    categoria           = db.Column(db.String(100))
    ativo               = db.Column(db.Boolean, default=True)
    # Identificação
    data_admissao       = db.Column(db.Date)
    data_nascimento     = db.Column(db.Date)
    num_cc              = db.Column(db.String(50))
    nif                 = db.Column(db.String(20))
    num_passaporte      = db.Column(db.String(50))
    filiacao_pai        = db.Column(db.String(200))
    filiacao_mae        = db.Column(db.String(200))
    situacao_militar    = db.Column(db.String(100))
    estado_civil        = db.Column(db.String(50))
    conjuge             = db.Column(db.String(200))
    titulares_rendimento= db.Column(db.Integer, default=1)
    num_dependentes     = db.Column(db.Integer, default=0)
    natural_freguesia   = db.Column(db.String(100))
    natural_concelho    = db.Column(db.String(100))
    socio_numero        = db.Column(db.String(50))
    sindicato           = db.Column(db.String(100))
    num_seg_social      = db.Column(db.String(30))
    carta_conducao      = db.Column(db.Boolean, default=False)
    # Contacto
    morada              = db.Column(db.Text)
    telemovel           = db.Column(db.String(30))
    email               = db.Column(db.String(200))
    contacto_emergencia = db.Column(db.String(200))
    nome_emergencia     = db.Column(db.String(200))
    # Financeiro
    iban                = db.Column(db.String(50))
    seguro_companhia    = db.Column(db.String(200))
    seguro_apolice      = db.Column(db.String(100))
    # Misc
    agregado_familiar   = db.Column(db.Integer, default=0)
    notas               = db.Column(db.Text)
    obs                 = db.Column(db.Text)
    criado_em           = db.Column(db.DateTime, default=datetime.now)
    atualizado_em       = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    documentos          = db.relationship('FuncionarioDocumento', backref='funcionario', lazy=True, cascade='all, delete-orphan')
    formacoes           = db.relationship('FuncionarioFormacao', backref='funcionario', lazy=True, cascade='all, delete-orphan')
    situacoes_prof      = db.relationship('FuncionarioSituacaoProf', backref='funcionario', lazy=True, cascade='all, delete-orphan', order_by='FuncionarioSituacaoProf.data.desc()')
    faltas              = db.relationship('FuncionarioFalta', backref='funcionario', lazy=True, cascade='all, delete-orphan')

    @property
    def idade(self):
        if not self.data_nascimento: return None
        today = datetime.now().date()
        d = self.data_nascimento
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))

class FuncionarioSituacaoProf(db.Model):
    __tablename__ = 'funcionario_situacao_prof'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False)
    data            = db.Column(db.Date, nullable=False)
    categoria_prof  = db.Column(db.String(200))
    vencimento      = db.Column(db.Numeric(10,2))
    refeicao        = db.Column(db.Numeric(10,2))
    premios_outros  = db.Column(db.Numeric(10,2))
    notas           = db.Column(db.Text)
    criado_em       = db.Column(db.DateTime, default=datetime.now)

class FuncionarioFalta(db.Model):
    __tablename__ = 'funcionario_falta'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False)
    ano             = db.Column(db.Integer, nullable=False)
    mes             = db.Column(db.Integer, nullable=False)  # 1-12
    dias_falta      = db.Column(db.Numeric(5,1), default=0)
    horas_falta     = db.Column(db.Numeric(5,1), default=0)
    tipo            = db.Column(db.String(50), default='injustificada')  # justificada/injustificada/baixa/ferias
    notas           = db.Column(db.Text)
    criado_em       = db.Column(db.DateTime, default=datetime.now)

class FuncionarioDocumento(db.Model):
    __tablename__ = 'funcionario_documento'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False)
    tipo            = db.Column(db.String(100), nullable=False)  # cc, passaporte, morada, higiene, aptidao, outro
    titulo          = db.Column(db.String(300), nullable=False)
    pdf_filename    = db.Column(db.String(500))
    pdf_path        = db.Column(db.String(1000))
    criado_em       = db.Column(db.DateTime, default=datetime.now)

class FuncionarioFormacao(db.Model):
    __tablename__ = 'funcionario_formacao'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False)
    titulo          = db.Column(db.String(300), nullable=False)
    entidade        = db.Column(db.String(200))
    data_inicio     = db.Column(db.Date)
    data_fim        = db.Column(db.Date)
    horas           = db.Column(db.Integer)
    pdf_filename    = db.Column(db.String(500))
    pdf_path        = db.Column(db.String(1000))
    criado_em       = db.Column(db.DateTime, default=datetime.now)


# ── MÓDULO SALÁRIOS ───────────────────────────────────────────────────────────

UPLOAD_SALARIOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'salarios')
os.makedirs(UPLOAD_SALARIOS, exist_ok=True)

class TabelaIRS(db.Model):
    __tablename__ = 'tabela_irs'
    id          = db.Column(db.Integer, primary_key=True)
    ano         = db.Column(db.Integer, nullable=False)
    descricao   = db.Column(db.String(200))
    pdf_filename= db.Column(db.String(500))
    pdf_path    = db.Column(db.String(1000))
    dados_json  = db.Column(db.Text, default='{}')  # parsed IRS brackets
    criado_em   = db.Column(db.DateTime, default=datetime.now)

class DocContabilistico(db.Model):
    __tablename__ = 'doc_contabilistico'
    id          = db.Column(db.Integer, primary_key=True)
    titulo      = db.Column(db.String(300), nullable=False)
    tipo        = db.Column(db.String(100))  # tabela_irs, outro
    ano         = db.Column(db.Integer)
    pdf_filename= db.Column(db.String(500))
    pdf_path    = db.Column(db.String(1000))
    criado_em   = db.Column(db.DateTime, default=datetime.now)

class ReciboSalario(db.Model):
    __tablename__ = 'recibo_salario'
    id              = db.Column(db.Integer, primary_key=True)
    funcionario_id  = db.Column(db.Integer, db.ForeignKey('funcionario.id'), nullable=False)
    ano             = db.Column(db.Integer, nullable=False)
    mes             = db.Column(db.Integer, nullable=False)   # 1-12, 13=ferias, 14=natal, 15+=extra
    mes_label       = db.Column(db.String(50))                # "Janeiro", "Subsídio Férias", etc.
    estado          = db.Column(db.String(20), default='rascunho')  # rascunho/processado/pago
    # Valores base
    vencimento_base     = db.Column(db.Numeric(10,2), default=0)
    vencimento_base_rht = db.Column(db.Numeric(10,4), default=0)   # F9
    vencimento_base_g   = db.Column(db.Numeric(10,2), default=0)   # G9 BASE
    subsidio_refeicao   = db.Column(db.Numeric(10,2), default=0)
    sub_refeicao_dias   = db.Column(db.Numeric(5,1), default=0)    # D14
    sub_refeicao_vdia   = db.Column(db.Numeric(8,4), default=0)    # F14
    horas_extra         = db.Column(db.Numeric(10,2), default=0)   # E13 horas
    horas_extra_rht     = db.Column(db.Numeric(10,4), default=0)   # F13 RHT
    premios             = db.Column(db.Numeric(10,2), default=0)   # H10
    outros_abonos       = db.Column(db.Numeric(10,2), default=0)
    faltas_dias         = db.Column(db.Numeric(5,1), default=0)    # D11
    faltas_horas        = db.Column(db.Numeric(5,1), default=0)    # E12
    # Deduções
    irs_retencao        = db.Column(db.Numeric(10,2), default=0)   # H19
    irs_taxa            = db.Column(db.Numeric(8,6), default=0)    # B19
    irs_parcela_abater  = db.Column(db.Numeric(10,2), default=0)  # C19
    irs_taxa_efetiva    = db.Column(db.Numeric(8,6), default=0)   # D19
    irs_base            = db.Column(db.Numeric(10,2), default=0)   # E19
    seg_social_func     = db.Column(db.Numeric(10,2), default=0)   # H18 11%
    seg_social_taxa     = db.Column(db.Numeric(8,4), default=0)    # D18
    seg_social_base     = db.Column(db.Numeric(10,2), default=0)   # E18
    seg_social_emp      = db.Column(db.Numeric(10,2), default=0)   # 23.75%
    outros_descontos    = db.Column(db.Numeric(10,2), default=0)
    faltas_valor        = db.Column(db.Numeric(10,2), default=0)
    # Totais calculados
    total_abonos    = db.Column(db.Numeric(10,2), default=0)
    total_descontos = db.Column(db.Numeric(10,2), default=0)
    liquido         = db.Column(db.Numeric(10,2), default=0)
    # Extra info
    notas           = db.Column(db.Text)
    dados_json      = db.Column(db.Text, default='{}')  # extra fields
    pdf_filename    = db.Column(db.String(500))
    pdf_path        = db.Column(db.String(1000))
    criado_em       = db.Column(db.DateTime, default=datetime.now)
    atualizado_em   = db.Column(db.DateTime, default=datetime.now)

    funcionario     = db.relationship('Funcionario', backref='recibos')

MESES_LABELS = {
    1:'Janeiro', 2:'Fevereiro', 3:'Março', 4:'Abril',
    5:'Maio', 6:'Junho', 7:'Julho', 8:'Agosto',
    9:'Setembro', 10:'Outubro', 11:'Novembro', 12:'Dezembro',
    13:'Subsídio de Férias', 14:'Subsídio de Natal'
}


class LinhaPedidoHistorico(db.Model):
    __tablename__ = 'linha_pedido_historico'
    id          = db.Column(db.Integer, primary_key=True)
    linha_id    = db.Column(db.Integer, db.ForeignKey('linhas_pedido.id'), nullable=False)
    pedido_id   = db.Column(db.Integer, nullable=False)
    status_ant  = db.Column(db.String(30))
    status_novo = db.Column(db.String(30), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'))
    user_nome   = db.Column(db.String(120))
    data        = db.Column(db.DateTime, default=datetime.now)
    notas       = db.Column(db.String(300))


class PartilhaFicheiro(db.Model):
    __tablename__ = 'partilha_ficheiros'
    id            = db.Column(db.Integer, primary_key=True)
    nome          = db.Column(db.String(255), nullable=False)
    nome_original = db.Column(db.String(255), nullable=False)
    descricao     = db.Column(db.String(500), default='')
    tamanho       = db.Column(db.BigInteger, default=0)
    mime          = db.Column(db.String(100), default='')
    path          = db.Column(db.String(500), nullable=False)
    criado_por    = db.Column(db.Integer, db.ForeignKey('users.id'))
    criado_em     = db.Column(db.DateTime, default=datetime.now)
    visibilidade  = db.Column(db.String(20), default='todos')  # 'todos' ou user id
    destinatario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploader      = db.relationship('User', foreign_keys=[criado_por])
    destinatario  = db.relationship('User', foreign_keys=[destinatario_id])


class RegistoPendente(db.Model):
    __tablename__ = 'registo_pendente'
    id            = db.Column(db.Integer, primary_key=True)
    nome          = db.Column(db.String(120), nullable=False)
    username      = db.Column(db.String(80), nullable=False)
    email         = db.Column(db.String(200), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    criado_em     = db.Column(db.DateTime, default=datetime.now)
    estado        = db.Column(db.String(20), default='pendente')  # pendente/aceite/recusado


class Perfil(db.Model):
    __tablename__ = 'perfil'
    id        = db.Column(db.Integer, primary_key=True)
    nome      = db.Column(db.String(100), unique=True, nullable=False)
    descricao = db.Column(db.String(300), default='')
    menus     = db.Column(db.Text, default='')  # JSON list of allowed endpoints
    criado_em = db.Column(db.DateTime, default=datetime.now)

    def get_menus(self):
        try: return json.loads(self.menus) if self.menus else []
        except: return []

    def set_menus(self, lst):
        self.menus = json.dumps(lst)

    def pode_aceder(self, endpoint):
        return endpoint in self.get_menus()


class EquipamentoDocumento(db.Model):
    __tablename__ = 'equipamento_documento'
    id              = db.Column(db.Integer, primary_key=True)
    equipamento_id  = db.Column(db.Integer, db.ForeignKey('equipamento.id'), nullable=False)
    componente      = db.Column(db.String(100), nullable=False)  # 'motor', 'caixa', 'aux_1', etc
    titulo          = db.Column(db.String(300), nullable=False)
    pdf_filename    = db.Column(db.String(500))
    pdf_path        = db.Column(db.String(1000))
    notas           = db.Column(db.Text, default='')
    criado_em       = db.Column(db.DateTime, default=datetime.now)


class EquipamentoMotorAux(db.Model):
    __tablename__ = 'equipamento_motor_aux'
    id              = db.Column(db.Integer, primary_key=True)
    equipamento_id  = db.Column(db.Integer, db.ForeignKey('equipamento.id'), nullable=False)
    numero          = db.Column(db.Integer, default=1)   # Motor Aux 1, 2, 3...
    marca           = db.Column(db.String(100))
    modelo          = db.Column(db.String(200))
    serial_number   = db.Column(db.String(100))
    potencia        = db.Column(db.String(50))
    rpm             = db.Column(db.String(50))
    ano             = db.Column(db.String(20))
    notas           = db.Column(db.Text, default='')
    ordem           = db.Column(db.Integer, default=0)


class ModeloPDF(db.Model):
    """Central library of PDFs shared by component model (caixa TM170, motor D13K, etc.)"""
    __tablename__ = 'modelo_pdf'
    id              = db.Column(db.Integer, primary_key=True)
    tipo_componente = db.Column(db.String(50), nullable=False)  # 'caixa', 'motor', 'aux', 'factory_code'
    modelo_codigo   = db.Column(db.String(100), nullable=False, index=True)  # e.g. 'TM170', '1152'
    titulo          = db.Column(db.String(300), nullable=False)
    pdf_filename    = db.Column(db.String(500))
    pdf_path        = db.Column(db.String(1000))
    thumb_path      = db.Column(db.String(1000))
    criado_em       = db.Column(db.DateTime, default=datetime.now)


class CampoTecnicoModelo(db.Model):
    """Custom technical fields shared by component model (e.g. all MG5085 caixas)"""
    __tablename__ = 'campo_tecnico_modelo'
    id              = db.Column(db.Integer, primary_key=True)
    tipo_componente = db.Column(db.String(50), nullable=False)  # 'caixa', 'motor', 'aux'
    modelo_codigo   = db.Column(db.String(100), nullable=False, index=True)
    titulo          = db.Column(db.String(200), nullable=False)
    valor           = db.Column(db.Text, default='')
    ordem           = db.Column(db.Integer, default=0)
    pdf_filename    = db.Column(db.String(500))
    pdf_path        = db.Column(db.String(1000))
    criado_em       = db.Column(db.DateTime, default=datetime.now)


class FactoryCodePDF(db.Model):
    __tablename__ = 'factory_code_pdf'
    id           = db.Column(db.Integer, primary_key=True)
    factory_code = db.Column(db.String(50), nullable=False, index=True)
    titulo       = db.Column(db.String(300))
    pdf_filename = db.Column(db.String(500))
    pdf_path     = db.Column(db.String(1000))
    criado_em    = db.Column(db.DateTime, default=datetime.now)


class EquipamentoOpcao(db.Model):
    __tablename__ = 'equipamento_opcao'
    id              = db.Column(db.Integer, primary_key=True)
    equipamento_id  = db.Column(db.Integer, db.ForeignKey('equipamento.id'), nullable=False)
    option_name     = db.Column(db.String(200), nullable=False)
    ordered         = db.Column(db.String(200))
    factory         = db.Column(db.String(200))
    distributor     = db.Column(db.String(200))
    pdf_filename    = db.Column(db.String(500))
    pdf_path        = db.Column(db.String(1000))
    ordem           = db.Column(db.Integer, default=0)


class BacklogItem(db.Model):
    __tablename__ = 'backlog_item'
    id         = db.Column(db.Integer, primary_key=True)
    titulo     = db.Column(db.String(200), nullable=False)
    descricao  = db.Column(db.Text, default='')
    tipo       = db.Column(db.String(20), default='medium')  # bug/small/medium/large/epic
    estado     = db.Column(db.String(20), default='pending') # pending/in_progress/done
    prioridade = db.Column(db.Integer, default=10)
    notas      = db.Column(db.Text, default='')
    criado_em  = db.Column(db.DateTime, default=datetime.now)
    atualizado_em = db.Column(db.DateTime, default=datetime.now)


@app.route('/api/backlog', methods=['GET'])
@login_required
def api_backlog_list():
    items = BacklogItem.query.order_by(BacklogItem.prioridade, BacklogItem.id).all()
    return jsonify([{
        'id': i.id, 'titulo': i.titulo, 'descricao': i.descricao,
        'notas': i.notas, 'tipo': i.tipo, 'estado': i.estado, 'prioridade': i.prioridade
    } for i in items])

@app.route('/api/backlog', methods=['POST'])
@login_required
def api_backlog_criar():
    d = request.get_json() or {}
    item = BacklogItem(
        titulo=d.get('titulo','').strip() or 'Sem titulo',
        descricao=d.get('descricao','').strip(),
        notas=d.get('notas','').strip(),
        tipo=d.get('tipo','medium'),
        estado=d.get('estado','pending'),
        prioridade=int(d.get('prioridade',10)),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True, 'id': item.id})

@app.route('/api/backlog/<int:bid>', methods=['PUT'])
@login_required
def api_backlog_atualizar(bid):
    item = BacklogItem.query.get_or_404(bid)
    d = request.get_json() or {}
    if 'titulo'     in d: item.titulo     = d['titulo']
    if 'descricao'  in d: item.descricao  = d['descricao']
    if 'notas'      in d: item.notas      = d['notas']
    if 'tipo'       in d: item.tipo       = d['tipo']
    if 'estado'     in d: item.estado     = d['estado']
    if 'prioridade' in d: item.prioridade = int(d['prioridade'])
    item.atualizado_em = datetime.now()
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/backlog/<int:bid>', methods=['DELETE'])
@login_required
def api_backlog_apagar(bid):
    item = BacklogItem.query.get_or_404(bid)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'ok': True})


def auto_registar_commit(commit_msg, versao=None):
    """Called after git pull to auto-update backlog and changelog."""
    try:
        import re
        from datetime import datetime as dt
        
        # Detect type from conventional commit prefix
        tipo = 'chore'
        if commit_msg.startswith('feat:'): tipo = 'feat'
        elif commit_msg.startswith('fix:'): tipo = 'fix'
        elif commit_msg.startswith('refactor:'): tipo = 'refactor'
        
        # Clean description
        desc = re.sub(r'^(feat|fix|chore|refactor|docs|style|test):\s*', '', commit_msg).strip()
        
        # Auto-version based on date + count
        if not versao:
            today = dt.now().strftime('%Y.%m.%d')
            existing = ChangelogEntry.query.filter(
                ChangelogEntry.versao.like(f'{today}%')
            ).count()
            versao = f'{today}.{existing+1}'
        
        # Add to changelog
        entry = ChangelogEntry(
            versao=versao,
            descricao=desc,
            tipo=tipo,
            commit_msg=commit_msg,
        )
        db.session.add(entry)
        
        # Try to match backlog items and mark done
        if tipo in ('feat', 'fix'):
            desc_lower = desc.lower()
            items = BacklogItem.query.filter(BacklogItem.estado != 'done').all()
            for item in items:
                title_lower = item.titulo.lower()
                # Simple keyword match - if 3+ words from title appear in commit
                words = [w for w in title_lower.split() if len(w) > 4]
                matches = sum(1 for w in words if w in desc_lower)
                if matches >= 2:
                    item.estado = 'done'
                    item.atualizado_em = dt.now()
                    app.logger.info(f"Auto-marked backlog item done: {item.titulo}")
        
        db.session.commit()
        app.logger.info(f"Auto-registered commit: {versao} - {desc}")
        return versao
    except Exception as e:
        app.logger.warning(f"auto_registar_commit error: {e}")
        return None


@app.route('/api/admin/registar-commit', methods=['POST'])
@login_required  
def api_registar_commit():
    """Called by update script after git pull."""
    d = request.get_json() or {}
    commit_msg = d.get('commit_msg', '').strip()
    versao = d.get('versao', '')
    if not commit_msg:
        return jsonify({'error': 'commit_msg required'}), 400
    with app.app_context():
        v = auto_registar_commit(commit_msg, versao or None)
    return jsonify({'ok': True, 'versao': v})


@app.route('/api/fornecedores')
@login_required
def api_fornecedores():
    q = request.args.get('q','').strip()
    if not q or len(q) < 2:
        return jsonify([])
    # Try local FornecedorPHC table first
    try:
        local = FornecedorPHC.query.filter(FornecedorPHC.nome.ilike(f'%{q}%')).limit(10).all()
        if local:
            return jsonify([{'no': f.no, 'nome': f.nome} for f in local])
    except Exception:
        pass
    # Query PHC cl table directly (fornecedores sao clientes com ncont)
    try:
        cfg_phc = ConfigPHC.query.first()
        if cfg_phc:
            from phc_sync import get_phc_connection
            conn = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            # Search in fo (facturas compra) for supplier names
            cursor.execute(
                "SELECT DISTINCT fo.no, fo.nome FROM PHC_Uniao..fo WHERE fo.nome LIKE ? AND fo.nome IS NOT NULL ORDER BY fo.nome",
                (f'%{q}%',)
            )
            rows = [{'no': r[0], 'nome': (r[1] or '').strip()} for r in cursor.fetchmany(10)]
            conn.close()
            if rows:
                return jsonify(rows)
            # Fallback to cl table
            conn = get_phc_connection(cfg_phc)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT no, nome FROM PHC_Uniao..cl WHERE nome LIKE ? AND ISNULL(inactivo,0)=0 ORDER BY nome",
                (f'%{q}%',)
            )
            rows = [{'no': r[0], 'nome': (r[1] or '').strip()} for r in cursor.fetchmany(10)]
            conn.close()
            return jsonify(rows)
    except Exception as e:
        app.logger.warning(f"api_fornecedores PHC error: {e}")
    return jsonify([])

@app.route('/admin/ia', methods=['GET', 'POST'])
@login_required
def admin_ia():
    if not current_user.is_admin:
        flash('Sem permissão.', 'error'); return redirect(url_for('dashboard'))

    cfg = ConfigIA.query.first()
    if not cfg:
        cfg = ConfigIA(); db.session.add(cfg); db.session.commit()

    from ai_provider import RECOMMENDED_MODELS, test_provider

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save':
            cfg.provider     = request.form.get('provider', 'lmstudio')
            cfg.lm_host      = request.form.get('lm_host', 'localhost').strip()
            cfg.lm_port      = int(request.form.get('lm_port', 1234))
            cfg.lm_model     = request.form.get('lm_model', '').strip()
            key = request.form.get('claude_api_key', '').strip()
            if key: cfg.claude_api_key = key
            gkey = request.form.get('gemini_api_key', '').strip()
            if gkey: cfg.gemini_api_key = gkey
            cfg.gemini_model = request.form.get('gemini_model', 'gemini-1.5-flash').strip()
            db.session.commit()
            flash('Configuração de IA guardada.', 'success')

        elif action == 'test':
            ok, msg = test_provider(cfg)
            cfg.teste_ok = ok
            cfg.ultimo_teste = datetime.now()
            db.session.commit()
            flash(msg, 'success' if ok else 'error')

        elif action == 'test_pdf':
            # Quick test with dummy text
            from ai_provider import analyze_pdf
            sample = """Empresa: Test Fornecedor Lda  NIF: 123456789
Orçamento Nº: ORC-2024-001   Data: 15/01/2024
Artigo: Cilindro Hidráulico CH-50   Qtd: 2 un   Preço: 150,00 €   Total: 300,00 €
Subtotal: 300,00 €   IVA 23%: 69,00 €   TOTAL: 369,00 €"""
            dados, erro = analyze_pdf(cfg, sample, "teste.pdf")
            if dados:
                flash(f'✅ Extração OK — Empresa: {dados.get("empresa")} · Total: {dados.get("total")} €', 'success')
            else:
                flash(f'❌ Falha na extração: {erro}', 'error')

        return redirect(url_for('admin_ia'))

    return render_template('admin_ia.html', cfg=cfg,
                           modelos=RECOMMENDED_MODELS.get('lmstudio', []))

def ensure_sqlserver_running():
    """Start SQL Server Express if not running."""
    import subprocess, time, logging
    _log = logging.getLogger(__name__)
    SERVICE = 'MSSQL$SQLEXPRESS'
    try:
        r = subprocess.run(['sc', 'query', SERVICE],
                          capture_output=True, text=True, timeout=5)
        if 'RUNNING' in r.stdout:
            _log.info("✅ SQL Server já está a correr")
            return True
        if 'STOPPED' in r.stdout:
            _log.info("🔄 A iniciar SQL Server Express...")
            start = subprocess.run(['net', 'start', SERVICE],
                                  capture_output=True, text=True, timeout=30)
            if start.returncode == 0:
                time.sleep(3)
                _log.info("✅ SQL Server iniciado com sucesso")
                return True
            else:
                _log.warning(f"⚠️  Não foi possível iniciar SQL Server: {start.stdout}")
                return False
    except Exception as e:
        _log.warning(f"⚠️  Erro ao verificar SQL Server: {e}")
        return False


@app.route('/api/backlog/count')
@login_required
def api_backlog_count():
    try:
        pending = BacklogItem.query.filter(BacklogItem.estado != 'done').count()
        return jsonify({'pending': pending})
    except Exception:
        return jsonify({'pending': 0})


@app.route('/inventario')
@login_required
def inventario():
    return render_template('inventario.html')


@app.route('/api/inventario/kpis')
@login_required
def api_inventario_kpis():
    """Calculate inventory KPIs from PHC data."""
    try:
        cfg_phc = ConfigPHC.query.first()
        if not cfg_phc:
            return jsonify({'error': 'PHC nao configurado'}), 400
        from phc_sync import get_phc_connection
        conn = get_phc_connection(cfg_phc)
        cur = conn.cursor()

        # --- Base stock data ---
        cur.execute("""
            SELECT st.ref, st.design, ISNULL(st.stock,0) AS stock,
                   ISNULL(st.epcusto,0) AS custo, ISNULL(st.epcpond,0) AS custo_pond,
                   ISNULL(st.epv1,0) AS pvp, ISNULL(st.familia,'') AS familia,
                   ISNULL(st.unidade,'un') AS unidade
            FROM st
            WHERE ISNULL(st.inactivo,0)=0 AND st.ref IS NOT NULL AND st.ref <> ''
        """)
        artigos = cur.fetchall()

        # --- Sales last 12 months ---
        cur.execute("""
            SELECT fi.ref, SUM(fi.qtt) AS total_vendido,
                   SUM(fi.qtt * ISNULL(fi.epv,0)) AS total_faturado,
                   COUNT(DISTINCT ft.ftstamp) AS num_facturas,
                   MAX(ft.fdata) AS ultima_venda
            FROM fi
            INNER JOIN ft ON ft.ftstamp = fi.ftstamp
            WHERE ft.tipodoc = 1 AND ft.anulado = 0
              AND ft.fdata >= DATEADD(month, -12, GETDATE())
              AND fi.qtt > 0
            GROUP BY fi.ref
        """)
        vendas = {r[0].strip(): {
            'vendido': float(r[1] or 0),
            'faturado': float(r[2] or 0),
            'facturas': int(r[3] or 0),
            'ultima_venda': r[4].strftime('%Y-%m-%d') if r[4] else None
        } for r in cur.fetchall()}

        # --- Purchases last 12 months ---
        cur.execute("""
            SELECT RTRIM(fn.ref), SUM(fn.qtt) AS total_comprado,
                   0 AS total_compras
            FROM fn
            INNER JOIN fo ON fo.fostamp = fn.fostamp
            WHERE fo.data >= DATEADD(month, -12, GETDATE())
              AND fn.qtt > 0
            GROUP BY RTRIM(fn.ref)
        """)
        compras = {r[0]: {'comprado': float(r[1] or 0), 'valor_compras': float(r[2] or 0)}
                   for r in cur.fetchall()}

        conn.close()

        # --- Calculate metrics per article ---
        items = []
        total_valor_custo = 0
        total_valor_pvp = 0
        total_margem = 0
        sem_movimento = 0
        stock_negativo = 0
        total_artigos = 0

        for r in artigos:
            ref = (r[0] or '').strip()
            design = (r[1] or '').strip()
            stock = float(r[2])
            custo = float(r[3]) or float(r[4])  # epcusto or epcpond
            pvp = float(r[5])
            familia = (r[6] or '').strip()

            v = vendas.get(ref, {})
            c = compras.get(ref, {})

            vendido_12m = v.get('vendido', 0)
            faturado_12m = v.get('faturado', 0)
            ultima_venda = v.get('ultima_venda')

            valor_stock_custo = stock * custo
            valor_stock_pvp = stock * pvp
            margem_pct = ((pvp - custo) / pvp * 100) if pvp > 0 else 0
            margem_valor = (pvp - custo) * vendido_12m if vendido_12m > 0 else 0

            # Days without movement
            dias_sem_venda = None
            if ultima_venda:
                from datetime import datetime
                dias_sem_venda = (datetime.now() - datetime.strptime(ultima_venda, '%Y-%m-%d')).days

            total_valor_custo += max(0, valor_stock_custo)
            total_valor_pvp += max(0, valor_stock_pvp)
            total_margem += margem_valor
            total_artigos += 1

            if stock < 0: stock_negativo += 1
            if not ultima_venda or (dias_sem_venda and dias_sem_venda > 180): sem_movimento += 1

            items.append({
                'ref': ref,
                'design': design,
                'stock': stock,
                'custo': custo,
                'pvp': pvp,
                'familia': familia,
                'valor_custo': valor_stock_custo,
                'valor_pvp': valor_stock_pvp,
                'margem_pct': round(margem_pct, 1),
                'vendido_12m': vendido_12m,
                'faturado_12m': faturado_12m,
                'margem_valor': round(margem_valor, 2),
                'ultima_venda': ultima_venda,
                'dias_sem_venda': dias_sem_venda,
                'num_facturas': v.get('facturas', 0),
            })

        # --- ABC Classification by revenue ---
        items_com_venda = sorted([i for i in items if i['faturado_12m'] > 0],
                                  key=lambda x: x['faturado_12m'], reverse=True)
        total_fat = sum(i['faturado_12m'] for i in items_com_venda)
        acum = 0
        abc_counts = {'A': 0, 'B': 0, 'C': 0}
        for item in items_com_venda:
            acum += item['faturado_12m']
            pct = acum / total_fat if total_fat else 0
            if pct <= 0.7:
                item['abc'] = 'A'
                abc_counts['A'] += 1
            elif pct <= 0.9:
                item['abc'] = 'B'
                abc_counts['B'] += 1
            else:
                item['abc'] = 'C'
                abc_counts['C'] += 1
        for item in items:
            if 'abc' not in item:
                item['abc'] = '-'

        # --- GMROI ---
        gmroi = (total_margem / total_valor_custo * 100) if total_valor_custo > 0 else 0

        # --- Top performers ---
        def rot(x): return (x['stock'] / (x['vendido_12m']/12)) if x['vendido_12m'] > 0 else 0
        top_faturacao = sorted(items, key=lambda x: x['faturado_12m'], reverse=True)[:10]
        top_margem    = sorted([a for a in items if a['margem_valor'] > 0], key=lambda x: x['margem_valor'], reverse=True)[:10]
        sem_vendas    = sorted([a for a in items if a['vendido_12m'] == 0 and a['stock'] > 0], key=lambda x: x['valor_custo'], reverse=True)[:10]
        excesso       = sorted([a for a in items if a['vendido_12m'] > 0 and a['stock'] > 0], key=rot, reverse=True)[:10]

        # --- Alerts ---
        alertas = []
        for i in items:
            if i['stock'] < 0:
                alertas.append({'tipo': 'negativo', 'ref': i['ref'], 'design': i['design'][:50], 'valor': i['stock']})
            elif i['stock'] > 0 and i['dias_sem_venda'] and i['dias_sem_venda'] > 365:
                alertas.append({'tipo': 'obsoleto', 'ref': i['ref'], 'design': i['design'][:50], 'valor': i['dias_sem_venda']})
            elif i['margem_pct'] < 0 and i['vendido_12m'] > 0:
                alertas.append({'tipo': 'margem_neg', 'ref': i['ref'], 'design': i['design'][:50], 'valor': i['margem_pct']})

        # --- Families breakdown ---
        familias = {}
        for i in items:
            f = i['familia'] or 'Sem familia'
            if f not in familias:
                familias[f] = {'artigos': 0, 'valor_custo': 0, 'faturado': 0}
            familias[f]['artigos'] += 1
            familias[f]['valor_custo'] += max(0, i['valor_custo'])
            familias[f]['faturado'] += i['faturado_12m']
        top_familias = sorted(familias.items(), key=lambda x: x[1]['faturado'], reverse=True)[:8]

        return jsonify({
            'kpis': {
                'total_artigos': total_artigos,
                'artigos_com_stock': len([i for i in items if i['stock'] > 0]),
                'artigos_sem_stock': len([i for i in items if i['stock'] <= 0]),
                'stock_negativo': stock_negativo,
                'sem_movimento_180d': sem_movimento,
                'valor_stock_custo': round(total_valor_custo, 2),
                'valor_stock_pvp': round(total_valor_pvp, 2),
                'margem_total': round(total_margem, 2),
                'gmroi': round(gmroi, 1),
                'faturacao_12m': round(sum(i['faturado_12m'] for i in items), 2),
            },
            'abc': abc_counts,
            'alertas': alertas[:20],
            'top_faturacao': top_faturacao,
            'top_margem': top_margem,
            'sem_vendas': sem_vendas,
            'familias': [{'familia': k, **v} for k, v in top_familias],
        })

    except Exception as e:
        app.logger.error(f"inventario KPIs error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/tecnico/<int:eid>/consumiveis')
@login_required
def tecnico_consumiveis(eid):
    e = Equipamento.query.get_or_404(eid)
    consumiveis = EquipamentoConsumivel.query.filter_by(equipamento_id=eid).order_by(EquipamentoConsumivel.ordem).all()
    q = request.args.get('q', '').strip()
    artigos_sugeridos = []
    if q and len(q) >= 2:
        artigos_sugeridos = ArtigoPHC.query.filter(
            db.or_(ArtigoPHC.referencia.ilike(f'%{q}%'), ArtigoPHC.designacao.ilike(f'%{q}%'))
        ).limit(10).all()
    return render_template('tecnico_consumiveis.html', equipamento=e, consumiveis=consumiveis,
                           artigos_sugeridos=artigos_sugeridos, q=q)

@app.route('/tecnico/<int:eid>/consumiveis/adicionar', methods=['POST'])
@login_required
def tecnico_consumivel_adicionar(eid):
    Equipamento.query.get_or_404(eid)
    c = EquipamentoConsumivel(
        equipamento_id=eid,
        ref=request.form.get('ref','').strip(),
        designacao=request.form.get('designacao','').strip(),
        unidade=request.form.get('unidade','un').strip(),
        quantidade=float(request.form.get('quantidade', 1) or 1),
        notas=request.form.get('notas','').strip(),
        ordem=EquipamentoConsumivel.query.filter_by(equipamento_id=eid).count(),
    )
    db.session.add(c)
    db.session.commit()
    return redirect(url_for('tecnico_consumiveis', eid=eid))

@app.route('/tecnico/consumivel/<int:cid>/apagar', methods=['POST'])
@login_required
def tecnico_consumivel_apagar(cid):
    c = EquipamentoConsumivel.query.get_or_404(cid)
    eid = c.equipamento_id
    db.session.delete(c)
    db.session.commit()
    return redirect(url_for('tecnico_consumiveis', eid=eid))

@app.route('/tecnico/consumivel/<int:cid>/editar', methods=['POST'])
@login_required
def tecnico_consumivel_editar(cid):
    c = EquipamentoConsumivel.query.get_or_404(cid)
    c.ref        = request.form.get('ref', c.ref)
    c.designacao = request.form.get('designacao', c.designacao)
    c.unidade    = request.form.get('unidade', c.unidade)
    c.quantidade = float(request.form.get('quantidade', c.quantidade) or 1)
    c.notas      = request.form.get('notas', c.notas)
    db.session.commit()
    return redirect(url_for('tecnico_consumiveis', eid=c.equipamento_id))


# ── MÓDULO TÉCNICO — GESTÃO DE EQUIPAMENTOS ────────────────────────────────

UPLOAD_TECNICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'tecnico')

def ensure_upload_dir():
    os.makedirs(UPLOAD_TECNICO, exist_ok=True)

@app.route('/tecnico')
@login_required
def tecnico():
    equipamentos = Equipamento.query.order_by(Equipamento.embarcacao).all()
    return render_template('tecnico.html', equipamentos=equipamentos)

@app.route('/tecnico/novo', methods=['GET', 'POST'])
@login_required
def tecnico_novo():
    if request.method == 'POST':
        e = Equipamento(
            cliente_nome=request.form.get('cliente_nome','').strip(),
            embarcacao=request.form.get('embarcacao','').strip(),
            motor_modelo=request.form.get('motor_modelo','').strip(),
            motor_potencia=request.form.get('motor_potencia','').strip(),
            serial_number=request.form.get('serial_number','').strip(),
            base_code=request.form.get('base_code','').strip(),
            manufactured_date=request.form.get('manufactured_date','').strip(),
            material=request.form.get('material','').strip(),
            caixa_modelo=request.form.get('caixa_modelo','').strip(),
            caixa_ratio=request.form.get('caixa_ratio','').strip(),
            caixa_serial=request.form.get('caixa_serial','').strip(),
            notas=request.form.get('notas','').strip(),
        )
        db.session.add(e)
        db.session.commit()
        return redirect(url_for('tecnico_detalhe', eid=e.id))
    return render_template('tecnico_form.html', equipamento=None)

@app.route('/tecnico/<int:eid>')
@login_required
def tecnico_detalhe(eid):
    e = Equipamento.query.get_or_404(eid)
    opcoes = EquipamentoOpcao.query.filter_by(equipamento_id=eid).order_by(EquipamentoOpcao.ordem).all()
    motores_aux = EquipamentoMotorAux.query.filter_by(equipamento_id=eid).order_by(EquipamentoMotorAux.numero).all()
    documentos = EquipamentoDocumento.query.filter_by(equipamento_id=eid).order_by(EquipamentoDocumento.componente, EquipamentoDocumento.criado_em).all()
    return render_template('tecnico_detalhe.html', equipamento=e, opcoes=opcoes, motores_aux=motores_aux, documentos=documentos)

@app.route('/tecnico/<int:eid>/editar', methods=['GET', 'POST'])
@login_required
def tecnico_editar(eid):
    e = Equipamento.query.get_or_404(eid)
    if request.method == 'POST':
        e.cliente_nome      = request.form.get('cliente_nome','').strip()
        e.embarcacao        = request.form.get('embarcacao','').strip()
        e.motor_modelo      = request.form.get('motor_modelo','').strip()
        e.motor_potencia    = request.form.get('motor_potencia','').strip()
        e.serial_number     = request.form.get('serial_number','').strip()
        e.base_code         = request.form.get('base_code','').strip()
        e.manufactured_date = request.form.get('manufactured_date','').strip()
        e.catalogo          = request.form.get('catalogo','').strip()
        e.material          = request.form.get('material','').strip()
        e.caixa_modelo      = request.form.get('caixa_modelo','').strip()
        e.caixa_ratio       = request.form.get('caixa_ratio','').strip()
        e.caixa_serial      = request.form.get('caixa_serial','').strip()
        e.tipo_motor        = request.form.get('tipo_motor','principal')
        e.ativo             = request.form.get('ativo') == '1'
        e.catalogo          = request.form.get('catalogo','').strip()
        e.material          = request.form.get('material','').strip()
        e.manufacturing_date = request.form.get('manufacturing_date','').strip()
        e.base_engine_pt    = request.form.get('base_engine_pt','').strip()
        e.base_engine_eng   = request.form.get('base_engine_eng','').strip()
        e.fuel_system_pt    = request.form.get('fuel_system_pt','').strip()
        e.fuel_system_eng   = request.form.get('fuel_system_eng','').strip()
        e.notas             = request.form.get('notas','').strip()
        db.session.commit()
        return redirect(url_for('tecnico_detalhe', eid=eid))
    return render_template('tecnico_form.html', equipamento=e)

@app.route('/tecnico/<int:eid>/apagar', methods=['POST'])
@login_required
def tecnico_apagar(eid):
    e = Equipamento.query.get_or_404(eid)
    db.session.delete(e)
    db.session.commit()
    return redirect(url_for('tecnico'))

@app.route('/tecnico/<int:eid>/opcao', methods=['POST'])
@login_required
def tecnico_opcao_criar(eid):
    Equipamento.query.get_or_404(eid)
    o = EquipamentoOpcao(
        equipamento_id=eid,
        option_name=request.form.get('option_name','').strip(),
        ordered=request.form.get('ordered','').strip(),
        factory=request.form.get('factory','').strip(),
        distributor=request.form.get('distributor','').strip(),
        ordem=EquipamentoOpcao.query.filter_by(equipamento_id=eid).count(),
    )
    db.session.add(o)
    db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=eid))

@app.route('/tecnico/opcao/<int:oid>/editar', methods=['POST'])
@login_required
def tecnico_opcao_editar(oid):
    o = EquipamentoOpcao.query.get_or_404(oid)
    o.option_name  = request.form.get('option_name', o.option_name)
    o.ordered      = request.form.get('ordered', o.ordered)
    o.factory      = request.form.get('factory', o.factory)
    o.distributor  = request.form.get('distributor', o.distributor)
    db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=o.equipamento_id))

@app.route('/tecnico/opcao/<int:oid>/apagar', methods=['POST'])
@login_required
def tecnico_opcao_apagar(oid):
    o = EquipamentoOpcao.query.get_or_404(oid)
    eid = o.equipamento_id
    db.session.delete(o)
    db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=eid))

@app.route('/tecnico/opcao/<int:oid>/upload', methods=['POST'])
@login_required
def tecnico_opcao_upload(oid):
    o = EquipamentoOpcao.query.get_or_404(oid)
    f = request.files.get('pdf')
    if not f or not f.filename.lower().endswith('.pdf'):
        flash('Ficheiro inválido — apenas PDF.', 'error')
        return redirect(url_for('tecnico_detalhe', eid=o.equipamento_id))
    ensure_upload_dir()
    safe = f"{oid}_{f.filename.replace(' ','_')}"
    path = os.path.join(UPLOAD_TECNICO, safe)
    f.save(path)
    o.pdf_filename = f.filename
    o.pdf_path = safe

    # Determine reference code by priority: distributor > factory > ordered
    dist = (o.distributor or '').strip().replace('*','').strip()
    fac  = (o.factory    or '').strip().replace('*','').strip()
    ord_ = (o.ordered    or '').strip().replace('*','').strip()
    ref_code = dist or fac or ord_
    ref_type = 'distributor' if dist else ('factory' if fac else 'ordered' if ord_ else None)

    # Get catalog of this equipment - REQUIRED for propagation
    eq = Equipamento.query.get(o.equipamento_id)
    catalogo = (eq.catalogo or '').strip().upper() if eq else None

    propagated = 0
    if ref_code and catalogo:
        # Only propagate if equipment has a catalog defined
        eq_ids = [e.id for e in Equipamento.query.filter(
            db.func.upper(Equipamento.catalogo) == catalogo
        ).all()]

        def match_others(col):
            return EquipamentoOpcao.query.filter(
                EquipamentoOpcao.id != oid,
                EquipamentoOpcao.equipamento_id.in_(eq_ids),
                db.func.replace(db.func.replace(col,'*',''),' ','') == ref_code
            ).all()

        if dist:   others = match_others(EquipamentoOpcao.distributor)
        elif fac:  others = match_others(EquipamentoOpcao.factory)
        else:      others = match_others(EquipamentoOpcao.ordered)

        for other in others:
            other.pdf_filename = f.filename
            other.pdf_path = safe
            propagated += 1

    db.session.commit()

    if propagated:
        flash(f'✅ PDF propagado para {propagated} linhas com catálogo={catalogo} e {ref_type}={ref_code}.', 'success')
    elif ref_code and not catalogo:
        flash('PDF associado. ⚠️ Sem catálogo definido — não foi propagado a outras fichas.', 'warning')
    else:
        flash('PDF associado.', 'success')

    return redirect(url_for('tecnico_detalhe', eid=o.equipamento_id))

@app.route('/tecnico/opcao/<int:oid>/pdf')
@login_required
def tecnico_opcao_pdf(oid):
    o = EquipamentoOpcao.query.get_or_404(oid)
    if not o.pdf_path:
        return 'Sem PDF', 404
    return send_from_directory(UPLOAD_TECNICO, o.pdf_path,
                               as_attachment=False, download_name=o.pdf_filename)

@app.route('/tecnico/opcao/<int:oid>/pdf/download')
@login_required
def tecnico_opcao_pdf_download(oid):
    o = EquipamentoOpcao.query.get_or_404(oid)
    if not o.pdf_path:
        return 'Sem PDF', 404
    return send_from_directory(UPLOAD_TECNICO, o.pdf_path,
                               as_attachment=True, download_name=o.pdf_filename)


@app.route('/tecnico/<int:eid>/importar-html', methods=['POST'])
@login_required
def tecnico_importar_html(eid):
    """Parse John Deere JDPS HTML - table#optioninfo."""
    Equipamento.query.get_or_404(eid)
    f = request.files.get('html_file')
    if not f:
        flash('Nenhum ficheiro enviado.', 'error')
        return redirect(url_for('tecnico_detalhe', eid=eid))
    try:
        raw = f.read()
        for enc in ('utf-8', 'latin-1', 'cp1252'):
            try: content = raw.decode(enc); break
            except Exception: content = raw.decode('latin-1', errors='replace')

        from html.parser import HTMLParser

        class JDPSParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows = []
                self.in_table = False
                self.table_depth = 0
                self.in_tr = False
                self.cells = []
                self.in_td = False
                self.cur_attrs = {}
                self.cur_text = ''

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == 'table':
                    if a.get('id') == 'optioninfo':
                        self.in_table = True
                        self.table_depth = 1
                    elif self.in_table:
                        self.table_depth += 1
                if self.in_table and self.table_depth == 1:
                    if tag == 'tr':
                        self.in_tr = True
                        self.cells = []
                    elif tag == 'td' and self.in_tr:
                        self.in_td = True
                        self.cur_attrs = a
                        self.cur_text = ''

            def handle_endtag(self, tag):
                if tag == 'table' and self.in_table:
                    self.table_depth -= 1
                    if self.table_depth == 0:
                        self.in_table = False
                if self.in_table and self.table_depth == 1:
                    if tag == 'td' and self.in_td:
                        self.in_td = False
                        self.cells.append((dict(self.cur_attrs), self.cur_text.strip()))
                    elif tag == 'tr' and self.in_tr:
                        self.in_tr = False
                        self._process_row()

            def handle_data(self, data):
                if self.in_td:
                    self.cur_text += data

            def _process_row(self):
                # Structure: trans=en_US=Option | trans=other=skip |
                #            plain[0]=Ordered | plain[1]=Factory |
                #            name2=viewDistribOption=Distributor | rest=skip
                option_name = ordered = factory = distributor = ''
                plain_cells = []
                for a, t in self.cells:
                    raw = t.strip()  # keep * as-is
                    if a.get('trans') == 'en_US':
                        option_name = raw
                    elif a.get('trans') == 'other':
                        continue
                    elif a.get('name2') == 'viewDistribOption':
                        distributor = raw
                    elif a.get('name2') == 'editDistribOption':
                        continue
                    elif a.get('width') == '100px' and a.get('align') == 'center':
                        continue
                    elif not a.get('trans') and not a.get('name2') and option_name:
                        plain_cells.append(raw)

                # Cell 2 (plain[0]) = Ordered (e.g. * or code)
                # Cell 3 (plain[1]) = Factory (e.g. 1102, 1299)
                if len(plain_cells) >= 1:
                    ordered = plain_cells[0]   # * or actual code
                if len(plain_cells) >= 2:
                    factory = plain_cells[1]   # factory code number

                if option_name:
                    self.rows.append({'option': option_name, 'ordered': ordered,
                                      'factory': factory, 'distributor': distributor})

        parser = JDPSParser()
        parser.feed(content)
        app.logger.info(f"JDPS: {len(parser.rows)} rows")

        added = 0
        ordem_start = EquipamentoOpcao.query.filter_by(equipamento_id=eid).count()
        for row in parser.rows:
            if not row['option']: continue
            o = EquipamentoOpcao(
                equipamento_id=eid,
                option_name=row['option'],
                ordered=row['ordered'],
                factory=row['factory'],
                distributor=row['distributor'],
                ordem=ordem_start + added,
            )
            db.session.add(o)
            added += 1
        db.session.commit()
        flash(f'Importados {added} option codes com sucesso.', 'success')
    except Exception as e:
        app.logger.error(f"JDPS import error: {e}")
        flash(f'Erro: {e}', 'error')
    return redirect(url_for('tecnico_detalhe', eid=eid))


@app.route('/tecnico/<int:eid>/opcoes/apagar-bulk', methods=['POST'])
@login_required
def tecnico_opcoes_apagar_bulk(eid):
    Equipamento.query.get_or_404(eid)
    ids = request.form.getlist('opcao_ids')
    if ids:
        EquipamentoOpcao.query.filter(
            EquipamentoOpcao.id.in_([int(i) for i in ids]),
            EquipamentoOpcao.equipamento_id == eid
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(f'{len(ids)} linhas eliminadas.', 'success')
    return redirect(url_for('tecnico_detalhe', eid=eid))


@app.route('/tecnico/importar-excel', methods=['GET', 'POST'])
@login_required
def tecnico_importar_excel():
    if request.method == 'GET':
        return render_template('tecnico_importar_excel.html')
    
    f = request.files.get('excel_file')
    if not f:
        flash('Nenhum ficheiro enviado.', 'error')
        return redirect(url_for('tecnico_importar_excel'))
    
    try:
        import openpyxl
        from io import BytesIO
        
        wb = openpyxl.load_workbook(BytesIO(f.read()), data_only=True)
        ws = wb.active
        
        # Find the actual header row and starting column (skip empty rows/cols)
        header_row = 1
        col_offset = 0
        for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
            vals = [str(v or '').strip() for v in row]
            non_empty = [(i, v) for i, v in enumerate(vals) if v]
            if len(non_empty) >= 3:  # found header row
                header_row = list(ws.iter_rows(min_row=1, max_row=10, values_only=True)).index(row) + 1
                col_offset = non_empty[0][0]
                break
        
        header_cells = list(ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True))[0]
        headers = [str(v or '').strip().lower() for v in header_cells]
        app.logger.info(f"Header row={header_row} offset={col_offset} headers={headers}")

        def find_col(names):
            for name in names:
                for i, h in enumerate(headers):
                    # normalise: remove accents roughly
                    hn = h.replace('ã','a').replace('á','a').replace('â','a').replace('é','e').replace('ê','e').replace('í','i').replace('ó','o').replace('ô','o').replace('ú','u').replace('ç','c').replace('º','').replace('ª','').replace('°','').strip()
                    nm = name.replace('ã','a').replace('á','a').replace('â','a').replace('é','e').replace('ê','e').replace('í','i').replace('ó','o').replace('ô','o').replace('ú','u').replace('ç','c').replace('º','').replace('ª','').strip()
                    if nm in hn:
                        return i
            return None

        # Try header-based detection first
        col_emb      = find_col(['embarca'])
        col_mod      = find_col(['modelo motor','motor mod','modelo m'])
        col_pot      = find_col(['potencia','pot','cv','kw'])
        col_rpm      = find_col(['rpm'])
        col_serie    = find_col(['serie motor','n serie motor','n. serie motor','serie m','n serie m'])
        col_base     = find_col(['base code','base cod','eq'])
        col_data_fab = find_col(['data fab','data de fab','fab'])
        col_marca_cx = find_col(['marca caixa','marca cai'])
        col_mod_cx   = find_col(['modelo caixa','caixa mod','cai mod','modelo cai'])
        col_ratio    = find_col(['ratio'])
        col_serie_cx = find_col(['serie caixa','n serie caixa','serie cai','n serie cai'])
        col_obs      = find_col(['obs','nota'])

        # Fallback: use positional order if headers not detected
        # Order: Embarcação Modelo Motor Potência RPM Nº Série Base Code Data Fab. Caixa Red. Ratio Série Caixa Obs
        ncols = len(headers)
        o = col_offset  # column offset
        if col_emb is None:      col_emb      = o + 0
        if col_mod is None:      col_mod      = o + 1
        if col_pot is None:      col_pot      = o + 2
        if col_rpm is None:      col_rpm      = o + 3
        if col_serie is None:    col_serie    = o + 4
        col_base = None  # not used
        col_data_fab = None  # not used
        if col_mod_cx is None:   col_mod_cx   = o + 8
        if col_ratio is None:    col_ratio    = o + 9
        if col_serie_cx is None: col_serie_cx = o + 10
        if col_obs is None:      col_obs      = o + 12

        app.logger.info(f"Cols mapped: emb={col_emb} mod={col_mod} pot={col_pot} serie={col_serie} base={col_base} cx={col_mod_cx} ratio={col_ratio}")
        
        # Log first data row for debug
        first_row = next(ws.iter_rows(min_row=2, max_row=2, values_only=True), None)
        app.logger.info(f"First data row: {first_row}")
        app.logger.info(f"Total rows: {ws.max_row}")

        added = 0
        duplicados = 0
        erros = []
        
        for row_idx, row in enumerate(ws.iter_rows(min_row=header_row+1, values_only=True), start=header_row+1):
            if not any(v for v in row if v is not None):
                continue
            
            def get(col):
                if col is None or col >= len(row): return ''
                v = row[col]
                if v is None: return ''
                return str(v).strip()
            
            embarcacao = get(col_emb)
            if not embarcacao or embarcacao.lower() in ('none','nan','','null'):
                app.logger.info(f'Row {row_idx}: skipped (empty embarcacao)')
                continue
            app.logger.info(f'Row {row_idx}: embarcacao={embarcacao}')

            serial = get(col_serie)
            
            # Check duplicate
            dup = Equipamento.query.filter_by(embarcacao=embarcacao)
            if serial:
                dup = dup.filter_by(serial_number=serial)
            if dup.first():
                duplicados += 1
                erros.append(f"L{row_idx}: {embarcacao}")
                continue
            
            pot = get(col_pot)
            if pot and 'cv' not in pot.lower() and 'kw' not in pot.lower() and pot.replace('.','').replace(',','').isdigit():
                pot = pot + ' CV'
            
            e = Equipamento(
                embarcacao      = embarcacao,
                motor_modelo    = get(col_mod),
                motor_potencia  = pot,
                serial_number   = serial,
                caixa_modelo    = get(col_mod_cx),
                caixa_ratio     = get(col_ratio),
                caixa_serial    = get(col_serie_cx),
                notas           = get(col_obs),
            )
            db.session.add(e)
            added += 1
        
        db.session.commit()
        
        msg = f'✅ {added} equipamentos importados.'
        if duplicados:
            msg += f' {duplicados} duplicados ignorados ({", ".join(erros[:3])}{"..." if len(erros)>3 else ""}).'
        flash(msg, 'success' if added > 0 else 'warning')
        return redirect(url_for('tecnico'))
    
    except Exception as e:
        app.logger.error(f"Excel import error: {e}")
        flash(f'Erro: {e}', 'error')
        return redirect(url_for('tecnico_importar_excel'))


@app.route('/tecnico/<int:eid>/motor-aux', methods=['POST'])
@login_required
def tecnico_motor_aux_criar(eid):
    Equipamento.query.get_or_404(eid)
    n = EquipamentoMotorAux.query.filter_by(equipamento_id=eid).count() + 1
    m = EquipamentoMotorAux(
        equipamento_id=eid,
        numero=int(request.form.get('numero', n)),
        marca=request.form.get('marca','').strip(),
        modelo=request.form.get('modelo','').strip(),
        serial_number=request.form.get('serial_number','').strip(),
        potencia=request.form.get('potencia','').strip(),
        rpm=request.form.get('rpm','').strip(),
        ano=request.form.get('ano','').strip(),
        notas=request.form.get('notas','').strip(),
        ordem=n,
    )
    db.session.add(m)
    db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=eid) + '#motores-aux')

@app.route('/tecnico/motor-aux/<int:mid>/editar', methods=['POST'])
@login_required
def tecnico_motor_aux_editar(mid):
    m = EquipamentoMotorAux.query.get_or_404(mid)
    m.numero        = int(request.form.get('numero', m.numero))
    m.marca         = request.form.get('marca', m.marca or '').strip()
    m.modelo        = request.form.get('modelo', m.modelo or '').strip()
    m.serial_number = request.form.get('serial_number', m.serial_number or '').strip()
    m.potencia      = request.form.get('potencia', m.potencia or '').strip()
    m.rpm           = request.form.get('rpm', m.rpm or '').strip()
    m.ano           = request.form.get('ano', m.ano or '').strip()
    m.notas         = request.form.get('notas', m.notas or '').strip()
    db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=m.equipamento_id) + '#motores-aux')

@app.route('/tecnico/motor-aux/<int:mid>/apagar', methods=['POST'])
@login_required
def tecnico_motor_aux_apagar(mid):
    m = EquipamentoMotorAux.query.get_or_404(mid)
    eid = m.equipamento_id
    db.session.delete(m)
    db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=eid) + '#motores-aux')


@app.route('/tecnico/<int:eid>/documento/upload', methods=['POST'])
@login_required
def tecnico_doc_upload(eid):
    e = Equipamento.query.get_or_404(eid)
    f = request.files.get('doc_file')
    componente = request.form.get('componente', '').strip()
    titulo = request.form.get('titulo', '').strip()
    notas = request.form.get('notas', '').strip()
    if not f or not componente or not titulo:
        flash('Preencha todos os campos e seleccione um ficheiro.', 'error')
        return redirect(url_for('tecnico_detalhe', eid=eid))
    ensure_upload_dir()
    safe = f"{eid}_{componente}_{f.filename.replace(' ','_')}"
    path = os.path.join(UPLOAD_TECNICO, safe)
    f.save(path)

    # Link to this equipment
    doc = EquipamentoDocumento(
        equipamento_id=eid,
        componente=componente,
        titulo=titulo,
        pdf_filename=f.filename,
        pdf_path=safe,
        notas=notas,
    )
    db.session.add(doc)

    # Determine model key for sharing
    tipo_comp = None
    modelo_val = None
    if componente == 'caixa' and e.caixa_modelo:
        tipo_comp = 'caixa'
        modelo_val = e.caixa_modelo.strip()
    elif componente == 'motor' and e.motor_modelo:
        tipo_comp = 'motor'
        modelo_val = e.motor_modelo.strip()
    elif componente.startswith('aux_'):
        # find the aux motor model
        num = int(componente.split('_')[1]) if '_' in componente else 1
        aux = EquipamentoMotorAux.query.filter_by(equipamento_id=eid, numero=num).first()
        if aux and aux.modelo:
            tipo_comp = 'aux'
            modelo_val = aux.modelo.strip()

    # Save to shared library if model identified
    if tipo_comp and modelo_val:
        existing = ModeloPDF.query.filter_by(tipo_componente=tipo_comp,
                                             modelo_codigo=modelo_val,
                                             titulo=titulo).first()
        if not existing:
            mp = ModeloPDF(
                tipo_componente=tipo_comp,
                modelo_codigo=modelo_val,
                titulo=titulo,
                pdf_filename=f.filename,
                pdf_path=safe,
            )
            db.session.add(mp)

    db.session.commit()

    msg = f'Documento adicionado.'
    if tipo_comp and modelo_val:
        count = Equipamento.query
        if tipo_comp == 'caixa':
            count = count.filter_by(caixa_modelo=modelo_val).count()
        elif tipo_comp == 'motor':
            count = count.filter_by(motor_modelo=modelo_val).count()
        else:
            count = 1
        if count > 1:
            msg = f'Documento guardado e partilhado com {count} equipamentos com {modelo_val}.'
    flash(msg, 'success')
    return redirect(url_for('tecnico_detalhe', eid=eid))

@app.route('/tecnico/documento/<int:did>/ver')
@login_required
def tecnico_doc_ver(did):
    d = EquipamentoDocumento.query.get_or_404(did)
    return send_from_directory(UPLOAD_TECNICO, d.pdf_path,
                               as_attachment=False, download_name=d.pdf_filename)

@app.route('/tecnico/documento/<int:did>/download')
@login_required
def tecnico_doc_download(did):
    d = EquipamentoDocumento.query.get_or_404(did)
    return send_from_directory(UPLOAD_TECNICO, d.pdf_path,
                               as_attachment=True, download_name=d.pdf_filename)

@app.route('/tecnico/documento/<int:did>/apagar', methods=['POST'])
@login_required
def tecnico_doc_apagar(did):
    d = EquipamentoDocumento.query.get_or_404(did)
    eid = d.equipamento_id
    try:
        path = os.path.join(UPLOAD_TECNICO, d.pdf_path)
        if os.path.exists(path): os.remove(path)
    except Exception: pass
    db.session.delete(d)
    db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=eid))


# ── BIBLIOTECA DE FACTORY CODE PDFs ─────────────────────────────────────────

@app.route('/api/factory-code/<code>/pdf')
@login_required
def api_factory_code_pdf(code):
    """Return PDF info for a factory code from the central library."""
    pdf = FactoryCodePDF.query.filter_by(factory_code=code).order_by(FactoryCodePDF.criado_em.desc()).first()
    if not pdf:
        return jsonify({'found': False})
    return jsonify({
        'found': True,
        'id': pdf.id,
        'titulo': pdf.titulo,
        'pdf_filename': pdf.pdf_filename,
        'ver_url': url_for('factory_code_pdf_ver', pid=pdf.id),
        'download_url': url_for('factory_code_pdf_download', pid=pdf.id),
    })

@app.route('/factory-code/pdf/<int:pid>/ver')
@login_required
def factory_code_pdf_ver(pid):
    p = FactoryCodePDF.query.get_or_404(pid)
    return send_from_directory(UPLOAD_TECNICO, p.pdf_path,
                               as_attachment=False, download_name=p.pdf_filename)

@app.route('/factory-code/pdf/<int:pid>/download')
@login_required
def factory_code_pdf_download(pid):
    p = FactoryCodePDF.query.get_or_404(pid)
    return send_from_directory(UPLOAD_TECNICO, p.pdf_path,
                               as_attachment=True, download_name=p.pdf_filename)

@app.route('/tecnico/opcao/<int:oid>/upload-factory', methods=['POST'])
@login_required
def tecnico_opcao_upload_factory(oid):
    """Upload PDF for an option code — saves to central library by factory code."""
    o = EquipamentoOpcao.query.get_or_404(oid)
    f = request.files.get('pdf')
    if not f or not f.filename:
        flash('Seleccione um ficheiro.', 'error')
        return redirect(url_for('tecnico_detalhe', eid=o.equipamento_id))

    ensure_upload_dir()
    factory_code = (o.factory or o.ordered or '').strip()
    safe = f"factory_{factory_code}_{f.filename.replace(' ','_')}"
    path = os.path.join(UPLOAD_TECNICO, safe)
    f.save(path)

    # Save/update central library entry
    if factory_code:
        existing = FactoryCodePDF.query.filter_by(factory_code=factory_code).first()
        if existing:
            # Update existing — replace file
            try:
                old = os.path.join(UPLOAD_TECNICO, existing.pdf_path)
                if os.path.exists(old) and old != path: os.remove(old)
            except Exception: pass
            existing.pdf_filename = f.filename
            existing.pdf_path = safe
            existing.titulo = f.filename
        else:
            db.session.add(FactoryCodePDF(
                factory_code=factory_code,
                titulo=f.filename,
                pdf_filename=f.filename,
                pdf_path=safe,
            ))

    # Also link directly to this option
    o.pdf_filename = f.filename
    o.pdf_path = safe
    db.session.commit()

    # Count how many other options share this factory code
    if factory_code:
        others = EquipamentoOpcao.query.filter(
            EquipamentoOpcao.factory == factory_code,
            EquipamentoOpcao.id != oid
        ).count()
        if others:
            flash(f'PDF guardado e disponível automaticamente para {others} outras linhas com factory code {factory_code}.', 'success')
        else:
            flash('PDF guardado na biblioteca central.', 'success')
    else:
        flash('PDF guardado.', 'success')

    return redirect(url_for('tecnico_detalhe', eid=o.equipamento_id))

@app.route('/biblioteca-factory')
@login_required
def biblioteca_factory():
    """List all factory code PDFs in the central library."""
    pdfs = FactoryCodePDF.query.order_by(FactoryCodePDF.factory_code).all()
    equipamentos = Equipamento.query.options(
        db.joinedload(Equipamento.opcoes)
    ).all()
    return render_template('biblioteca_factory.html', pdfs=pdfs, equipamentos=equipamentos)

@app.route('/biblioteca-factory/<int:pid>/apagar', methods=['POST'])
@login_required
def biblioteca_factory_apagar(pid):
    p = FactoryCodePDF.query.get_or_404(pid)
    try:
        path = os.path.join(UPLOAD_TECNICO, p.pdf_path)
        if os.path.exists(path): os.remove(path)
    except Exception: pass
    db.session.delete(p)
    db.session.commit()
    flash('PDF removido da biblioteca.', 'success')
    return redirect(url_for('biblioteca_factory'))


# ── BIBLIOTECA DE MODELO PDFs (partilhados por modelo de componente) ─────────

@app.route('/api/modelo-pdf/<tipo>/<path:modelo>')
@login_required
def api_modelo_pdf_list(tipo, modelo):
    """Return all PDFs for a component model."""
    pdfs = ModeloPDF.query.filter_by(tipo_componente=tipo, modelo_codigo=modelo).order_by(ModeloPDF.titulo).all()
    return jsonify([{
        'id': p.id, 'titulo': p.titulo, 'pdf_filename': p.pdf_filename,
        'ver_url': url_for('modelo_pdf_ver', pid=p.id),
        'download_url': url_for('modelo_pdf_download', pid=p.id),
        'criado_em': p.criado_em.strftime('%d/%m/%Y'),
    } for p in pdfs])

@app.route('/modelo-pdf/<int:pid>/ver')
@login_required
def modelo_pdf_ver(pid):
    p = ModeloPDF.query.get_or_404(pid)
    return send_from_directory(UPLOAD_TECNICO, p.pdf_path,
                               as_attachment=False, download_name=p.pdf_filename)

@app.route('/modelo-pdf/<int:pid>/download')
@login_required
def modelo_pdf_download(pid):
    p = ModeloPDF.query.get_or_404(pid)
    return send_from_directory(UPLOAD_TECNICO, p.pdf_path,
                               as_attachment=True, download_name=p.pdf_filename)

@app.route('/modelo-pdf/<int:pid>/editar', methods=['POST'])
@login_required
def modelo_pdf_editar(pid):
    p = ModeloPDF.query.get_or_404(pid)
    novo_titulo = request.form.get('titulo', '').strip()
    if novo_titulo:
        p.titulo = novo_titulo
        db.session.commit()
    return redirect(request.referrer or url_for('biblioteca_modelos'))

@app.route('/modelo-pdf/<int:pid>/apagar', methods=['POST'])
@login_required
def modelo_pdf_apagar(pid):
    p = ModeloPDF.query.get_or_404(pid)
    try:
        path = os.path.join(UPLOAD_TECNICO, p.pdf_path)
        if os.path.exists(path): os.remove(path)
    except Exception: pass
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/tecnico/<int:eid>/upload-modelo', methods=['POST'])
@login_required
def tecnico_upload_modelo(eid):
    """Upload PDF to central model library (for caixa/motor model sharing)."""
    e = Equipamento.query.get_or_404(eid)
    f = request.files.get('pdf')
    tipo = request.form.get('tipo', '').strip()
    modelo = request.form.get('modelo', '').strip()
    titulo = request.form.get('titulo', '').strip()

    if not f or not tipo or not modelo or not titulo:
        return jsonify({'ok': False, 'error': 'Campos em falta'}), 400

    ensure_upload_dir()
    safe = f"modelo_{tipo}_{modelo}_{f.filename.replace(' ','_')}"
    path = os.path.join(UPLOAD_TECNICO, safe)
    f.save(path)

    p = ModeloPDF(
        tipo_componente=tipo,
        modelo_codigo=modelo,
        titulo=titulo,
        pdf_filename=f.filename,
        pdf_path=safe,
    )
    db.session.add(p)
    db.session.commit()

    # Count how many equipamentos share this model
    if tipo == 'caixa':
        count = Equipamento.query.filter_by(caixa_modelo=modelo).count()
    elif tipo == 'motor':
        count = Equipamento.query.filter_by(motor_modelo=modelo).count()
    else:
        count = 0

    return jsonify({'ok': True, 'id': p.id, 'count': count, 'titulo': titulo})

@app.route('/biblioteca-modelos', methods=['GET', 'POST'])
@login_required
def biblioteca_modelos():
    q = request.args.get('q', '').strip()
    
    if request.method == 'POST':
        f = request.files.get('pdf')
        titulo = request.form.get('titulo', '').strip()
        tipo_comp = request.form.get('tipo_componente', 'geral').strip()
        modelo_cod = request.form.get('modelo_codigo', '').strip()
        
        if not f or not titulo:
            flash('Título e ficheiro são obrigatórios.', 'error')
            return redirect(url_for('biblioteca_modelos'))
        
        ensure_upload_dir()
        safe = f"bib_{tipo_comp}_{modelo_cod}_{f.filename.replace(' ','_')}".replace('/','_')
        path = os.path.join(UPLOAD_TECNICO, safe)
        f.save(path)
        
        # Generate thumbnail of first page
        thumb = None
        try:
            from pdf2image import convert_from_path
            pages = convert_from_path(path, first_page=1, last_page=1, dpi=80)
            if pages:
                thumb_name = safe.replace('.pdf', '_thumb.jpg')
                thumb_path = os.path.join(UPLOAD_TECNICO, thumb_name)
                pages[0].save(thumb_path, 'JPEG', quality=70)
                thumb = thumb_name
        except Exception as ex:
            app.logger.warning(f"Thumbnail error: {ex}")
        
        p = ModeloPDF(
            tipo_componente=tipo_comp,
            modelo_codigo=modelo_cod,
            titulo=titulo,
            pdf_filename=f.filename,
            pdf_path=safe,
        )
        # Store thumb in notas field temporarily — we'll add a column
        if thumb:
            p.pdf_path = safe  # keep path
        db.session.add(p)
        db.session.commit()
        
        # Store thumbnail path
        if thumb:
            try:
                from sqlalchemy import text
                with db.engine.begin() as conn:
                    conn.execute(text("UPDATE modelo_pdf SET thumb_path=:t WHERE id=:id"),
                                {'t': thumb, 'id': p.id})
            except Exception:
                pass
        
        flash(f'"{titulo}" adicionado à biblioteca.', 'success')
        return redirect(url_for('biblioteca_modelos'))
    
    query = ModeloPDF.query
    if q:
        query = query.filter(
            db.or_(
                ModeloPDF.titulo.ilike(f'%{q}%'),
                ModeloPDF.modelo_codigo.ilike(f'%{q}%'),
                ModeloPDF.tipo_componente.ilike(f'%{q}%'),
            )
        )
    pdfs = query.order_by(ModeloPDF.tipo_componente, ModeloPDF.modelo_codigo, ModeloPDF.titulo).all()
    
    # Collect unique models for suggestions
    caixas = db.session.query(Equipamento.caixa_modelo).filter(
        Equipamento.caixa_modelo.isnot(None)).distinct().all()
    motores = db.session.query(Equipamento.motor_modelo).filter(
        Equipamento.motor_modelo.isnot(None)).distinct().all()
    
    return render_template('biblioteca_modelos.html', pdfs=pdfs, q=q,
                           caixas=[c[0] for c in caixas if c[0]],
                           motores=[m[0] for m in motores if m[0]])


@app.route('/tecnico/documento/<int:did>/editar-titulo', methods=['POST'])
@login_required
def tecnico_doc_editar_titulo(did):
    d = EquipamentoDocumento.query.get_or_404(did)
    novo = request.form.get('titulo', '').strip()
    if novo:
        d.titulo = novo
        db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=d.equipamento_id))


@app.route('/api/tecnico/<int:eid>/tipo', methods=['POST'])
@login_required
def api_tecnico_tipo(eid):
    e = Equipamento.query.get_or_404(eid)
    novo = request.get_json().get('tipo', 'principal')
    e.tipo_motor = novo
    db.session.commit()
    return jsonify({'ok': True, 'tipo': novo})


@app.route('/api/tecnico/<int:eid>/ativo', methods=['POST'])
@login_required
def api_tecnico_ativo(eid):
    e = Equipamento.query.get_or_404(eid)
    e.ativo = not e.ativo
    db.session.commit()
    return jsonify({'ok': True, 'ativo': e.ativo})


import re as _re

def extrair_factory_code(filename):
    """Extract 4-5 char factory/ordered code from filename.
    e.g. PC12295_1150_ST617227 → code='1150', catalog='PC12295'
    """
    name = filename.replace('.pdf','').replace('.PDF','')
    parts = _re.split(r'[_\-]', name)
    # Catalog: first part that looks like PC##### (letters + digits)
    catalog = None
    for p in parts:
        if _re.match(r'^[A-Z]{1,3}[0-9]{4,6}$', p, _re.IGNORECASE):
            catalog = p.upper()
            break
    # Code: 4-5 char alphanumeric that is NOT the catalog and NOT a long serial
    code = None
    for p in parts:
        if p.upper() == (catalog or ''):
            continue
        if _re.match(r'^[A-Z0-9]{4,5}$', p, _re.IGNORECASE) and not _re.match(r'^ST', p, _re.IGNORECASE):
            code = p.upper()
            break
    return code, catalog

@app.route('/tecnico/<int:eid>/upload-bulk', methods=['GET', 'POST'])
@login_required
def tecnico_upload_bulk(eid):
    e = Equipamento.query.get_or_404(eid)
    opcoes = EquipamentoOpcao.query.filter_by(equipamento_id=eid).order_by(EquipamentoOpcao.ordem).all()
    
    if request.method == 'GET':
        outros_docs = EquipamentoDocumento.query.filter_by(
            equipamento_id=eid, componente='outros_bulk').order_by(
            EquipamentoDocumento.criado_em.desc()).all()
        app.logger.warning(f"BULK GET eid={eid} outros_docs={len(outros_docs)}")
        # Also check all docs for this equipment
        all_docs = EquipamentoDocumento.query.filter_by(equipamento_id=eid).all()
        app.logger.warning(f"ALL DOCS for eid={eid}: {[(d.id, d.componente, d.titulo) for d in all_docs]}")
        return render_template('tecnico_upload_bulk.html', equipamento=e, opcoes=opcoes, outros_docs=outros_docs)
    
    files = request.files.getlist('pdfs')
    if not files:
        flash('Nenhum ficheiro seleccionado.', 'error')
        return redirect(url_for('tecnico_upload_bulk', eid=eid))
    
    ensure_upload_dir()
    matched = 0
    unmatched = []
    
    for f in files:
        if not f or not f.filename:
            continue
        code, catalog = extrair_factory_code(f.filename)
        opcao = None
        
        if code:
            # Match against factory OR ordered columns for this equipment
            opcao = EquipamentoOpcao.query.filter_by(equipamento_id=eid).filter(
                db.or_(
                    db.func.replace(db.func.replace(EquipamentoOpcao.factory,'*',''),' ','') == code,
                    db.func.replace(db.func.replace(EquipamentoOpcao.ordered,'*',''),' ','') == code,
                    db.func.replace(db.func.replace(EquipamentoOpcao.distributor,'*',''),' ','') == code,
                )
            ).first()
        
        if opcao:
            safe = f"{eid}_opcao_{opcao.id}_{f.filename.replace(' ','_')}"
            path = os.path.join(UPLOAD_TECNICO, safe)
            f.save(path)
            opcao.pdf_filename = f.filename
            opcao.pdf_path = safe
            matched += 1
        else:
            # Save as "outros" document linked to equipment
            safe = f"outros_{eid}_{f.filename.replace(' ','_')}"
            path = os.path.join(UPLOAD_TECNICO, safe)
            f.save(path)
            app.logger.warning(f'SAVING outros_bulk doc: {f.filename} safe={safe}')
            doc = EquipamentoDocumento(
                equipamento_id=eid,
                componente='outros_bulk',
                titulo=f.filename,
                pdf_filename=f.filename,
                pdf_path=safe,
                notas=f'Código detectado: {code or "nenhum"} — sem correspondência',
            )
            db.session.add(doc)
            unmatched.append(f.filename)
    
    db.session.commit()
    
    if matched:
        flash(f'✅ {matched} PDFs associados automaticamente.', 'success')
    if unmatched:
        flash(f'⚠️ {len(unmatched)} ficheiro(s) guardados em "Outros Ficheiros".', 'warning')
    
    return redirect(url_for('tecnico_upload_bulk', eid=eid))

@app.route('/tecnico/<int:eid>/upload-bulk/assign', methods=['POST'])
@login_required
def tecnico_upload_bulk_assign(eid):
    """Manually assign an outros_bulk doc to an option code."""
    did = request.form.get('doc_id','')
    oid = request.form.get('opcao_id','')
    if not did or not oid:
        return redirect(url_for('tecnico_upload_bulk', eid=eid))
    
    doc = EquipamentoDocumento.query.get(int(did))
    opcao = EquipamentoOpcao.query.get(int(oid))
    
    if doc and opcao and opcao.equipamento_id == eid:
        opcao.pdf_filename = doc.pdf_filename
        opcao.pdf_path = doc.pdf_path
        db.session.delete(doc)
        db.session.commit()
        flash(f'PDF "{opcao.pdf_filename}" associado a "{opcao.option_name}".', 'success')
    
    return redirect(url_for('tecnico_upload_bulk', eid=eid))


@app.route('/api/tecnico/<int:eid>/outros-docs')
@login_required
def api_tecnico_outros_docs(eid):
    docs = EquipamentoDocumento.query.filter_by(
        equipamento_id=eid, componente='outros_bulk').order_by(
        EquipamentoDocumento.criado_em.asc()).all()

    # Detect duplicates by pdf_filename
    seen = {}
    for d in docs:
        key = (d.pdf_filename or '').strip().upper()
        if key not in seen:
            seen[key] = []
        seen[key].append(d.id)

    result = []
    for d in docs:
        key = (d.pdf_filename or '').strip().upper()
        is_dup = len(seen[key]) > 1
        is_kept = seen[key][0] == d.id  # keep first occurrence
        result.append({
            'id': d.id,
            'titulo': d.titulo,
            'pdf_filename': d.pdf_filename,
            'notas': d.notas or '',
            'ver_url': url_for('tecnico_doc_ver', did=d.id),
            'download_url': url_for('tecnico_doc_download', did=d.id),
            'is_duplicate': is_dup and not is_kept,
            'dup_count': len(seen[key]),
        })
    return jsonify(result)

@app.route('/api/tecnico/<int:eid>/outros-dedup', methods=['POST'])
@login_required
def api_tecnico_outros_dedup(eid):
    """Remove duplicate outros_bulk docs, keeping the first occurrence of each filename."""
    docs = EquipamentoDocumento.query.filter_by(
        equipamento_id=eid, componente='outros_bulk').order_by(
        EquipamentoDocumento.criado_em.asc()).all()

    seen = {}
    removed = 0
    for d in docs:
        key = (d.pdf_filename or '').strip().upper()
        if key in seen:
            # duplicate — delete
            try:
                path = os.path.join(UPLOAD_TECNICO, d.pdf_path) if d.pdf_path else None
                # Don't delete the file if the kept copy uses the same path
                if path and path != os.path.join(UPLOAD_TECNICO, seen[key].pdf_path or ''):
                    if os.path.exists(path): os.remove(path)
            except Exception: pass
            db.session.delete(d)
            removed += 1
        else:
            seen[key] = d

    db.session.commit()
    return jsonify({'ok': True, 'removed': removed})

@app.route('/api/tecnico/<int:eid>/associar-outro', methods=['POST'])
@login_required
def api_tecnico_associar_outro(eid):
    data = request.get_json()
    did = data.get('doc_id')
    oid = data.get('opcao_id')
    doc = EquipamentoDocumento.query.get(int(did))
    opcao = EquipamentoOpcao.query.get(int(oid))
    if not doc or not opcao or opcao.equipamento_id != eid:
        return jsonify({'ok': False, 'error': 'Não encontrado'})
    opcao.pdf_filename = doc.pdf_filename
    opcao.pdf_path = doc.pdf_path
    db.session.delete(doc)
    db.session.commit()
    return jsonify({'ok': True})


# ── CAMPOS TÉCNICOS POR MODELO ───────────────────────────────────────────────

@app.route('/api/campos-tecnicos/<tipo>/<path:modelo>')
@login_required
def api_campos_tecnicos(tipo, modelo):
    campos = CampoTecnicoModelo.query.filter_by(
        tipo_componente=tipo, modelo_codigo=modelo
    ).order_by(CampoTecnicoModelo.ordem, CampoTecnicoModelo.id).all()
    return jsonify([{
        'id': c.id, 'titulo': c.titulo, 'valor': c.valor, 'ordem': c.ordem,
        'pdf_filename': c.pdf_filename, 'pdf_path': c.pdf_path
    } for c in campos])

@app.route('/api/campos-tecnicos/<tipo>/<path:modelo>', methods=['POST'])
@login_required
def api_campos_tecnicos_criar(tipo, modelo):
    data = request.get_json()
    titulo = (data.get('titulo') or '').strip()
    valor  = (data.get('valor') or '').strip()
    if not titulo:
        return jsonify({'ok': False, 'error': 'Título obrigatório'})
    count = CampoTecnicoModelo.query.filter_by(tipo_componente=tipo, modelo_codigo=modelo).count()
    c = CampoTecnicoModelo(
        tipo_componente=tipo, modelo_codigo=modelo,
        titulo=titulo, valor=valor, ordem=count
    )
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'id': c.id, 'titulo': c.titulo, 'valor': c.valor})

@app.route('/api/campos-tecnicos/<int:cid>', methods=['PUT'])
@login_required
def api_campos_tecnicos_editar(cid):
    c = CampoTecnicoModelo.query.get_or_404(cid)
    data = request.get_json()
    c.titulo = (data.get('titulo') or c.titulo).strip()
    c.valor  = (data.get('valor')  or '').strip()
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/campos-tecnicos/<int:cid>', methods=['DELETE'])
@login_required
def api_campos_tecnicos_apagar(cid):
    c = CampoTecnicoModelo.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/campos-tecnicos/<int:cid>/upload', methods=['POST'])
@login_required
def api_campos_tecnicos_upload(cid):
    c = CampoTecnicoModelo.query.get_or_404(cid)
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'Nenhum ficheiro'})
    ensure_upload_dir()
    safe = f"campo_{cid}_{f.filename.replace(' ','_')}"
    path = os.path.join(UPLOAD_TECNICO, safe)
    f.save(path)
    c.pdf_filename = f.filename
    c.pdf_path = safe
    db.session.commit()
    return jsonify({'ok': True, 'filename': f.filename,
                    'ver_url': url_for('api_campos_tecnicos_ver', cid=cid),
                    'download_url': url_for('api_campos_tecnicos_download', cid=cid)})

@app.route('/api/campos-tecnicos/<int:cid>/ver')
@login_required
def api_campos_tecnicos_ver(cid):
    c = CampoTecnicoModelo.query.get_or_404(cid)
    if not c.pdf_path:
        return '', 404
    return send_from_directory(UPLOAD_TECNICO, c.pdf_path,
                               as_attachment=False, download_name=c.pdf_filename)

@app.route('/api/campos-tecnicos/<int:cid>/download')
@login_required
def api_campos_tecnicos_download(cid):
    c = CampoTecnicoModelo.query.get_or_404(cid)
    if not c.pdf_path:
        return '', 404
    return send_from_directory(UPLOAD_TECNICO, c.pdf_path,
                               as_attachment=True, download_name=c.pdf_filename)

@app.route('/api/campos-tecnicos/<int:cid>/remover-ficheiro', methods=['POST'])
@login_required
def api_campos_tecnicos_remover_ficheiro(cid):
    c = CampoTecnicoModelo.query.get_or_404(cid)
    try:
        if c.pdf_path:
            path = os.path.join(UPLOAD_TECNICO, c.pdf_path)
            if os.path.exists(path): os.remove(path)
    except Exception: pass
    c.pdf_filename = None
    c.pdf_path = None
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/tecnico/<int:eid>/sync-pdfs', methods=['POST'])
@login_required
def api_tecnico_sync_pdfs(eid):
    """Sync PDFs: fill missing + validate existing ones using catalog+code."""
    eq = Equipamento.query.get_or_404(eid)
    catalogo = (eq.catalogo or '').strip().upper()

    if not catalogo:
        return jsonify({
            'ok': False,
            'error': 'Este equipamento não tem Catálogo definido. Preencha o campo Catálogo no Editar Equipamento.'
        })

    # All equipamentos with same catalog
    cat_eq_ids = [e.id for e in Equipamento.query.filter(
        db.func.upper(Equipamento.catalogo) == catalogo).all()]

    all_opcoes = EquipamentoOpcao.query.filter_by(equipamento_id=eid).all()
    matched = 0
    corrected = 0
    missing = 0
    details_new = []
    details_fixed = []
    details_missing = []

    def get_ref(o):
        dist = (o.distributor or '').strip().replace('*','').strip()
        fac  = (o.factory    or '').strip().replace('*','').strip()
        ord_ = (o.ordered    or '').strip().replace('*','').strip()
        code = dist or fac or ord_
        typ  = 'distributor' if dist else ('factory' if fac else ('ordered' if ord_ else None))
        return code, typ

    def find_donor(o, code):
        """Find best PDF donor within same catalog."""
        for col in [EquipamentoOpcao.distributor, EquipamentoOpcao.factory, EquipamentoOpcao.ordered]:
            donor = EquipamentoOpcao.query.filter(
                EquipamentoOpcao.id != o.id,
                EquipamentoOpcao.pdf_path.isnot(None),
                EquipamentoOpcao.equipamento_id.in_(cat_eq_ids),
                db.func.replace(db.func.replace(col,'*',''),' ','') == code
            ).first()
            if donor:
                return donor
        return None

    for o in all_opcoes:
        code, typ = get_ref(o)
        if not code:
            continue

        donor = find_donor(o, code)

        def filename_matches(fname, cat, cod):
            """Check if filename contains both catalog and code."""
            if not fname: return False
            n = fname.upper()
            return cat.upper() in n and cod.upper() in n

        if not o.pdf_path:
            # Missing PDF — try to fill with donor that has correct catalog in filename
            if donor and filename_matches(donor.pdf_filename, catalogo, code):
                o.pdf_filename = donor.pdf_filename
                o.pdf_path = donor.pdf_path
                matched += 1
                details_new.append(f'✅ {o.option_name[:35]} ({typ}={code}) ← {donor.pdf_filename}')
            else:
                missing += 1
                details_missing.append(f'❌ {o.option_name[:35]} ({typ}={code})')
        else:
            # Has PDF — verify filename contains correct catalog AND code
            if not filename_matches(o.pdf_filename, catalogo, code):
                # Wrong — remove the PDF association
                old_name = o.pdf_filename
                o.pdf_filename = None
                o.pdf_path = None
                corrected += 1
                details_fixed.append(
                    f'🗑 {o.option_name[:30]} ({typ}={code}): '
                    f'"{old_name}" removido — não contém catálogo {catalogo} + código {code}'
                )
                # Immediately try to find a correct replacement
                if donor and filename_matches(donor.pdf_filename, catalogo, code):
                    o.pdf_filename = donor.pdf_filename
                    o.pdf_path = donor.pdf_path
                    details_fixed[-1] += f' → substituído por {donor.pdf_filename}'

    db.session.commit()

    return jsonify({
        'ok': True,
        'catalogo': catalogo,
        'matched': matched,
        'corrected': corrected,
        'missing': missing,
        'total': len(all_opcoes),
        'details_new': details_new,
        'details_fixed': details_fixed,
        'details_missing': details_missing,
    })


# ── GESTÃO DE PERFIS ─────────────────────────────────────────────────────────

@app.route('/admin/perfis')
@login_required
def admin_perfis():
    if not current_user.is_admin:
        flash('Sem permissão.','error'); return redirect(url_for('dashboard'))
    perfis = Perfil.query.order_by(Perfil.nome).all()
    return render_template('admin_perfis.html', perfis=perfis, menus=MENUS_DISPONIVEIS)

@app.route('/admin/perfis/novo', methods=['POST'])
@login_required
def admin_perfis_novo():
    if not current_user.is_admin: return redirect(url_for('dashboard'))
    nome = request.form.get('nome','').strip()
    if not nome or Perfil.query.filter_by(nome=nome).first():
        flash('Nome inválido ou já existe.','error')
        return redirect(url_for('admin_perfis'))
    menus = request.form.getlist('menus')
    p = Perfil(nome=nome, descricao=request.form.get('descricao','').strip())
    p.set_menus(menus)
    db.session.add(p)
    db.session.commit()
    flash(f'Perfil "{nome}" criado.','success')
    return redirect(url_for('admin_perfis'))

@app.route('/admin/perfis/<int:pid>/editar', methods=['POST'])
@login_required
def admin_perfis_editar(pid):
    if not current_user.is_admin: return redirect(url_for('dashboard'))
    p = Perfil.query.get_or_404(pid)
    p.nome = request.form.get('nome', p.nome).strip()
    p.descricao = request.form.get('descricao','').strip()
    p.set_menus(request.form.getlist('menus'))
    db.session.commit()
    flash(f'Perfil "{p.nome}" actualizado.','success')
    return redirect(url_for('admin_perfis'))

@app.route('/admin/perfis/<int:pid>/apagar', methods=['POST'])
@login_required
def admin_perfis_apagar(pid):
    if not current_user.is_admin: return redirect(url_for('dashboard'))
    p = Perfil.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    flash('Perfil removido.','info')
    return redirect(url_for('admin_perfis'))

@app.route('/admin/utilizadores/<int:uid>/perfil', methods=['POST'])
@login_required
def admin_utilizador_perfil(uid):
    if not current_user.is_admin: return redirect(url_for('dashboard'))
    u = User.query.get_or_404(uid)
    perfil_id = request.form.get('perfil_id','')
    # Store perfil_id in departamento field as JSON for now
    import json as _json
    try:
        meta = _json.loads(u.departamento or '{}')
    except:
        meta = {'dept': u.departamento or ''}
    meta['perfil_id'] = int(perfil_id) if perfil_id else None
    u.departamento = _json.dumps(meta)
    u.is_admin = request.form.get('is_admin') == 'on'
    db.session.commit()
    flash(f'Utilizador {u.nome} actualizado.','success')
    return redirect(url_for('admin_utilizadores'))

def get_user_perfil_id(user):
    """Get perfil_id from user.departamento JSON."""
    try:
        meta = json.loads(user.departamento or '{}')
        return meta.get('perfil_id')
    except:
        return None


# ── REGISTO DE UTILIZADORES ───────────────────────────────────────────────────

@app.route('/registo', methods=['GET', 'POST'])
def registo():
    if request.method == 'POST':
        nome     = request.form.get('nome','').strip()
        username = request.form.get('username','').strip()
        email    = request.form.get('email','').strip()
        password = request.form.get('password','')

        if not all([nome, username, email, password]):
            flash('Preencha todos os campos.', 'error')
            return redirect(url_for('registo'))

        if User.query.filter_by(username=username).first():
            flash('Username já existe.', 'error')
            return redirect(url_for('registo'))

        if RegistoPendente.query.filter_by(username=username, estado='pendente').first():
            flash('Já existe um pedido de registo pendente para este username.', 'error')
            return redirect(url_for('registo'))

        r = RegistoPendente(
            nome=nome, username=username, email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(r)
        db.session.commit()

        # Notify admins by email if SMTP configured
        try:
            _notificar_admins_registo(nome, username, email)
        except Exception as ex:
            app.logger.warning(f"Email notify error: {ex}")

        return redirect(url_for('registo_aguarda'))
    return render_template('registo.html', cfg=ConfigGeral.query.first())

@app.route('/registo/aguarda')
def registo_aguarda():
    return render_template('registo_aguarda.html', cfg=ConfigGeral.query.first())

@app.route('/admin/registos-pendentes')
@login_required
def admin_registos_pendentes():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    pendentes = RegistoPendente.query.filter_by(estado='pendente').order_by(RegistoPendente.criado_em).all()
    return render_template('admin_registos.html', pendentes=pendentes)

@app.route('/admin/registos/<int:rid>/aceitar', methods=['POST'])
@login_required
def admin_registo_aceitar(rid):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    r = RegistoPendente.query.get_or_404(rid)
    if User.query.filter_by(username=r.username).first():
        flash('Username já existe.', 'error')
        return redirect(url_for('admin_registos_pendentes'))
    u = User(nome=r.nome, username=r.username,
              password_hash=r.password_hash, is_admin=False,
              email=r.email, must_change_password=False)
    db.session.add(u)
    r.estado = 'aceite'
    db.session.commit()
    try:
        _enviar_email_aprovacao(r.email, r.nome, r.username)
        flash(f'Utilizador {r.nome} aprovado. Email enviado para {r.email}.', 'success')
    except Exception as ex:
        app.logger.warning(f"Email aprovacao error: {ex}")
        flash(f'Utilizador {r.nome} aprovado. ⚠️ Email não enviado: {ex}', 'warning')
    return redirect(url_for('admin_registos_pendentes'))

@app.route('/admin/registos/<int:rid>/recusar', methods=['POST'])
@login_required
def admin_registo_recusar(rid):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    r = RegistoPendente.query.get_or_404(rid)
    r.estado = 'recusado'
    db.session.commit()
    flash(f'Pedido de {r.nome} recusado.', 'info')
    return redirect(url_for('admin_registos_pendentes'))

def _notificar_admins_registo(nome, username, email):
    """Send email to all admins about new registration request."""
    admins = User.query.filter_by(is_admin=True).all()
    cfg = ConfigGeral.query.first()
    smtp_host = getattr(cfg, 'smtp_host', None) if cfg else None
    if not smtp_host:
        return
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(f"""
Novo pedido de registo na plataforma:

Nome: {nome}
Username: {username}
Email: {email}

Aceda ao menu Admin → Registos Pendentes para aprovar ou recusar.
""")
    msg['Subject'] = f'[NavTech] Novo pedido de registo: {nome}'
    msg['From'] = getattr(cfg, 'smtp_from', 'noreply@navtech.pt')
    msg['To'] = ', '.join([a.username for a in admins if '@' in (a.username or '')])
    if not msg['To']:
        return
    with smtplib.SMTP(smtp_host, getattr(cfg, 'smtp_port', 587)) as s:
        s.starttls()
        if getattr(cfg, 'smtp_user', None):
            s.login(cfg.smtp_user, cfg.smtp_pass or '')
        s.send_message(msg)

def _enviar_email_aprovacao(email, nome, username):
    """Send approval email to new user."""
    cfg = ConfigGeral.query.first()
    smtp_host = getattr(cfg, 'smtp_host', None) if cfg else None
    if not smtp_host or not email:
        return
    import smtplib
    from email.mime.text import MIMEText
    empresa = getattr(cfg, 'empresa_nome', 'NavTech') if cfg else 'NavTech'
    msg = MIMEText(f"""
Olá {nome},

O seu registo na plataforma {empresa} foi aprovado.

Pode agora aceder com o username: {username}

Bem-vindo(a)!
""")
    msg['Subject'] = f'[{empresa}] Acesso aprovado'
    msg['From'] = getattr(cfg, 'smtp_from', 'noreply@navtech.pt')
    msg['To'] = email
    with smtplib.SMTP(smtp_host, getattr(cfg, 'smtp_port', 587)) as s:
        s.starttls()
        if getattr(cfg, 'smtp_user', None):
            s.login(cfg.smtp_user, cfg.smtp_pass or '')
        s.send_message(msg)


@app.route('/api/admin/registos-count')
@login_required
def api_admin_registos_count():
    if not current_user.is_admin:
        return jsonify({'count': 0})
    return jsonify({'count': RegistoPendente.query.filter_by(estado='pendente').count()})


@app.route('/api/admin/testar-smtp', methods=['POST'])
@login_required
def api_testar_smtp():
    if not current_user.is_admin:
        return jsonify({'ok': False, 'error': 'Sem permissão'})
    cfg = ConfigGeral.query.first()
    if not cfg or not cfg.smtp_host:
        return jsonify({'ok': False, 'error': 'SMTP não configurado. Guarde primeiro.'})
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText('Teste de email da plataforma NavTech.')
        msg['Subject'] = '[NavTech] Teste de email'
        msg['From'] = cfg.smtp_from or cfg.smtp_user
        msg['To'] = cfg.smtp_user
        port = cfg.smtp_port or 587
        if port == 465:
            # SSL directo
            import ssl
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg.smtp_host, port, timeout=15, context=ctx) as s:
                if cfg.smtp_user and cfg.smtp_pass:
                    s.login(cfg.smtp_user, cfg.smtp_pass)
                s.send_message(msg)
        else:
            # STARTTLS (587 ou 25)
            with smtplib.SMTP(cfg.smtp_host, port, timeout=15) as s:
                s.ehlo()
                if cfg.smtp_tls:
                    s.starttls()
                    s.ehlo()
                if cfg.smtp_user and cfg.smtp_pass:
                    s.login(cfg.smtp_user, cfg.smtp_pass)
                s.send_message(msg)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


import secrets
import string

def gerar_password_aleatoria(length=10):
    chars = string.ascii_letters + string.digits + '!@#$%'
    return ''.join(secrets.choice(chars) for _ in range(length))

def enviar_email(para, assunto, corpo):
    """Generic email sender using SMTP config."""
    cfg = ConfigGeral.query.first()
    if not cfg or not getattr(cfg, 'smtp_host', None):
        raise Exception('SMTP não configurado')
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(corpo, 'plain', 'utf-8')
    msg['Subject'] = assunto
    msg['From'] = getattr(cfg, 'smtp_from', None) or getattr(cfg, 'smtp_user', '')
    msg['To'] = para
    port = getattr(cfg, 'smtp_port', 587) or 587
    if port == 465:
        import ssl
        with smtplib.SMTP_SSL(cfg.smtp_host, port, timeout=15, context=ssl.create_default_context()) as s:
            if cfg.smtp_user and cfg.smtp_pass:
                s.login(cfg.smtp_user, cfg.smtp_pass)
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg.smtp_host, port, timeout=15) as s:
            s.ehlo()
            if getattr(cfg, 'smtp_tls', 1): s.starttls(); s.ehlo()
            if cfg.smtp_user and cfg.smtp_pass:
                s.login(cfg.smtp_user, cfg.smtp_pass)
            s.send_message(msg)

@app.route('/recuperar-password', methods=['GET', 'POST'])
def recuperar_password():
    cfg = ConfigGeral.query.first()
    if request.method == 'POST':
        email_ou_user = request.form.get('email_ou_user','').strip()
        u = User.query.filter(
            (User.email == email_ou_user) | (User.username == email_ou_user)
        ).first()
        if u and u.email:
            nova = gerar_password_aleatoria()
            u.password_hash = generate_password_hash(nova)
            u.must_change_password = True
            db.session.commit()
            try:
                empresa = cfg.empresa_nome if cfg and cfg.empresa_nome else 'NavTech'
                enviar_email(u.email,
                    f'[{empresa}] Reset de Password',
                    f'Olá {u.nome},\n\nA sua password foi redefinida.\n\nPassword temporária: {nova}\n\nAo fazer login será pedido que defina uma nova password.\n\nSe não pediu este reset, contacte o administrador.')
                flash('Email enviado com a nova password temporária.', 'success')
            except Exception as ex:
                flash(f'Password alterada mas email não enviado: {ex}', 'warning')
        else:
            flash('Email ou utilizador não encontrado.', 'error')
        return redirect(url_for('login'))
    return render_template('recuperar_password.html', cfg=cfg)

@app.route('/alterar-password', methods=['GET', 'POST'])
@login_required
def alterar_password():
    if request.method == 'POST':
        atual = request.form.get('atual','')
        nova  = request.form.get('nova','').strip()
        conf  = request.form.get('confirmar','').strip()
        if not check_password_hash(current_user.password_hash, atual):
            flash('Password actual incorrecta.', 'error')
            return redirect(url_for('alterar_password'))
        if nova != conf:
            flash('As passwords não coincidem.', 'error')
            return redirect(url_for('alterar_password'))
        if len(nova) < 6:
            flash('A password deve ter pelo menos 6 caracteres.', 'error')
            return redirect(url_for('alterar_password'))
        current_user.password_hash = generate_password_hash(nova)
        current_user.must_change_password = False
        db.session.commit()
        flash('Password alterada com sucesso.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('alterar_password.html')

@app.route('/admin/utilizadores/<int:uid>/reset-password', methods=['POST'])
@login_required
def admin_reset_password(uid):
    if not current_user.is_admin: return redirect(url_for('dashboard'))
    u = User.query.get_or_404(uid)
    nova = gerar_password_aleatoria()
    u.password_hash = generate_password_hash(nova)
    u.must_change_password = True
    db.session.commit()
    if u.email:
        try:
            cfg = ConfigGeral.query.first()
            empresa = cfg.empresa_nome if cfg else 'NavTech'
            enviar_email(u.email,
                f'[{empresa}] Reset de Password',
                f'Olá {u.nome},\n\nA sua password foi redefinida pelo administrador.\n\nPassword temporária: {nova}\n\nAo fazer login será pedido que defina uma nova password.')
            flash(f'Password de {u.nome} redefinida e email enviado para {u.email}.', 'success')
        except Exception as ex:
            flash(f'Password redefinida: {nova} (email não enviado: {ex})', 'warning')
    else:
        flash(f'Password de {u.nome} redefinida: {nova} (sem email registado)', 'warning')
    return redirect(url_for('admin_utilizadores'))

@app.route('/admin/utilizadores/<int:uid>/editar-email', methods=['POST'])
@login_required
def admin_editar_email(uid):
    if not current_user.is_admin: return redirect(url_for('dashboard'))
    u = User.query.get_or_404(uid)
    u.email = request.form.get('email','').strip()
    db.session.commit()
    flash(f'Email de {u.nome} actualizado.', 'success')
    return redirect(url_for('admin_utilizadores'))


# ── FUNCIONÁRIOS ROUTES ───────────────────────────────────────────────────────

@app.route('/funcionarios')
@login_required
def funcionarios():
    q      = request.args.get('q','').strip()
    filtro = request.args.get('filtro','todos')
    cat    = request.args.get('categoria','')
    page   = int(request.args.get('page', 1))
    per    = 20

    query = Funcionario.query
    if q:
        query = query.filter(db.or_(
            Funcionario.nome.ilike(f'%{q}%'),
            Funcionario.numero.ilike(f'%{q}%'),
        ))
    if filtro == 'ativo':   query = query.filter_by(ativo=True)
    if filtro == 'inativo': query = query.filter_by(ativo=False)
    if cat: query = query.filter_by(categoria=cat)

    total = query.count()
    items = query.order_by(Funcionario.numero).offset((page-1)*per).limit(per).all()
    categorias = [r[0] for r in db.session.query(Funcionario.categoria).distinct() if r[0]]

    return render_template('funcionarios.html',
        funcionarios=items, total=total, page=page, per=per,
        q=q, filtro=filtro, categoria=cat, categorias=categorias,
        pages=((total-1)//per+1) if total else 1)

@app.route('/funcionarios/novo', methods=['GET','POST'])
@login_required
def funcionario_novo():
    if request.method == 'POST':
        from datetime import date
        def d(f): return request.form.get(f,'').strip() or None
        def di(f):
            v = d(f)
            try: return date.fromisoformat(v) if v else None
            except: return None

        # Auto-generate numero if empty
        num = d('numero')
        if not num:
            last = Funcionario.query.order_by(Funcionario.id.desc()).first()
            num = str((int(last.numero) + 1) if last and last.numero.isdigit() else 1).zfill(4)

        f = Funcionario(
            numero=num, nome=d('nome'), categoria=d('categoria'),
            ativo=request.form.get('ativo')=='1',
            data_nascimento=di('data_nascimento'),
            morada=d('morada'), nif=d('nif'),
            num_cc=d('num_cc'), num_passaporte=d('num_passaporte'),
            agregado_familiar=int(request.form.get('agregado_familiar',0) or 0),
            telemovel=d('telemovel'), email=d('email'),
            contacto_emergencia=d('contacto_emergencia'),
            nome_emergencia=d('nome_emergencia'),
            iban=d('iban'), num_seg_social=d('num_seg_social'),
            seguro_companhia=d('seguro_companhia'),
            seguro_apolice=d('seguro_apolice'), notas=d('notas'),
        )
        db.session.add(f)
        db.session.flush()
        _rh_upload_docs(f.id, request.files)
        db.session.commit()
        flash(f'Funcionário {f.nome} criado.', 'success')
        return redirect(url_for('funcionario_detalhe', fid=f.id))
    return render_template('funcionario_form.html', f=None)

@app.route('/funcionarios/<int:fid>')
@login_required
def funcionario_detalhe(fid):
    f = Funcionario.query.get_or_404(fid)
    return render_template('funcionario_detalhe.html', f=f)

@app.route('/funcionarios/<int:fid>/editar', methods=['GET','POST'])
@login_required
def funcionario_editar(fid):
    func = Funcionario.query.get_or_404(fid)
    if request.method == 'POST':
        from datetime import date
        def d(field): return request.form.get(field,'').strip() or None
        def di(field):
            v = d(field)
            try: return date.fromisoformat(v) if v else None
            except: return None
        # Update numero if changed and not duplicate
        novo_numero = d('numero')
        if novo_numero and novo_numero != func.numero:
            existente = Funcionario.query.filter_by(numero=novo_numero).first()
            if existente and existente.id != fid:
                flash(f'Nº {novo_numero} já está atribuído a {existente.nome}.', 'error')
                return redirect(url_for('funcionario_editar', fid=fid))
            func.numero = novo_numero
        func.nome=d('nome'); func.categoria=d('categoria')
        func.ativo=request.form.get('ativo')=='1'
        func.data_nascimento=di('data_nascimento')
        func.data_admissao=di('data_admissao')
        func.morada=d('morada'); func.nif=d('nif')
        func.num_cc=d('num_cc'); func.num_passaporte=d('num_passaporte')
        func.filiacao_pai=d('filiacao_pai'); func.filiacao_mae=d('filiacao_mae')
        func.situacao_militar=d('situacao_militar'); func.estado_civil=d('estado_civil')
        func.conjuge=d('conjuge')
        func.titulares_rendimento=int(request.form.get('titulares_rendimento',1) or 1)
        func.num_dependentes=int(request.form.get('num_dependentes',0) or 0)
        func.natural_freguesia=d('natural_freguesia'); func.natural_concelho=d('natural_concelho')
        func.socio_numero=d('socio_numero'); func.sindicato=d('sindicato')
        func.carta_conducao=request.form.get('carta_conducao')=='1'
        func.agregado_familiar=int(request.form.get('agregado_familiar',0) or 0)
        func.telemovel=d('telemovel'); func.email=d('email')
        func.contacto_emergencia=d('contacto_emergencia')
        func.nome_emergencia=d('nome_emergencia')
        func.iban=d('iban'); func.num_seg_social=d('num_seg_social')
        func.seguro_companhia=d('seguro_companhia')
        func.seguro_apolice=d('seguro_apolice')
        func.notas=d('notas'); func.obs=d('obs')
        _rh_upload_docs(fid, request.files)
        db.session.commit()
        flash('Dados actualizados.', 'success')
        return redirect(url_for('funcionario_detalhe', fid=fid))
    return render_template('funcionario_form.html', f=func)

@app.route('/funcionarios/<int:fid>/apagar', methods=['POST'])
@login_required
def funcionario_apagar(fid):
    f = Funcionario.query.get_or_404(fid)
    db.session.delete(f)
    db.session.commit()
    flash('Funcionário eliminado.', 'info')
    return redirect(url_for('funcionarios'))

@app.route('/funcionarios/<int:fid>/toggle-ativo', methods=['POST'])
@login_required
def funcionario_toggle_ativo(fid):
    f = Funcionario.query.get_or_404(fid)
    f.ativo = not f.ativo
    db.session.commit()
    return jsonify({'ok': True, 'ativo': f.ativo})

@app.route('/funcionarios/<int:fid>/doc/upload', methods=['POST'])
@login_required
def funcionario_doc_upload(fid):
    Funcionario.query.get_or_404(fid)
    file = request.files.get('file')
    tipo = request.form.get('tipo','outro')
    titulo = request.form.get('titulo','').strip()
    if not file or not titulo:
        flash('Título e ficheiro obrigatórios.', 'error')
        return redirect(url_for('funcionario_detalhe', fid=fid))
    safe = f"rh_{fid}_{tipo}_{file.filename.replace(' ','_')}"
    file.save(os.path.join(UPLOAD_RH, safe))
    db.session.add(FuncionarioDocumento(
        funcionario_id=fid, tipo=tipo, titulo=titulo,
        pdf_filename=file.filename, pdf_path=safe))
    db.session.commit()
    flash('Documento adicionado.', 'success')
    return redirect(url_for('funcionario_detalhe', fid=fid))

@app.route('/funcionarios/doc/<int:did>/ver')
@login_required
def funcionario_doc_ver(did):
    d = FuncionarioDocumento.query.get_or_404(did)
    return send_from_directory(UPLOAD_RH, d.pdf_path, as_attachment=False, download_name=d.pdf_filename)

@app.route('/funcionarios/doc/<int:did>/download')
@login_required
def funcionario_doc_download(did):
    d = FuncionarioDocumento.query.get_or_404(did)
    return send_from_directory(UPLOAD_RH, d.pdf_path, as_attachment=True, download_name=d.pdf_filename)

@app.route('/funcionarios/doc/<int:did>/apagar', methods=['POST'])
@login_required
def funcionario_doc_apagar(did):
    d = FuncionarioDocumento.query.get_or_404(did)
    fid = d.funcionario_id
    try:
        p = os.path.join(UPLOAD_RH, d.pdf_path)
        if os.path.exists(p): os.remove(p)
    except: pass
    db.session.delete(d)
    db.session.commit()
    return redirect(url_for('funcionario_detalhe', fid=fid))

@app.route('/funcionarios/<int:fid>/formacao/adicionar', methods=['POST'])
@login_required
def funcionario_formacao_add(fid):
    Funcionario.query.get_or_404(fid)
    from datetime import date
    def d(f): return request.form.get(f,'').strip() or None
    def di(f):
        v = d(f)
        try: return date.fromisoformat(v) if v else None
        except: return None
    fm = FuncionarioFormacao(
        funcionario_id=fid, titulo=d('titulo'), entidade=d('entidade'),
        data_inicio=di('data_inicio'), data_fim=di('data_fim'),
        horas=int(d('horas') or 0) if d('horas') else None)
    db.session.add(fm)
    db.session.flush()
    cert = request.files.get('certificado')
    if cert and cert.filename:
        safe = f"rh_{fid}_form_{fm.id}_{cert.filename.replace(' ','_')}"
        cert.save(os.path.join(UPLOAD_RH, safe))
        fm.pdf_filename = cert.filename
        fm.pdf_path = safe
    db.session.commit()
    flash('Formação adicionada.', 'success')
    return redirect(url_for('funcionario_detalhe', fid=fid))

@app.route('/funcionarios/formacao/<int:fmid>/apagar', methods=['POST'])
@login_required
def funcionario_formacao_apagar(fmid):
    fm = FuncionarioFormacao.query.get_or_404(fmid)
    fid = fm.funcionario_id
    try:
        if fm.pdf_path:
            p = os.path.join(UPLOAD_RH, fm.pdf_path)
            if os.path.exists(p): os.remove(p)
    except: pass
    db.session.delete(fm)
    db.session.commit()
    return redirect(url_for('funcionario_detalhe', fid=fid))

@app.route('/funcionarios/formacao/<int:fmid>/certificado')
@login_required
def funcionario_formacao_cert(fmid):
    fm = FuncionarioFormacao.query.get_or_404(fmid)
    return send_from_directory(UPLOAD_RH, fm.pdf_path, as_attachment=False, download_name=fm.pdf_filename)

@app.route('/funcionarios/exportar-excel')
@login_required
def funcionarios_exportar_excel():
    import openpyxl
    from io import BytesIO
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Funcionários'
    headers = ['Nº','Nome','Categoria','Ativo','Data Nasc.','Idade','NIF','Nº CC','Nº Passaporte',
               'Agregado Familiar','Telemóvel','Email','NIF','IBAN','Nº Seg. Social',
               'Seguro Companhia','Seguro Apólice','Morada']
    ws.append(headers)
    for f in Funcionario.query.order_by(Funcionario.numero).all():
        ws.append([f.numero, f.nome, f.categoria or '',
                   'Sim' if f.ativo else 'Não',
                   f.data_nascimento.strftime('%d/%m/%Y') if f.data_nascimento else '',
                   f.idade or '', f.nif or '', f.num_cc or '',
                   f.num_passaporte or '', f.agregado_familiar or 0,
                   f.telemovel or '', f.email or '', f.nif or '',
                   f.iban or '', f.num_seg_social or '',
                   f.seguro_companhia or '', f.seguro_apolice or '',
                   f.morada or ''])
    buf = BytesIO()
    wb.save(buf); buf.seek(0)
    from flask import send_file
    return send_file(buf, as_attachment=True, download_name='funcionarios.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def _rh_upload_docs(fid, files):
    """Upload inline document files (cc, passaporte, morada) from form."""
    for tipo in ['cc','passaporte','morada']:
        f = files.get(f'doc_{tipo}')
        if f and f.filename:
            safe = f"rh_{fid}_{tipo}_{f.filename.replace(' ','_')}"
            f.save(os.path.join(UPLOAD_RH, safe))
            # Replace existing doc of same type
            existing = FuncionarioDocumento.query.filter_by(funcionario_id=fid, tipo=tipo).first()
            if existing:
                existing.pdf_filename = f.filename; existing.pdf_path = safe
            else:
                db.session.add(FuncionarioDocumento(
                    funcionario_id=fid, tipo=tipo,
                    titulo={'cc':'Cartão de Cidadão','passaporte':'Passaporte','morada':'Comprovativo de Morada'}[tipo],
                    pdf_filename=f.filename, pdf_path=safe))


@app.route('/admin/perfis/sync-menus', methods=['POST'])
@login_required
def admin_perfis_sync_menus():
    """Show all available menus — doesn't change permissions, just refreshes the list."""
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    flash('Lista de menus actualizada. Edite cada perfil para atribuir os novos menus.', 'success')
    return redirect(url_for('admin_perfis'))


@app.route('/funcionarios/<int:fid>/situacao-prof/adicionar', methods=['POST'])
@login_required
def funcionario_situacao_prof_add(fid):
    if not current_user.is_admin:
        flash('Sem permissão.', 'error')
        return redirect(url_for('funcionario_detalhe', fid=fid))
    Funcionario.query.get_or_404(fid)
    from datetime import date
    def d(f): return request.form.get(f,'').strip() or None
    def di(f):
        v = d(f)
        try: return date.fromisoformat(v) if v else None
        except: return None
    def dn(f):
        v = d(f)
        if not v: return None
        try: return float(v.replace(',','.'))
        except: return None
    sp = FuncionarioSituacaoProf(
        funcionario_id=fid,
        data=di('data') or date.today(),
        categoria_prof=d('categoria_prof'),
        vencimento=dn('vencimento'),
        refeicao=dn('refeicao'),
        premios_outros=dn('premios_outros'),
        notas=d('notas'),
    )
    db.session.add(sp)
    db.session.commit()
    flash('Situação profissional adicionada.', 'success')
    return redirect(url_for('funcionario_detalhe', fid=fid) + '#situacao-prof')

@app.route('/funcionarios/situacao-prof/<int:sid>/apagar', methods=['POST'])
@login_required
def funcionario_situacao_prof_apagar(sid):
    if not current_user.is_admin:
        return redirect(url_for('funcionarios'))
    sp = FuncionarioSituacaoProf.query.get_or_404(sid)
    fid = sp.funcionario_id
    db.session.delete(sp)
    db.session.commit()
    return redirect(url_for('funcionario_detalhe', fid=fid) + '#situacao-prof')

@app.route('/funcionarios/<int:fid>/falta/gravar', methods=['POST'])
@login_required
def funcionario_falta_gravar(fid):
    Funcionario.query.get_or_404(fid)
    ano = int(request.form.get('ano', datetime.now().year))
    mes = int(request.form.get('mes', 1))
    dias = float(request.form.get('dias_falta', 0) or 0)
    horas = float(request.form.get('horas_falta', 0) or 0)
    tipo = request.form.get('tipo', 'injustificada')
    notas = request.form.get('notas', '').strip()

    existing = FuncionarioFalta.query.filter_by(
        funcionario_id=fid, ano=ano, mes=mes, tipo=tipo).first()
    if existing:
        existing.dias_falta = dias
        existing.horas_falta = horas
        existing.notas = notas
    else:
        db.session.add(FuncionarioFalta(
            funcionario_id=fid, ano=ano, mes=mes,
            dias_falta=dias, horas_falta=horas,
            tipo=tipo, notas=notas))
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/funcionarios/<int:fid>/faltas/<int:ano>')
@login_required
def api_funcionario_faltas(fid, ano):
    faltas = FuncionarioFalta.query.filter_by(funcionario_id=fid, ano=ano).all()
    return jsonify([{
        'id': f.id, 'mes': f.mes, 'dias_falta': float(f.dias_falta or 0),
        'horas_falta': float(f.horas_falta or 0), 'tipo': f.tipo, 'notas': f.notas or ''
    } for f in faltas])


# ── SALÁRIOS ROUTES ───────────────────────────────────────────────────────────

@app.route('/salarios')
@login_required
def salarios():
    funcionarios = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    return render_template('salarios.html', funcionarios=funcionarios)

@app.route('/salarios/processar/<int:fid>')
@login_required
def salarios_calendario(fid):
    func = Funcionario.query.get_or_404(fid)
    ano = int(request.args.get('ano', datetime.now().year))
    # Get existing recibos for this employee/year
    recibos = {r.mes: r for r in ReciboSalario.query.filter_by(
        funcionario_id=fid, ano=ano).all()}
    # Extra months defined by user
    extra_meses = []
    for m_num, m_label in MESES_LABELS.items():
        pass
    return render_template('salarios_calendario.html',
        func=func, ano=ano, recibos=recibos,
        meses_labels=MESES_LABELS)

@app.route('/salarios/recibo/<int:fid>/<int:ano>/<int:mes>', methods=['GET','POST'])
@login_required
def salario_recibo(fid, ano, mes):
    db.session.expire_all()  # force fresh read
    func = Funcionario.query.get_or_404(fid)
    recibo = ReciboSalario.query.filter_by(
        funcionario_id=fid, ano=ano, mes=mes).first()

    # Get last situacao profissional for defaults
    ultima_sp = None
    if func.situacoes_prof:
        ultima_sp = func.situacoes_prof[0]

    if request.method == 'POST':
        def n(f): 
            v = request.form.get(f,'0').strip().replace(',','.')
            try: return float(v)
            except: return 0.0

        if not recibo:
            recibo = ReciboSalario(
                funcionario_id=fid, ano=ano, mes=mes,
                mes_label=MESES_LABELS.get(mes, f'Mês {mes}'))
            db.session.add(recibo)

        recibo.vencimento_base     = n('vencimento_base')
        recibo.vencimento_base_rht = n('vencimento_base_rht')
        recibo.vencimento_base_g   = n('vencimento_base_g')
        recibo.faltas_dias         = n('faltas_dias')
        recibo.faltas_horas        = n('faltas_horas')
        recibo.horas_extra         = n('horas_extra')        # horas
        recibo.horas_extra_rht     = n('horas_extra_rht')
        recibo.sub_refeicao_dias   = n('sub_refeicao_dias')
        recibo.sub_refeicao_vdia   = n('sub_refeicao_vdia')
        recibo.subsidio_refeicao   = n('subsidio_refeicao')
        recibo.premios             = n('premios')
        recibo.outros_abonos       = n('outros_abonos')
        recibo.irs_retencao        = n('irs_retencao')
        recibo.irs_taxa            = n('irs_taxa')
        recibo.irs_parcela_abater  = n('irs_parcela_abater')
        recibo.irs_taxa_efetiva    = n('irs_taxa_efetiva')
        recibo.irs_base            = n('irs_base')
        recibo.seg_social_func     = n('seg_social_func')
        recibo.seg_social_taxa     = n('seg_social_taxa')
        recibo.seg_social_base     = n('seg_social_base')
        recibo.seg_social_emp      = n('seg_social_emp')
        recibo.outros_descontos    = n('outros_descontos')
        recibo.faltas_valor        = n('faltas_valor')
        recibo.notas               = request.form.get('notas','').strip()
        recibo.estado              = request.form.get('estado', 'rascunho')

        # Horas extra valor = horas * RHT
        hex_valor = recibo.horas_extra * recibo.horas_extra_rht if recibo.horas_extra and recibo.horas_extra_rht else n('horas_extra_valor')

        # Calculate totals
        recibo.total_abonos    = float(recibo.vencimento_base or 0) + float(recibo.subsidio_refeicao or 0) + hex_valor + float(recibo.premios or 0) + float(recibo.outros_abonos or 0)
        recibo.total_descontos = float(recibo.irs_retencao or 0) + float(recibo.seg_social_func or 0) + float(recibo.outros_descontos or 0) + float(recibo.faltas_valor or 0)
        recibo.liquido         = recibo.total_abonos - recibo.total_descontos
        recibo.atualizado_em   = datetime.now()
        db.session.commit()

        if request.form.get('action') == 'pdf':
            return redirect(url_for('salario_recibo_pdf', rid=recibo.id))
        flash('Recibo guardado.', 'success')
        return redirect(url_for('salario_recibo', fid=fid, ano=ano, mes=mes))

    # Get faltas for this month
    faltas_mes = FuncionarioFalta.query.filter_by(
        funcionario_id=fid, ano=ano, mes=mes).all()
    dias_falta = sum(float(f.dias_falta or 0) for f in faltas_mes)

    # Get tabelas IRS
    tabelas_irs = TabelaIRS.query.filter_by(ano=ano).order_by(TabelaIRS.id.desc()).all()

    return render_template('salario_recibo.html',
        func=func, ano=ano, mes=mes,
        mes_label=MESES_LABELS.get(mes, f'Mês {mes}'),
        recibo=recibo, ultima_sp=ultima_sp,
        dias_falta=dias_falta, tabelas_irs=tabelas_irs)

@app.route('/salarios/recibo/<int:rid>/pdf')
@login_required
def salario_recibo_pdf(rid):
    """Return printable HTML — user saves as PDF via browser print dialog."""
    db.session.expire_all()  # force fresh read from DB
    r = ReciboSalario.query.get_or_404(rid)
    func = Funcionario.query.get(r.funcionario_id)
    cfg = ConfigGeral.query.first()
    empresa_nome = cfg.empresa_nome if cfg else 'União Construtora Naval Limitada'
    upload_url = request.host_url.rstrip('/') + '/uploads'
    mes_label = MESES_LABELS.get(r.mes, r.mes_label or f'Mês {r.mes}')
    html = render_template('salario_recibo_print.html',
        recibo=r, func=func, ano=r.ano,
        mes_label=mes_label,
        cfg=cfg, empresa_nome=empresa_nome,
        upload_url=upload_url)
    from flask import make_response
    resp = make_response(html)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route('/salarios/recibo/<int:rid>/email', methods=['POST'])
@login_required
def salario_recibo_email(rid):
    r = ReciboSalario.query.get_or_404(rid)
    func = Funcionario.query.get(r.funcionario_id)
    if not func.email:
        return jsonify({'ok': False, 'error': 'Funcionario sem email'})
    try:
        cfg = ConfigGeral.query.first()
        empresa = cfg.empresa_nome if cfg else 'Empresa'
        mes_label = MESES_LABELS.get(r.mes, f'Mes {r.mes}')
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg['Subject'] = f'[{empresa}] Recibo Salario {mes_label} {r.ano}'
        msg['From'] = getattr(cfg,'smtp_from','') or getattr(cfg,'smtp_user','')
        msg['To'] = func.email
        msg.set_content(
            f'Ola {func.nome},\n\n'
            f'Segue em anexo o recibo de salario referente a {mes_label} de {r.ano}.\n\n'
            f'Com os melhores cumprimentos,\n{empresa}',
            charset='utf-8'
        )
        try:
            html_body = render_template('salario_recibo_print.html',
                recibo=r, func=func, ano=r.ano, mes_label=mes_label,
                cfg=cfg, empresa_nome=empresa,
                upload_url=request.host_url.rstrip('/') + '/uploads')
            html_clean = html_body.replace('window.onload', '//window.onload')
            fname = f'Recibo_{func.numero}_{r.ano}_{r.mes:02d}'
            pdf_done = False
            for wk_path in [
                r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
                r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe',
            ]:
                if os.path.exists(wk_path):
                    try:
                        import pdfkit
                        pdf_file = os.path.join(UPLOAD_SALARIOS, fname + '.pdf')
                        wk_opts = {'page-size':'A4','margin-top':'12mm','margin-bottom':'12mm',
                                   'margin-left':'12mm','margin-right':'12mm','encoding':'UTF-8','quiet':''}
                        pdfkit.from_string(html_clean, pdf_file, options=wk_opts,
                                           configuration=pdfkit.configuration(wkhtmltopdf=wk_path))
                        with open(pdf_file,'rb') as pf:
                            msg.add_attachment(pf.read(), maintype='application', subtype='pdf',
                                               filename=fname+'.pdf')
                        pdf_done = True
                    except Exception as ex_wk:
                        app.logger.warning(f'wkhtmltopdf: {ex_wk}')
                    break
            if not pdf_done:
                msg.add_attachment(html_clean.encode('utf-8'), maintype='text', subtype='html',
                                   filename=fname+'.html')
        except Exception as ex_a:
            app.logger.warning(f'Attach error: {ex_a}')
        port = getattr(cfg,'smtp_port',587) or 587
        if port == 465:
            import ssl
            with smtplib.SMTP_SSL(cfg.smtp_host, port, timeout=15,
                                   context=ssl.create_default_context()) as s:
                if cfg.smtp_user: s.login(cfg.smtp_user, cfg.smtp_pass or '')
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.smtp_host, port, timeout=15) as s:
                s.ehlo()
                if getattr(cfg,'smtp_tls',1): s.starttls(); s.ehlo()
                if cfg.smtp_user: s.login(cfg.smtp_user, cfg.smtp_pass or '')
                s.send_message(msg)
        return jsonify({'ok': True})
    except Exception as e:
        import traceback
        app.logger.error(f'Email error: {traceback.format_exc()}')
        return jsonify({'ok': False, 'error': str(e)})


# Documentos Contabilísticos
@app.route('/salarios/documentos', methods=['GET','POST'])
@login_required
def salarios_documentos():
    if request.method == 'POST':
        f = request.files.get('file')
        titulo = request.form.get('titulo','').strip()
        tipo = request.form.get('tipo','outro')
        ano = request.form.get('ano','')
        if f and titulo:
            safe = f"contab_{tipo}_{ano}_{f.filename.replace(' ','_')}"
            f.save(os.path.join(UPLOAD_SALARIOS, safe))
            doc = DocContabilistico(titulo=titulo, tipo=tipo,
                ano=int(ano) if ano.isdigit() else None,
                pdf_filename=f.filename, pdf_path=safe)
            db.session.add(doc)
            if tipo == 'tabela_irs' and ano.isdigit():
                db.session.add(TabelaIRS(ano=int(ano), descricao=titulo,
                    pdf_filename=f.filename, pdf_path=safe))
            db.session.commit()
            flash('Documento guardado.', 'success')
        return redirect(url_for('salarios_documentos'))
    docs = DocContabilistico.query.order_by(DocContabilistico.criado_em.desc()).all()
    return render_template('salarios_documentos.html', docs=docs)

@app.route('/salarios/documentos/<int:did>/ver')
@login_required
def salario_doc_ver(did):
    d = DocContabilistico.query.get_or_404(did)
    return send_from_directory(UPLOAD_SALARIOS, d.pdf_path, as_attachment=False, download_name=d.pdf_filename)

@app.route('/salarios/documentos/<int:did>/apagar', methods=['POST'])
@login_required
def salario_doc_apagar(did):
    d = DocContabilistico.query.get_or_404(did)
    try:
        p = os.path.join(UPLOAD_SALARIOS, d.pdf_path)
        if os.path.exists(p): os.remove(p)
    except: pass
    db.session.delete(d)
    db.session.commit()
    return redirect(url_for('salarios_documentos'))

@app.route('/salarios/historico')
@login_required
def salarios_historico():
    ano = int(request.args.get('ano', datetime.now().year))
    fid = request.args.get('fid','')
    q = ReciboSalario.query.filter_by(ano=ano)
    if fid: q = q.filter_by(funcionario_id=int(fid))
    recibos = q.order_by(ReciboSalario.funcionario_id, ReciboSalario.mes).all()
    funcs = Funcionario.query.filter_by(ativo=True).order_by(Funcionario.nome).all()
    return render_template('salarios_historico.html', recibos=recibos, ano=ano, funcs=funcs, fid=fid)


@app.route('/salarios/recibo/<int:rid>/excel')
@login_required
def salario_recibo_excel(rid):
    """Download salary slip as Excel."""
    from io import BytesIO
    from flask import send_file
    r = ReciboSalario.query.get_or_404(rid)
    func = Funcionario.query.get(r.funcionario_id)
    cfg = ConfigGeral.query.first()
    empresa = cfg.empresa_nome if cfg else 'União Construtora Naval Limitada'
    mes_label = MESES_LABELS.get(r.mes, r.mes_label or f'Mês {r.mes}')

    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("gerar_recibo",
        os.path.join(os.path.dirname(__file__), 'gerar_recibo.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    wb = mod.gerar_recibo_excel(func, r, mes_label, r.ano, empresa)
    buf = BytesIO()
    wb.save(buf); buf.seek(0)
    fname = f"Recibo_{func.numero}_{r.ano}_{r.mes:02d}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/salarios/recibo/<int:rid>/apagar', methods=['POST'])
@login_required
def salario_recibo_apagar(rid):
    r = ReciboSalario.query.get_or_404(rid)
    fid = r.funcionario_id
    ano = r.ano
    try:
        if r.pdf_path:
            p = os.path.join(UPLOAD_SALARIOS, r.pdf_path)
            if os.path.exists(p): os.remove(p)
    except: pass
    db.session.delete(r)
    db.session.commit()
    flash('Recibo eliminado.', 'info')
    return redirect(url_for('salarios_calendario', fid=fid, ano=ano))


# ── IMPORTAÇÃO RECIBOS EXCEL ─────────────────────────────────────────────────

@app.route('/salarios/importar', methods=['GET', 'POST'])
@login_required
def salarios_importar():
    if request.method == 'POST':
        f = request.files.get('excel')
        if not f or not f.filename:
            flash('Seleccione um ficheiro Excel.', 'error')
            return redirect(url_for('salarios_importar'))
        # Save temp file
        import tempfile, os as _os
        ext = _os.path.splitext(f.filename)[1].lower() or '.xls'
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        f.save(tmp.name); tmp.close()
        try:
            resultado = _parse_recibos_excel(tmp.name)
            # Strip non-serializable objects before storing in session
            resultado_safe = []
            for rec in resultado:
                r2 = {k: v for k, v in rec.items() if k != 'func_match'}
                resultado_safe.append(r2)
            session['excel_import_resultado'] = resultado_safe
            return render_template('salarios_importar_preview.html',
                resultado=resultado_safe,
                funcionarios=Funcionario.query.order_by(Funcionario.nome).all(),
                meses_labels=MESES_LABELS)
        except Exception as e:
            flash(f'Erro ao ler ficheiro: {e}', 'error')
            return redirect(url_for('salarios_importar'))
    return render_template('salarios_importar.html')

@app.route('/salarios/importar/confirmar', methods=['POST'])
@login_required
def salarios_importar_confirmar():
    """Confirm import — create ReciboSalario records from Excel data."""
    from flask import session as sess
    resultado = sess.get('excel_import_resultado', [])
    mes_global = request.form.get('mes_global', '')
    ano_global = request.form.get('ano_global', str(datetime.now().year))

    criados = 0
    erros = []
    for i, rec in enumerate(resultado):
        # Skip if not checked
        if not request.form.get(f'incluir_{i}'):
            continue
        fid = request.form.get(f'func_{i}')
        mes = request.form.get(f'mes_{i}') or mes_global
        ano = request.form.get(f'ano_{i}') or ano_global

        if not fid or not mes or not ano:
            erros.append(f"Linha {i+1} ({rec.get('sheet','?')}): sem funcionário/mês/ano")
            continue

        fid = int(fid); mes = int(mes); ano = int(ano)
        func = Funcionario.query.get(fid)
        if not func:
            erros.append(f"Linha {i+1}: funcionário não encontrado")
            continue

        # Check existing
        existing = ReciboSalario.query.filter_by(
            funcionario_id=fid, ano=ano, mes=mes).first()
        if existing:
            # Update
            r = existing
        else:
            r = ReciboSalario(funcionario_id=fid, ano=ano, mes=mes,
                mes_label=MESES_LABELS.get(mes, f'Mês {mes}'))
            db.session.add(r)

        r.vencimento_base     = rec.get('vencimento_base', 0)
        r.vencimento_base_rht = rec.get('vencimento_base_rht', 0)
        r.vencimento_base_g   = rec.get('vencimento_base_g', 0)
        r.premios             = rec.get('premios', 0)
        r.faltas_dias         = rec.get('faltas_dias', 0)
        r.faltas_horas        = rec.get('faltas_horas', 0)
        r.horas_extra         = rec.get('horas_extra_horas', 0)
        r.horas_extra_rht     = rec.get('horas_extra_rht', 0)
        r.sub_refeicao_dias   = rec.get('sub_refeicao_dias', 0)
        r.sub_refeicao_vdia   = rec.get('sub_refeicao_vdia', 0)
        r.subsidio_refeicao   = rec.get('subsidio_refeicao', 0)
        r.outros_abonos       = rec.get('outros_abonos', 0)
        r.total_abonos        = rec.get('total_iliquido', 0)
        r.seg_social_taxa     = rec.get('seg_social_taxa', 0)
        r.seg_social_base     = rec.get('seg_social_base', 0)
        r.seg_social_func     = rec.get('seg_social', 0)
        r.irs_taxa            = rec.get('irs_taxa', 0)
        r.irs_parcela_abater  = rec.get('irs_parcela_abater', 0)
        r.irs_taxa_efetiva    = rec.get('irs_taxa_efetiva', 0)
        r.irs_base            = rec.get('irs_base', 0)
        r.irs_retencao        = rec.get('irs', 0)
        r.outros_descontos    = 0
        r.total_descontos     = rec.get('total_descontos', 0)
        r.liquido             = rec.get('liquido', 0)
        r.estado              = 'processado'
        r.notas               = 'Importado de Excel: ' + rec.get('sheet','')
        if rec.get('obs'): r.notas = rec.get('obs') + ' | ' + r.notas
        r.atualizado_em       = datetime.now()
        criados += 1

    db.session.commit()
    if erros:
        for e in erros: flash(e, 'warning')
    flash(f'{criados} recibo(s) importado(s) com sucesso.', 'success')
    return redirect(url_for('salarios'))

def _parse_recibos_excel(filepath):
    """Parse UCN salary Excel format — one sheet per employee."""
    if filepath.lower().endswith('.xlsx'):
        return _parse_recibos_xlsx(filepath)

    # .xls — use xlrd
    import xlrd
    wb = xlrd.open_workbook(filepath)

    resultado = []

    # Get global month from INICIO sheet if present
    mes_global = ''
    try:
        ini = wb.sheet_by_name('INICIO')
        mes_global = str(ini.cell_value(4, 2)).strip()  # C5
    except: pass

    for sname in wb.sheet_names():
        if sname in ('INICIO', 'Transf BCP', 'inicio', 'transf'):
            continue
        ws = wb.sheet_by_name(sname)
        try:
            rec = _parse_sheet_xls(ws, sname, mes_global)
            resultado.append(rec)
        except Exception as e:
            resultado.append({'sheet': sname, 'erro': str(e), 'nome_raw': sname})

    return resultado

def _parse_sheet_xls(ws, sname, mes_global=''):
    """Parse one salary sheet. Skips non-salary sheets (dist lucros, etc).
    Finds key rows by text search within the 'original' block.
    """
    def fv(r, c):
        try: return float(ws.cell_value(r, c) or 0)
        except: return 0.0
    def sv(r, c):
        try: return str(ws.cell_value(r, c)).strip()
        except: return ''

    # Find 'original' row
    orig_row = 1
    for r in range(min(10, ws.nrows)):
        for c in range(ws.ncols):
            if sv(r, c).lower() == 'original':
                orig_row = r
                break

    O = orig_row

    # Verify this is a salary sheet (has 'Remuneração Base')
    has_rem = False
    for r in range(O, min(O+15, ws.nrows)):
        txt = sv(r, 0).upper()
        if 'REMUNERAÇÃO BASE' in txt or 'REMUNERACAO BASE' in txt:
            has_rem = True
            break
    if not has_rem:
        raise ValueError(f"Sheet '{sname}' não é um recibo de salário normal")

    # Find key rows by text in col A within the block
    rm = {}  # row_map
    for r in range(O, min(O+30, ws.nrows)):
        txt = sv(r, 0).upper()
        if not txt: continue
        if ('REMUNERAÇÃO BASE' in txt or 'REMUNERACAO BASE' in txt) and 'rem_base' not in rm:
            rm['rem_base'] = r
        elif ('GRATIFICAÇÃO' in txt or 'GRATIFICACAO' in txt or 'PRÉMIO' in txt or 'PREMIO' in txt) and 'premios' not in rm:
            rm['premios'] = r
        elif 'FALTAS' in txt and ('MÊS' in txt or 'MES' in txt or 'CORRENTE' in txt) and 'faltas_horas' not in rm:
            rm['faltas_horas'] = r
        elif 'FALTAS' in txt and 'faltas_dias' not in rm:
            rm['faltas_dias'] = r
        elif ('EXTRAORDINÁR' in txt or 'EXTRAORDINAR' in txt) and 'horas_extra' not in rm:
            rm['horas_extra'] = r
        elif ('ALIMENTAÇÃO' in txt or 'ALIMENTACAO' in txt or 'REFEIÇÃO' in txt) and 'sub_ref' not in rm:
            rm['sub_ref'] = r
        elif ('TOTAL ILÍQUIDO' in txt or 'TOTAL ILIQUIDO' in txt) and 'total_iliq' not in rm:
            rm['total_iliq'] = r
        elif 'C.R.S.S' in txt and 'crss' not in rm:
            rm['crss'] = r
        elif 'I.R.S' in txt and 'HORAS' not in txt and 'EXTRAS' not in txt and 'irs' not in rm:
            rm['irs'] = r
        elif ('TOTAL DE DESCONTOS' in txt or 'TOTAL DESCONTOS' in txt) and 'total_desc' not in rm:
            rm['total_desc'] = r
        elif ('LÍQUIDO A RECEBER' in txt or 'LIQUIDO A RECEBER' in txt) and 'liquido' not in rm:
            rm['liquido'] = r
        elif 'DISCRIMINATIVO' in txt and 'transf' not in rm:
            rm['transf'] = r

    RB  = rm.get('rem_base',  O+7)
    RPR = rm.get('premios',   O+8)
    RFD = rm.get('faltas_dias', O+9)
    RFH = rm.get('faltas_horas', O+10)
    RHE = rm.get('horas_extra', O+11)
    RSR = rm.get('sub_ref',   O+12)
    RTI = rm.get('total_iliq', O+14)
    RCS = rm.get('crss',      O+16)
    RIR = rm.get('irs',       O+17)
    RTD = rm.get('total_desc', O+21)
    RLQ = rm.get('liquido',   O+23)
    RTR = rm.get('transf',    O+25)

    # Employee name from A4 of block
    nome_raw = sv(O+2, 0).strip()
    if not nome_raw or 'NOME' in nome_raw.upper():
        nome_raw = sname

    # Match funcionario
    func_match = None
    funcs = Funcionario.query.all()
    if '-' in sname:
        parts = sname.split('-', 1)
        num = parts[0].strip()
        f_by_num = Funcionario.query.filter_by(numero=num).first()
        if f_by_num:
            func_match = f_by_num
        elif len(parts) > 1:
            nome_sheet = parts[1].strip()
            for f in funcs:
                if nome_sheet.upper() in f.nome.upper() or f.nome.upper() in nome_sheet.upper():
                    func_match = f; break
    if not func_match:
        nome_parts = [p for p in nome_raw.upper().split() if len(p) > 2]
        best = 0
        for f in funcs:
            score = sum(1 for p in nome_parts if any(p in fp for fp in f.nome.upper().split()))
            if score > best:
                best = score; func_match = f

    return {
        'sheet': sname,
        'nome_raw': nome_raw,
        'func_match_id':   func_match.id   if func_match else None,
        'func_match_nome': func_match.nome if func_match else '—',
        'mes_global': mes_global,
        'vencimento_base':     fv(RB,  7),  # H
        'vencimento_base_rht': fv(RB,  5),  # F
        'vencimento_base_g':   fv(RB,  6),  # G
        'premios':             fv(RPR, 7),  # H
        'faltas_dias':         fv(RFD, 3),  # D
        'faltas_horas':        fv(RFH, 4),  # E
        'horas_extra_horas':   fv(RHE, 4),  # E
        'horas_extra_rht':     fv(RHE, 5),  # F
        'horas_extra':         fv(RHE, 7),  # H
        'sub_refeicao_dias':   fv(RSR, 3),  # D
        'sub_refeicao_vdia':   fv(RSR, 5),  # F
        'subsidio_refeicao':   fv(RSR, 7),  # H
        'outros_abonos':       0,
        'total_iliquido':      fv(RTI, 7),  # H
        'seg_social_taxa':     fv(RCS, 3),  # D
        'seg_social_base':     fv(RCS, 4),  # E
        'seg_social':          fv(RCS, 5),  # F
        'irs_taxa':            fv(RIR, 1),  # B
        'irs_parcela_abater':  fv(RIR, 2),  # C
        'irs_taxa_efetiva':    fv(RIR, 3),  # D
        'irs_base':            fv(RIR, 4),  # E
        'irs':                 fv(RIR, 7),  # H
        'total_descontos':     fv(RTD, 7),  # H
        'liquido':             fv(RLQ, 7),  # H
        'transf_conta':        fv(RTR, 7),  # H
        'transf_refeicao':     fv(RTR+1, 7),# H next row
        'obs':                 sv(O+30, 5),  # F32
    }


def _parse_recibos_xlsx(filepath):
    """Parse .xlsx format."""
    import openpyxl
    wb = openpyxl.load_workbook(filepath, data_only=True)
    resultado = []
    for sname in wb.sheetnames:
        if sname.upper() in ('INICIO', 'TRANSF BCP'):
            continue
        ws = wb[sname]
        def fv(r, c):
            try: return float(ws.cell(row=r, column=c).value or 0)
            except: return 0.0
        def sv(r, c):
            try: return str(ws.cell(row=r, column=c).value or '').strip()
            except: return ''
        nome_raw = sv(4, 1).replace('NOME DO FUNCIONÁRIO','').replace('XPTO','').strip()
        resultado.append({
            'sheet': sname, 'nome_raw': nome_raw or sname,
            'func_match': None, 'func_match_id': None, 'func_match_nome': '—',
            'mes_global': '',
            'vencimento_base': fv(9,8), 'premios': fv(10,8),
            'horas_extra': fv(13,8), 'subsidio_refeicao': fv(14,8),
            'outros_abonos': fv(15,8), 'total_iliquido': fv(16,8),
            'seg_social': fv(18,6), 'irs': fv(19,8),
            'total_descontos': fv(23,8), 'liquido': fv(25,8),
            'transf_conta': fv(27,8), 'transf_refeicao': fv(28,8),
        })
    return resultado


def init_db():
    """Create all database tables."""
    with app.app_context():
        db.create_all()


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
# cache bust Tue Apr  7 15:34:00 UTC 2026
