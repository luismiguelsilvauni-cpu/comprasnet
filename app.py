import os, json, threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import pdfplumber
from models import db, User, PedidoCompra, LinhaPedido, Orcamento, ItemOrcamento, ArtigoPHC, AliasArtigo, FornecedorPHC, ConfigPHC, ConfigIA, ConfigReposicao, PendingMatch, Cliente, Embarcacao, ComponenteEmbarcacao, ConfigGeral, NotaArtigo, EventoCalendario

app = Flask(__name__)
app.permanent_session_lifetime = __import__('datetime').timedelta(days=30)
app.config['SECRET_KEY'] = 'comprasnet-2024-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///compras.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['BAK_FOLDER'] = os.path.join(os.path.dirname(__file__), 'bak_uploads')
os.makedirs(app.config['BAK_FOLDER'], exist_ok=True)

db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor faça login para aceder.'

@app.before_request
def make_session_permanent():
    session.permanent = True

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
            return redirect(url_for('dashboard'))
        flash('Utilizador ou palavra-passe incorretos.', 'error')
    return render_template('login.html')

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
    pedidos_recentes = PedidoCompra.query.order_by(PedidoCompra.data_criacao.desc()).limit(8).all()
    # Stock baixo: stock actual <= 5 e > 0, or stock = 0
    artigos_stock_baixo = ArtigoPHC.query.filter(
        ArtigoPHC.stock_atual <= 5
    ).order_by(ArtigoPHC.stock_atual).limit(10).all()
    return render_template('dashboard.html',
        total_pedidos=total_pedidos,
        pedidos_abertos=pedidos_abertos,
        pedidos_aprovados=pedidos_aprovados,
        total_orcamentos=total_orcamentos,
        pedidos_recentes=pedidos_recentes,
        artigos_stock_baixo=artigos_stock_baixo,
    )


@app.route('/pedidos')
@login_required
def pedidos():
    estado = request.args.get('estado','')
    q = PedidoCompra.query
    if estado: q = q.filter_by(estado=estado)
    return render_template('pedidos.html', pedidos=q.order_by(PedidoCompra.data_criacao.desc()).all(), estado_filtro=estado)

@app.route('/pedidos/novo', methods=['GET','POST'])
@login_required
def novo_pedido():
    if request.method == 'POST':
        titulo = request.form.get('titulo','').strip()
        if not titulo:
            flash('O título é obrigatório.','error')
            return render_template('novo_pedido.html')
        p = PedidoCompra(titulo=titulo,
            descricao=request.form.get('descricao','').strip(),
            prioridade=request.form.get('prioridade','normal'),
            departamento=request.form.get('departamento','').strip(),
            estado='aberto', criado_por=current_user.id,
            data_criacao=datetime.utcnow())
        db.session.add(p); db.session.commit()
        flash('Pedido criado!','success')
        return redirect(url_for('pedido_detalhe', pid=p.id))
    return render_template('novo_pedido.html')

@app.route('/pedidos/<int:pid>')
@login_required
def pedido_detalhe(pid):
    p = PedidoCompra.query.get_or_404(pid)
    orcs = Orcamento.query.filter_by(pedido_id=pid).order_by(Orcamento.total).all()
    linhas_json = json.dumps([{
        'id': l.id, 'referencia': l.referencia or '', 'designacao': l.designacao or '',
        'unidade': l.unidade or 'un', 'quantidade': l.quantidade,
        'stock_atual': l.stock_atual, 'preco_custo_ref': l.preco_custo_ref,
        'preco_pcp_ref': l.preco_pcp_ref, 'fornecedor_hab': l.fornecedor_hab or '',
        'observacoes': l.observacoes or '', 'artigo_ref': l.artigo_ref or ''
    } for l in p.linhas])
    return render_template('pedido_detalhe.html', pedido=p, orcamentos=orcs,
                           melhor=orcs[0] if orcs else None, linhas_json=linhas_json)

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
            observacoes     = l.get('observacoes','').strip()
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

    fname = secure_filename(f"pc{pid}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
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
        data_upload=datetime.utcnow(),
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
    p.estado = 'aprovado'; p.aprovado_por = current_user.id; p.data_aprovacao = datetime.utcnow()
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
@login_required
def download_pdf(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)



# ── REPOSIÇÃO ─────────────────────────────────────────────────────────────────

@app.route('/reposicao')
@login_required
def reposicao():
    """Replenishment suggestions dashboard."""
    from reposicao import CONFIG_PADRAO
    cfg_global = ConfigReposicao.query.filter_by(artigo_ref=None).first()
    if not cfg_global:
        cfg_global = ConfigReposicao()
        db.session.add(cfg_global)
        db.session.commit()
    artigos = ArtigoPHC.query.order_by(ArtigoPHC.referencia).all()
    return render_template('reposicao.html',
        cfg=cfg_global, artigos=artigos,
        total_artigos=len(artigos),
        config_padrao=CONFIG_PADRAO)


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
    cfg.taxa_posse_anual            = float(request.form.get('taxa_posse_anual', 0.20))
    cfg.quantidade_minima_encomenda = float(request.form.get('quantidade_minima_encomenda', 1))
    cfg.alertar_dias_cobertura      = int(request.form.get('alertar_dias_cobertura', 30))
    cfg.ignorar_parados_dias        = int(request.form.get('ignorar_parados_dias', 365))
    cfg.atualizado_em               = datetime.utcnow()
    cfg.atualizado_por              = current_user.id
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True})
    flash('Configuração de reposição guardada.', 'success')
    return redirect(url_for('reposicao'))


