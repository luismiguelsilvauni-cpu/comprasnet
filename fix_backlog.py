"""fix_backlog.py - Adiciona rota /roadmap (Backlog)"""
import urllib.request

# Download template
urllib.request.urlretrieve('https://raw.githubusercontent.com/luismiguelsilvauni-cpu/comprasnet/main/templates/roadmap.html', 'templates/roadmap.html')
print("OK: templates/roadmap.html descarregado")

with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

if "def roadmap():" in src:
    print("OK: rota roadmap ja existe")
else:
    rota = """
@app.route('/roadmap')
@login_required
def roadmap():
    return render_template('roadmap.html')

"""
    src = src.replace('\ndef init_db():', rota + '\ndef init_db():')
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("OK: rota /roadmap adicionada ao app.py")

print("Reinicie o servidor.")
