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
    pedidos_recentes = PedidoCompra.query.filter(PedidoCompra.estado.in_(['aberto','aprovado','pendente'])).order_by(PedidoCompra.data_criacao.desc()).limit(8).all()
    # Stock baixo: stock > 0 mas abaixo de threshold (excluir negativos)
    artigos_stock_baixo = ArtigoPHC.query.filter(
        ArtigoPHC.stock_atual > 0,
        ArtigoPHC.stock_atual <= 3
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
            flash('O título é obrigatório.','error')
            return render_template('novo_pedido.html')
        p = PedidoCompra(titulo=titulo,
            descricao=request.form.get('descricao','').strip(),
            prioridade=request.form.get('prioridade','normal'),
            departamento=request.form.get('departamento','').strip(),
            estado='aberto', criado_por=current_user.id,
            data_criacao=datetime.now())
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
@login_required
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
    # Try local DB first
    clientes = ClientePHC.query.filter(ClientePHC.nome.ilike(f'%{q}%')).limit(10).all()
    if clientes:
        return jsonify([{'no': c.no, 'nome': c.nome} for c in clientes])
    # Query PHC directly
    try:
        cfg_phc = ConfigPHC.query.first()
        if cfg_phc:
            from phc_sync import get_phc_connection
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
    material        = db.Column(db.String(200))
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
    q = request.args.get('q', '').strip()
    query = Equipamento.query
    if q:
        query = query.filter(
            db.or_(
                Equipamento.serial_number.ilike(f'%{q}%'),
                Equipamento.model.ilike(f'%{q}%'),
                Equipamento.base_code.ilike(f'%{q}%'),
            )
        )
    equipamentos = query.order_by(Equipamento.criado_em.desc()).all()
    return render_template('tecnico.html', equipamentos=equipamentos, q=q)

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
        e.material          = request.form.get('material','').strip()
        e.caixa_modelo      = request.form.get('caixa_modelo','').strip()
        e.caixa_ratio       = request.form.get('caixa_ratio','').strip()
        e.caixa_serial      = request.form.get('caixa_serial','').strip()
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
    db.session.commit()
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
                option_name = ordered = factory = distributor = ''
                for a, t in self.cells:
                    clean = t.replace('*', '').strip()
                    if a.get('trans') == 'en_US':
                        option_name = clean
                    elif a.get('trans') == 'other':
                        continue
                    elif a.get('name2') == 'viewDistribOption':
                        distributor = clean
                    elif a.get('name2') == 'editDistribOption':
                        continue
                    elif a.get('width') == '100px' and a.get('align') == 'center':
                        continue
                    elif option_name and not a.get('trans') and not a.get('name2'):
                        if not ordered:
                            ordered = clean
                        elif not factory:
                            factory = clean
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
        
        # Read headers from first row
        headers = []
        for cell in ws[1]:
            headers.append((cell.value or '').strip().lower())
        
        app.logger.info(f"Excel headers: {headers}")
        
        # Map columns - flexible matching
        def find_col(names):
            for name in names:
                for i, h in enumerate(headers):
                    if name in h:
                        return i
            return None

        col_embarcacao  = find_col(['embarca'])
        col_modelo      = find_col(['modelo']) 
        col_cv          = find_col(['cv', 'potencia', 'pot'])
        col_rpm         = find_col(['rpm'])
        col_serie       = find_col(['série', 'serie', 'nº série', 'n serie'])
        col_eq          = find_col(['eq', 'base code', 'base'])
        col_caixa       = find_col(['modelo2', 'caixa'])
        col_ratio       = find_col(['ratio'])
        col_serie_caixa = find_col(['série3', 'serie3', 'nº série3', 'n serie3'])
        col_obs         = find_col(['obs', 'nota'])

        app.logger.info(f"Cols: emb={col_embarcacao} mod={col_modelo} cv={col_cv} serie={col_serie} eq={col_eq}")

        added = 0
        errors = []
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not any(row):
                continue
            
            def get(col):
                if col is None or col >= len(row): return ''
                v = row[col]
                return str(v).strip() if v is not None else ''
            
            embarcacao = get(col_embarcacao)
            if not embarcacao:
                continue  # skip empty rows
            
            e = Equipamento(
                embarcacao      = embarcacao,
                motor_modelo    = get(col_modelo),
                motor_potencia  = get(col_cv) + (' CV' if get(col_cv) and 'cv' not in get(col_cv).lower() else ''),
                serial_number   = get(col_serie),
                base_code       = get(col_eq),
                caixa_modelo    = get(col_caixa),
                caixa_ratio     = get(col_ratio),
                caixa_serial    = get(col_serie_caixa),
                notas           = get(col_obs),
            )
            db.session.add(e)
            added += 1
        
        db.session.commit()
        flash(f'✅ {added} equipamentos importados com sucesso.', 'success')
        return redirect(url_for('tecnico'))
    
    except Exception as e:
        app.logger.error(f"Excel import error: {e}")
        flash(f'Erro ao processar Excel: {e}', 'error')
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
    doc = EquipamentoDocumento(
        equipamento_id=eid,
        componente=componente,
        titulo=titulo,
        pdf_filename=f.filename,
        pdf_path=safe,
        notas=notas,
    )
    db.session.add(doc)
    db.session.commit()
    flash('Documento adicionado.', 'success')
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

@app.route('/biblioteca-modelos')
@login_required
def biblioteca_modelos():
    """Central model PDF library."""
    pdfs = ModeloPDF.query.order_by(ModeloPDF.tipo_componente, ModeloPDF.modelo_codigo, ModeloPDF.titulo).all()
    return render_template('biblioteca_modelos.html', pdfs=pdfs)

# Also update EquipamentoDocumento editar title
@app.route('/tecnico/documento/<int:did>/editar-titulo', methods=['POST'])
@login_required
def tecnico_doc_editar_titulo(did):
    d = EquipamentoDocumento.query.get_or_404(did)
    novo = request.form.get('titulo', '').strip()
    if novo:
        d.titulo = novo
        db.session.commit()
    return redirect(url_for('tecnico_detalhe', eid=d.equipamento_id))


def init_db():
    """Create all database tables."""
    with app.app_context():
        db.create_all()


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
# cache bust Tue Apr  7 15:34:00 UTC 2026