@app.route('/reposicao/analisar/<ref>')
@login_required
def analisar_artigo(ref):
    """Analyse one article and return replenishment suggestion as JSON."""
    from reposicao import analisar_artigo as _analisar, CONFIG_PADRAO

    cfg_phc    = ConfigPHC.query.first()
    cfg_artigo = ConfigReposicao.query.filter_by(artigo_ref=ref).first()
    cfg_global = ConfigReposicao.query.filter_by(artigo_ref=None).first()

    # Build config dict: defaults → global override → per-article override
    config = dict(CONFIG_PADRAO)
    if cfg_global:
        for k in CONFIG_PADRAO:
            v = getattr(cfg_global, k, None)
            if v is not None:
                config[k] = v
    if cfg_artigo:
        for k in CONFIG_PADRAO:
            v = getattr(cfg_artigo, k, None)
            if v is not None:
                config[k] = v

    resultado = _analisar(cfg_phc, config, ref)
    return jsonify(resultado)


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
        data_criacao=datetime.utcnow()
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
                    cfg.ultima_sync = datetime.utcnow()
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
    return render_template('admin_utilizadores.html', utilizadores=User.query.all())

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
    return render_template('changelog.html')


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
    pm.data_confirmacao  = datetime.utcnow()

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
    pm.data_confirmacao = datetime.utcnow()
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
        return {'cfg_geral': get_config_geral(), 'now': _dt.now}
    except Exception:
        return {'cfg_geral': None, 'now': _dt.now}


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
                c.ultima_sync_phc=datetime.utcnow(); atualizados+=1
            else:
                db.session.add(Cliente(phc_no=int(r[0]),nome=r[1],abreviatura=r[2],
                    nif=r[3],morada=r[4],localidade=r[5],cod_postal=r[6],pais=r[7],
                    telefone=r[8],telemovel=r[9],email=r[10],website=r[11],
                    ultima_sync_phc=datetime.utcnow())); inseridos+=1
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
        c.atualizado_em=datetime.utcnow()
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
    comp.atualizado_em = datetime.utcnow()
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
    messages   = data.get('messages', [])
    imagem_b64 = data.get('imagem_b64')
    imagem_tipo= data.get('imagem_tipo', 'image/jpeg')

    cfg_ia  = ConfigIA.query.first()
    cfg     = get_config_geral()
    sistema = (cfg.claude_chat_sistema if cfg else None) or \
              'És um assistente técnico especializado em equipamentos e compras industriais. Responde sempre em português.'

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
    ano  = request.args.get('ano',  type=int, default=datetime.utcnow().year)
    mes  = request.args.get('mes',  type=int, default=datetime.utcnow().month)
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
    } for e in eventos])


@app.route('/api/calendario/eventos', methods=['POST'])
@login_required
def api_criar_evento():
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
        hora         = data.get('hora','').strip() or None,
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
    e.atualizado_em = datetime.utcnow()
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

    data_compra = datetime.strptime(data.get('data_compra', datetime.utcnow().strftime('%Y-%m-%d')), '%Y-%m-%d').date()
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


