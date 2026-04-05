"""fix_artigo_template.py v3"""

with open('templates/reposicao_artigo.html', 'r', encoding='utf-8') as f:
    src = f.read()

print("Tamanho:", len(src))

# Find the monthly history table and replace it
# Look for the card that contains the monthly history
marker = 'Nº Fact.'
if marker in src:
    # Find the enclosing card div
    idx = src.find(marker)
    # Go back to find the card start
    card_start = src.rfind('<div class="card">', 0, idx)
    # Find card end
    card_end = src.find('</div>\n</div>', idx)
    if card_end > 0:
        card_end = card_end + len('</div>\n</div>')
    
    print(f"Card: {card_start} to {card_end}")
    
    new_section = '''<div style="display:flex;gap:8px;margin-bottom:12px">
  <button onclick="showTab2('mensal')" id="tab2-mensal" class="btn btn-primary btn-sm">Por Mes</button>
  <button onclick="showTab2('detalhe')" id="tab2-detalhe" class="btn btn-ghost btn-sm">Por Factura / Cliente</button>
</div>

<div id="view2-mensal" class="card">
  <div class="card-title">Historico Mensal</div>
  <div class="table-wrap" style="margin:0;max-height:320px;overflow-y:auto">
    <table>
      <thead><tr>
        <th>Mes/Ano</th>
        <th style="text-align:right">Vendido</th>
        <th style="text-align:right">Facturas</th>
        <th>vs. Media</th>
      </tr></thead>
      <tbody>
        {% set media_m = result.consumo_medio_mensal %}
        {% for v in vendas_lista|reverse %}
        <tr>
          <td class="mono" style="font-size:12px">{{ '%02d'|format(v.mes) }}/{{ v.ano }}</td>
          <td style="text-align:right;font-weight:600;font-family:monospace">{{ '%.1f'|format(v.total) }}</td>
          <td style="text-align:right;color:var(--text-muted)">{{ v.nfat }}</td>
          <td>{% if media_m > 0 %}{% set ratio = v.total / media_m %}
            <span style="font-size:11px;color:var(--text-muted)">{{ '%+.0f'|format((ratio-1)*100) }}%</span>
          {% else %}-{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<div id="view2-detalhe" class="card" style="display:none">
  <div class="card-title">Detalhe por Factura / Cliente</div>
  {% if vendas_detalhe %}
  <div class="table-wrap" style="margin:0;max-height:320px;overflow-y:auto">
    <table>
      <thead><tr>
        <th>Data</th>
        <th>Nr. Factura</th>
        <th>Cliente</th>
        <th style="text-align:right">Qtd.</th>
        <th style="text-align:right">P. Venda</th>
      </tr></thead>
      <tbody>
        {% for v in vendas_detalhe %}
        <tr>
          <td class="mono" style="font-size:12px">{{ v.data }}</td>
          <td class="mono" style="font-size:12px;color:var(--accent)">{{ v.num_fatura }}</td>
          <td style="font-size:12px">{{ (v.cliente_nome or 'N/D')[:35] }}</td>
          <td style="text-align:right;font-weight:600;font-family:monospace">{{ '%.1f'|format(v.quantidade) }}</td>
          <td style="text-align:right;font-size:12px;color:var(--text-muted)">{% if v.preco_venda %}{{ '%.2f'|format(v.preco_venda) }}EUR{% else %}-{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">Sem dados (PHC nao ligado ou sem vendas)</div>
  {% endif %}
</div>

<script>
function showTab2(tab) {
  document.getElementById('view2-mensal').style.display = tab==='mensal' ? '' : 'none';
  document.getElementById('view2-detalhe').style.display = tab==='detalhe' ? '' : 'none';
  document.getElementById('tab2-mensal').className = 'btn btn-sm ' + (tab==='mensal' ? 'btn-primary' : 'btn-ghost');
  document.getElementById('tab2-detalhe').className = 'btn btn-sm ' + (tab==='detalhe' ? 'btn-primary' : 'btn-ghost');
}
</script>'''
    
    src = src[:card_start] + new_section + src[card_end:]
    print("OK: Replaced card section")
else:
    print("Marker not found, looking for alternative...")
    idx = src.find('vendas_lista')
    print(f"vendas_lista at: {idx}")
    if idx > 0:
        print(repr(src[idx-100:idx+100]))

with open('templates/reposicao_artigo.html', 'w', encoding='utf-8') as f:
    f.write(src)

with open('templates/reposicao_artigo.html', encoding='utf-8') as f:
    check = f.read()
print("Nr. Factura:", 'Nr. Factura' in check)
print("view2-detalhe:", 'view2-detalhe' in check)
