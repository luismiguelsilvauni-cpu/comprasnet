"""fix_historico_vendas.py - Corrige historico de vendas no artigo"""
import urllib.request

# Download template directamente
data = urllib.request.urlopen('https://raw.githubusercontent.com/luismiguelsilvauni-cpu/comprasnet/main/templates/reposicao_artigo.html').read()
open('templates/reposicao_artigo.html', 'wb').write(data)

with open('templates/reposicao_artigo.html', encoding='utf-8') as f:
    s = f.read()

print("Tamanho:", len(s))
print("num_fatura:", 'num_fatura' in s)
print("vendas_detalhe:", 'vendas_detalhe' in s)
print("Nr Factura:", 'Nº Factura' in s)

if 'num_fatura' in s:
    print("OK - Template actualizado!")
else:
    print("ERRO - Template nao actualizou")