def init_db():
    """Run migrations then seed default admin. Safe to call on every startup."""
    with app.app_context():
        # 1. Apply any pending migrations (creates tables if first run)
        try:
            from flask_migrate import upgrade
            upgrade(directory=os.path.join(os.path.dirname(__file__), 'migrations'))
        except Exception:
            # Fallback: create all tables directly (no migrations folder)
            db.create_all()

        # 2. Seed default admin if no users exist
        try:
            if not User.query.first():
                db.session.add(User(
                    username='admin', nome='Administrador',
                    password_hash=generate_password_hash('admin123'),
                    is_admin=True, departamento='Administração'))
                db.session.commit()
                print("✅ Utilizador admin criado  →  user: admin  /  pass: admin123")
        except Exception as e:
            print(f"⚠️  Erro ao criar admin: {e}")

# ── ADMIN IA ──────────────────────────────────────────────────────────────────

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
            cfg.ultimo_teste = datetime.utcnow()
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


if __name__ == '__main__':
    ensure_sqlserver_running()
    init_db()
    # Run startup health check with auto-fix
    try:
        from health_check import startup_check
        startup_check(app, auto_fix=True)
    except Exception as e:
        print(f"⚠️  Health check error: {e}")
    # Start backup scheduler
    try:
        from backup_manager import iniciar_scheduler
        iniciar_scheduler(app)
    except Exception as e:
        print(f"⚠️  Backup scheduler não iniciado: {e}")
    print("🚀 ComprasNet em http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
import threading as _threading
_sync_status = {'running': False, 'pct': 0, 'steps': [], 'done': False, 'error': None}

@app.route('/admin/phc/sync-start', methods=['POST'])
@login_required
def admin_phc_sync_start():
    global _sync_status
    if not current_user.is_admin:
        return jsonify({'error': 'Sem permissão'}), 403
    if _sync_status['running']:
        return jsonify({'error': 'Sync já em curso'}), 400

    cfg = ConfigPHC.query.first()
    if not cfg:
        return jsonify({'error': 'PHC não configurado'}), 400

    _sync_status = {'running': True, 'pct': 0, 'steps': [], 'done': False, 'error': None}

    def run_sync():
        global _sync_status
        def step(pct, msg):
            _sync_status['pct'] = pct
            _sync_status['steps'].append(msg)

        try:
            step(0, 'A verificar SQL Server...')
            ensure_sqlserver_running()
            step(5, 'A ligar ao SQL Server...')

            from phc_sync import sync_artigos, sync_fornecedores, sync_clientes, test_connection
            ok, msg = test_connection(cfg)
            if not ok:
                _sync_status['error'] = f'Erro de ligação: {msg}'
                _sync_status['running'] = False
                return

            step(10, 'A sincronizar artigos...')
            with app.app_context():
                ins_a, upd_a, err_a = sync_artigos(cfg)
            step(45, f'Artigos: {ins_a} novos, {upd_a} actualizados')

            step(50, 'A sincronizar fornecedores...')
            with app.app_context():
                ins_f, upd_f, err_f = sync_fornecedores(cfg)
            step(70, f'Fornecedores: {ins_f} novos, {upd_f} actualizados')

            step(75, 'A sincronizar clientes...')
            with app.app_context():
                ins_c, upd_c, err_c = sync_clientes(cfg)
            step(95, f'Clientes: {ins_c} novos, {upd_c} actualizados')

            with app.app_context():
                cfg2 = ConfigPHC.query.first()
                if cfg2:
                    cfg2.ultima_sync = datetime.utcnow()
                    db.session.commit()

            errs = len(err_a) + len(err_f) + len(err_c)
            msg = (f'Sync completa — Artigos: {ins_a}+{upd_a} | '
                   f'Fornecedores: {ins_f}+{upd_f} | Clientes: {ins_c}+{upd_c}')
            if errs: msg += f' | {errs} erros'
            step(100, msg)
            _sync_status['done'] = True

        except Exception as e:
            import traceback
            _sync_status['error'] = str(e)
            _sync_status['steps'].append(f'Erro: {e}')
        finally:
            _sync_status['running'] = False

    t = _threading.Thread(target=run_sync, daemon=True)
    t.start()
    return jsonify({'ok': True})


@app.route('/admin/phc/sync-status')
@login_required
def admin_phc_sync_status():
    return jsonify(_sync_status)



