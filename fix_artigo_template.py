"""fix_artigo_template.py - Adiciona nr factura e cliente ao historico"""

with open('templates/reposicao_artigo.html', 'r', encoding='utf-8') as f:
    src = f.read()

# Check current state
has_tab = 'Por Factura' in src
has_mensal = 'view-mensal' in src
print(f"Tem tabs: {has_tab}, Tem view-mensal: {has_mensal}")

# Find the monthly history section and replace
if 'Historico Mensal de Vendas' in src or 'Histórico Mensal de Vendas' in src:
    # Find and replace the old single table with tabbed version
    idx_start = src.find('<div class="card">\n  <div class="card-title">📅')
    if idx_start == -1:
        idx_start = src.find('<div class="card">\n  <div class="card-title">&#')
    if idx_start == -1:
        # Try another approach
        idx_start = src.find('Hist')
        print(f"Found 'Hist' at: {idx_start}")
        print("Context:", repr(src[idx_start-30:idx_start+100]))
    
    if idx_start > 0:
        idx_end = src.find('\n{% endif %}\n\n{% endblock %}')
        if idx_end == -1:
            idx_end = src.find('{% endblock %}')
        
        new_section = '''
<!-- Tab switcher -->
<div style="display:flex;gap:8px;margin-bottom:12px">
  <button onclick="showTab('mensal')" id="tab-mensal" class="btn btn-primary btn-sm">Por Mes</button>
  <button onclick="showTab('detalhe')" id="tab-detalhe" class="btn btn-ghost btn-sm">Por Factura / Cliente</button>
</div>

<!-- Monthly view -->
<div id="view-mensal" class="card">
  <div class="card-title">Historico Mensal de Vendas</div>
  <div class="table-wrap" style="margin:0;max-height:350px;overflow-y:auto">
    <table>
      <thead>
        <tr>
          <th>Mes/Ano</th>
          <th style="text-align:right">Vendido</th>
          <th style="text-align:right">Facturas</th>
          <th>vs. Media</th>
        </tr>
      </thead>
      <tbody>
        {% set media_m = result.consumo_medio_mensal %}
        {% for v in vendas_lista|reverse %}
        <tr>
          <td class="mono" style="font-size:12px">{{ '%02d'|format(v.mes) }}/{{ v.ano }}</td>
          <td style="text-align:right;font-weight:600;font-family:monospace">{{ '%.1f'|format(v.total) }}</td>
          <td style="text-align:right;color:var(--text-muted)">{{ v.nfat }}</td>
          <td>
            {% if media_m > 0 %}
            {% set ratio = v.total / media_m %}
            {% set w = [ratio * 60, 120]|min|int %}
            <div style="display:flex;align-items:center;gap:6px">
              <div style="background:{% if ratio>1.5 %}var(--warning){% elif ratio<0.5 %}var(--surface2){% else %}var(--accent){% endif %};height:6px;width:{{ w }}px;border-radius:3px;min-width:2px"></div>
              <span style="font-size:11px;color:var(--text-muted)">{{ '%+.0f'|format((ratio-1)*100) }}%</span>
            </div>
            {% else %}-{% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<!-- Invoice detail view -->
<div id="view-detalhe" class="card" style="display:none">
  <div class="card-title">Detalhe por Factura / Cliente</div>
  {% if vendas_detalhe %}
  <div class="table-wrap" style="margin:0;max-height:350px;overflow-y:auto">
    <table>
      <thead>
        <tr>
          <th>Data</th>
          <th>Nr. Factura</th>
          <th>Cliente</th>
          <th style="text-align:right">Qtd.</th>
          <th style="text-align:right">P. Venda</th>
        </tr>
      </thead>
      <tbody>
        {% for v in vendas_detalhe %}
        <tr>
          <td class="mono" style="font-size:12px">{{ v.data }}</td>
          <td class="mono" style="font-size:12px;color:var(--accent)">{{ v.num_fatura }}</td>
          <td style="font-size:12px">{{ (v.cliente_nome or 'N/D')[:35] }}</td>
          <td style="text-align:right;font-weight:600;font-family:monospace">{{ '%.1f'|format(v.quantidade) }}</td>
          <td style="text-align:right;font-size:12px;color:var(--text-muted)">
            {% if v.preco_venda %}{{ '%.2f'|format(v.preco_venda) }}EUR{% else %}-{% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px">Sem dados PHC disponiveis</div>
  {% endif %}
</div>

<script>
function showTab(tab) {
  document.getElementById('view-mensal').style.display = tab==='mensal' ? '' : 'none';
  document.getElementById('view-detalhe').style.display = tab==='detalhe' ? '' : 'none';
  document.getElementById('tab-mensal').className = 'btn btn-sm ' + (tab==='mensal' ? 'btn-primary' : 'btn-ghost');
  document.getElementById('tab-detalhe').className = 'btn btn-sm ' + (tab==='detalhe' ? 'btn-primary' : 'btn-ghost');
}
</script>

{% endif %}

{% endblock %}'''
        
        # Replace from card start to end
        src = src[:idx_start] + new_section
        print("OK: Template replaced")
    else:
        print("ERROR: Could not find start of history section")
else:
    print("ERROR: History section not found")

with open('templates/reposicao_artigo.html', 'w', encoding='utf-8') as f:
    f.write(src)

# Verify
with open('templates/reposicao_artigo.html', encoding='utf-8') as f:
    check = f.read()
print("num_fatura:", 'num_fatura' in check)
print("Por Factura:", 'Por Factura' in check)
