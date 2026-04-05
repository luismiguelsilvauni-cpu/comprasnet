"""fix_artigo_template.py - Adiciona historico de vendas com nr factura e cliente"""

with open('templates/reposicao_artigo.html', 'r', encoding='utf-8') as f:
    src = f.read()

# Check if already has the feature
if 'view-detalhe' in src:
    print("Template ja tem a funcionalidade. OK.")
else:
    # Add before {% endblock %}
    new_section = '''
<!-- Historico de Vendas com tabs -->
{% if vendas_lista %}
<div style="display:flex;gap:8px;margin-bottom:12px;margin-top:16px">
  <button onclick="showTab('mensal')" id="tab-mensal" class="btn btn-primary btn-sm">Por Mes</button>
  <button onclick="showTab('detalhe')" id="tab-detalhe" class="btn btn-ghost btn-sm">Por Factura / Cliente</button>
</div>

<div id="view-mensal" class="card">
  <div class="card-title">Historico Mensal de Vendas</div>
  <div class="table-wrap" style="margin:0;max-height:350px;overflow-y:auto">
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
          <td>
            {% if media_m > 0 %}{% set ratio = v.total / media_m %}
            <span style="font-size:11px;color:var(--text-muted)">{{ '%+.0f'|format((ratio-1)*100) }}%</span>
            {% else %}-{% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<div id="view-detalhe" class="card" style="display:none;margin-top:0">
  <div class="card-title">Detalhe por Factura / Cliente</div>
  {% if vendas_detalhe %}
  <div class="table-wrap" style="margin:0;max-height:350px;overflow-y:auto">
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
          <td style="text-align:right;font-size:12px;color:var(--text-muted)">
            {% if v.preco_venda %}{{ '%.2f'|format(v.preco_venda) }}EUR{% else %}-{% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px">Sem dados de detalhe (PHC nao ligado)</div>
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

'''
    src = src.replace('\n{% endblock %}', new_section + '\n{% endblock %}')
    print("OK: Secção adicionada")

with open('templates/reposicao_artigo.html', 'w', encoding='utf-8') as f:
    f.write(src)

with open('templates/reposicao_artigo.html', encoding='utf-8') as f:
    check = f.read()
print("view-detalhe:", 'view-detalhe' in check)
print("num_fatura:", 'num_fatura' in check)
print("Nr. Factura:", 'Nr. Factura' in check)
