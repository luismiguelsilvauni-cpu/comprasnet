import os, json, threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import pdfplumber
from models import db, User, PedidoCompra, LinhaPedido, Orcamento, ItemOrcamento, ArtigoPHC, AliasArtigo, FornecedorPHC, ConfigPHC, ConfigIA, ConfigReposicao

app = Flask(__name__)
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
    cfg = ConfigPHC.query.first()
    return render_template('dashboard.html',
        total_pedidos    = PedidoCompra.query.count(),
        pedidos_abertos  = PedidoCompra.query.filter_by(estado='aberto').count(),
        pedidos_aprovados= PedidoCompra.query.filter_by(estado='aprovado').count(),
        total_orcamentos = Orcamento.query.count(),
        total_artigos    = ArtigoPHC.query.count(),
        ultima_sync      = cfg.ultima_sync if cfg else None,
        pedidos_recentes = PedidoCompra.query.order_by(PedidoCompra.data_criacao.desc()).limit(8).all())

# ── PEDIDOS ────────────────────────────────────────────────────────────────────

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
            cfg.servidor     = request.form.get('servidor','localhost').strip()
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
                    from phc_sync import sync_all
                    stats = sync_all(app, cfg)
                    flash(f"Sync concluída — Artigos: {stats['artigos']['inseridos']} novos / {stats['artigos']['atualizados']} atualizados | "
                          f"Fornecedores: {stats['fornecedores']['inseridos']} novos / {stats['fornecedores']['atualizados']} atualizados",'success')
                except Exception as e:
                    flash(f'Erro na sincronização: {e}','error')

        return redirect(url_for('admin_phc'))

    total_artigos = ArtigoPHC.query.count()
    total_forn    = FornecedorPHC.query.count()
    return render_template('admin_phc.html', cfg=cfg,
                           total_artigos=total_artigos, total_forn=total_forn)

# ── ADMIN USERS ───────────────────────────────────────────────────────────────

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
            cfg.provider  = request.form.get('provider', 'lmstudio')
            cfg.lm_host   = request.form.get('lm_host', 'localhost').strip()
            cfg.lm_port   = int(request.form.get('lm_port', 1234))
            cfg.lm_model  = request.form.get('lm_model', '').strip()
            key = request.form.get('claude_api_key', '').strip()
            if key: cfg.claude_api_key = key
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

if __name__ == '__main__':
    init_db()
    print("🚀 ComprasNet em http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
