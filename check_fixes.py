src = open('app.py', 'rb').read().decode('utf-8')
print("pedidos aberto:", "get('estado', 'aberto')" in src)
print("pedidos todos:", "get('estado', 'todos')" in src)

bsrc = open('templates/base.html', 'rb').read().decode('utf-8')
print("backlogBadge:", 'backlogBadge' in bsrc)

# Apply fixes if needed
if "get('estado', 'todos')" in src:
    src = src.replace("get('estado', 'todos')", "get('estado', 'aberto')")
    open('app.py', 'wb').write(src.encode('utf-8'))
    print("FIXED: pedidos default=aberto")

if 'backlogBadge' not in bsrc:
    bsrc = bsrc.replace(
        '>Backlog</span>\n        </a>',
        '>Backlog</span><span id="backlogBadge" style="display:none;margin-left:auto;font-size:10px;font-weight:700;padding:1px 6px;border-radius:8px;background:var(--accent);color:#fff"></span>\n        </a>'
    )
    js = '<script>(function(){fetch("/api/backlog").then(function(r){return r.json();}).then(function(d){var n=d.filter(function(i){return i.estado!="done";}).length;if(n){var b=document.getElementById("backlogBadge");if(b){b.textContent=n;b.style.display="inline";}}}).catch(function(){});})();</script>'
    bsrc = bsrc.replace('</body>', js + '\n</body>')
    open('templates/base.html', 'wb').write(bsrc.encode('utf-8'))
    print("FIXED: backlogBadge added")

print("Done. Restart server.")
