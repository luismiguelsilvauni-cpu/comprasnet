import urllib.request

for f in ['app.py', 'templates/base.html']:
    data = urllib.request.urlopen('https://raw.githubusercontent.com/luismiguelsilvauni-cpu/comprasnet/main/'+f).read()
    open(f, 'wb').write(data)
    print("Downloaded", f, len(data), "bytes")

src = open('app.py', 'rb').read().decode('utf-8')

if "get('estado', 'aberto')" in src:
    print("OK: pedidos aberto ja existe")
else:
    src = src.replace("get('estado', 'todos')", "get('estado', 'aberto')")
    open('app.py', 'wb').write(src.encode('utf-8'))
    print("OK: pedidos default=aberto corrigido")

bsrc = open('templates/base.html', 'rb').read().decode('utf-8')

if 'backlogBadge' in bsrc:
    print("OK: badge ja existe")
else:
    bsrc = bsrc.replace(
        'Backlog</span>\n        </a>',
        'Backlog</span><span id="backlogBadge" style="display:none;margin-left:auto;font-size:10px;font-weight:700;padding:1px 6px;border-radius:8px;background:var(--accent);color:#fff"></span>\n        </a>'
    )
    js = '<script>(function(){fetch("/api/backlog").then(function(r){return r.json();}).then(function(items){var n=items.filter(function(i){return i.estado!="done";}).length;if(n>0){var b=document.getElementById("backlogBadge");if(b){b.textContent=n;b.style.display="inline";}}}).catch(function(){});})();</script>'
    bsrc = bsrc.replace('</body>', js + '\n</body>')
    open('templates/base.html', 'wb').write(bsrc.encode('utf-8'))
    print("OK: badge adicionado")

print("Concluido. Reinicie o servidor.")
