import urllib.request

# Download latest files
for f in ['app.py', 'templates/base.html']:
    data = urllib.request.urlopen(f'https://raw.githubusercontent.com/luismiguelsilvauni-cpu/comprasnet/main/{f}').read()
    open(f, 'wb').write(data)
    print(f"Downloaded {f}: {len(data)} bytes")

# Verify fix 1: pedidos default=aberto
with open('app.py', encoding='utf-8') as f:
    src = f.read()

if "estado = request.args.get('estado', 'aberto')" in src:
    print("OK: pedidos default=aberto ja existe")
else:
    src = src.replace(
        "estado = request.args.get('estado', 'todos')",
        "estado = request.args.get('estado', 'aberto')"
    )
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(src)
    if "estado = request.args.get('estado', 'aberto')" in open('app.py').read():
        print("OK: pedidos default=aberto corrigido")
    else:
        print("ERRO: nao encontrou o estado no app.py")

# Verify fix 3: backlog badge
with open('templates/base.html', encoding='utf-8') as f:
    bsrc = f.read()

if 'backlogBadge' in bsrc:
    print("OK: backlog badge ja existe no base.html")
else:
    bsrc = bsrc.replace(
        '<span class="icon">📋</span><span>Backlog</span>',
        '<span class="icon">📋</span><span>Backlog</span><span id="backlogBadge" style="display:none;margin-left:auto;font-size:10px;font-weight:700;padding:1px 6px;border-radius:8px;background:var(--accent);color:#fff"></span>'
    )
    badge_js = '''<script>
(function(){
  fetch('/api/backlog').then(r=>r.json()).then(items=>{
    const n=items.filter(i=>i.estado!=="done").length;
    if(n>0){const b=document.getElementById("backlogBadge");if(b){b.textContent=n;b.style.display="inline";}}
  }).catch(()=>{});
})();
</script>'''
    bsrc = bsrc.replace('</body>', badge_js + '\n</body>')
    with open('templates/base.html', 'w', encoding='utf-8') as f:
        f.write(bsrc)
    print("OK: backlog badge adicionado ao base.html")

print("Concluido. Reinicie o servidor.")
