
with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

# Find and replace the old pedidos route
import re
# Match from def pedidos(): to next @app.route
pattern = r'def pedidos\(\):.*?(?=@app\.route)'
new_route = "def pedidos():\n    # filtro_tab: em_analise, pedido, concluido, todos\n    filtro_tab = request.args.get('filtro_tab', 'em_analise')\n    q_filter = request.args.get('q','').strip()\n\n    # Get all active pedidos\n    q = PedidoCompra.query.filter(\n        PedidoCompra.estado.notin_(['cancelado','arquivado','anulado'])\n    )\n    if q_filter:\n        q = q.filter(db.or_(\n            PedidoCompra.titulo.ilike(f'%{q_filter}%'),\n            PedidoCompra.descricao.ilike(f'%{q_filter}%'),\n        ))\n    todos = q.order_by(PedidoCompra.data_criacao.desc()).all()\n\n    # Classify each pedido by its linhas statuses\n    def classify(p):\n        statuses = set(l.status or 'nao_encomendado' for l in p.linhas)\n        if not statuses: return 'em_analise'\n        if statuses <= {'concluido','faturado','cancelado'}: return 'concluido'\n        if any(s in statuses for s in ['encomendado','por_faturar','recebido','faturado']): return 'pedido'\n        return 'em_analise'  # nao_encomendado or consultado\n\n    # Count per tab\n    tab_counts = {'em_analise': 0, 'pedido': 0, 'concluido': 0, 'todos': len(todos)}\n    classified = []\n    for p in todos:\n        cls = classify(p)\n        tab_counts[cls] += 1\n        classified.append((p, cls))\n\n    # Filter\n    if filtro_tab == 'todos':\n        pedidos_list = todos\n    else:\n        pedidos_list = [p for p, cls in classified if cls == filtro_tab]\n\n    return render_template('pedidos.html', pedidos=pedidos_list,\n        filtro_tab=filtro_tab, tab_counts=tab_counts, q=q_filter)\n\n"

src_new = re.sub(pattern, new_route + '\n\n', src, count=1, flags=re.DOTALL)
if src_new != src:
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(src_new)
    print('Fixed OK')
else:
    print('No change - checking:')
    idx = src.find('def pedidos():')
    print(src[idx:idx+100])
