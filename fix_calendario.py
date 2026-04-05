"""fix_calendario.py - Corrige erro hora None no calendario"""

with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

fixes = 0

# Fix all potential None.strip() issues in api_criar_evento
old = "hora         = data.get('hora','').strip() or None,"
new = "hora         = (data.get('hora') or '').strip() or None,"
if old in src:
    src = src.replace(old, new)
    fixes += 1
    print("OK Fix 1: hora strip")

# Also fix fornecedor and titulo just in case
old2 = "fornecedor   = data.get('fornecedor','').strip(),"
new2 = "fornecedor   = (data.get('fornecedor') or '').strip(),"
if old2 in src:
    src = src.replace(old2, new2)
    fixes += 1
    print("OK Fix 2: fornecedor strip")

old3 = "titulo       = data.get('titulo','').strip() or 'Sem título',"
new3 = "titulo       = (data.get('titulo') or '').strip() or 'Sem titulo',"
if old3 in src:
    src = src.replace(old3, new3)
    fixes += 1
    print("OK Fix 3: titulo strip")

# Safer approach: replace the entire criar_evento with a robust version
idx = src.find('def api_criar_evento():')
if idx > 0:
    end = src.find('\n\n\n@app.route', idx)
    old_func = src[idx:end]
    new_func = '''def api_criar_evento():
    if not current_user.is_authenticated:
        return jsonify({'error': 'Sessao expirada'}), 401
    data = request.get_json() or {}
    def s(v): return (v or '').strip()
    def parse_date(v):
        try: return datetime.strptime(v, '%Y-%m-%d').date() if v else None
        except: return None
    e = EventoCalendario(
        titulo       = s(data.get('titulo')) or 'Sem titulo',
        tipo         = s(data.get('tipo')) or 'manual',
        data_inicio  = parse_date(data.get('data_inicio')),
        data_fim     = parse_date(data.get('data_fim')),
        hora         = s(data.get('hora')) or None,
        descricao    = s(data.get('descricao')),
        artigos_json = __import__('json').dumps(data.get('artigos', [])),
        pedido_id    = data.get('pedido_id'),
        fornecedor   = s(data.get('fornecedor')),
        concluido    = bool(data.get('concluido', False)),
        criado_por   = current_user.id,
    )
    db.session.add(e)
    db.session.commit()
    return jsonify({'ok': True, 'id': e.id})'''
    src = src[:idx] + new_func + src[end:]
    fixes += 1
    print("OK Fix 4: entire function replaced safely")

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(src)

print(f"\nTotal: {fixes} fixes. Reinicie o servidor.")
