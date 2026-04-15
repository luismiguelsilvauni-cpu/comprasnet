"""Re-import recibo values directly from Excel, overwriting existing DB records."""
import sys, os, glob
sys.path.insert(0, os.path.dirname(__file__))

# Find Excel files in uploads/salarios
upload_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'salarios')
xls_files = glob.glob(os.path.join(upload_dir, '*.xls')) + \
            glob.glob(os.path.join(upload_dir, '*.xlsx'))

if xls_files:
    print("Ficheiros encontrados em uploads/salarios:")
    for i, f in enumerate(xls_files):
        print(f"  {i+1}. {os.path.basename(f)}")
    choice = input("Escolha o nº do ficheiro (Enter=1): ").strip()
    idx = int(choice)-1 if choice.isdigit() else 0
    xls_path = xls_files[idx]
else:
    xls_path = input("Caminho completo do ficheiro Excel: ").strip()

if not os.path.exists(xls_path):
    print(f"ERRO: ficheiro não encontrado: {xls_path}")
    sys.exit(1)

print(f"\nA ler: {os.path.basename(xls_path)}")

from app import app, _parse_recibos_excel, ReciboSalario, Funcionario, MESES_LABELS
from models import db
from datetime import datetime

with app.app_context():
    resultado = _parse_recibos_excel(xls_path)
    print(f"Encontrados {len(resultado)} recibo(s):\n")

    meses_nomes = {v.lower(): k for k, v in MESES_LABELS.items()}

    for rec in resultado:
        print(f"  Sheet: {rec['sheet']}")
        print(f"    Funcionário detectado: {rec.get('func_match_nome','—')} (ID={rec.get('func_match_id','?')})")
        print(f"    Mês global Excel: '{rec.get('mes_global','')}'")
        print(f"    vencimento_base={rec.get('vencimento_base')}, rht={rec.get('vencimento_base_rht')}")
        print(f"    irs_taxa={rec.get('irs_taxa')}, irs_parcela={rec.get('irs_parcela_abater')}, irs_tx_ef={rec.get('irs_taxa_efetiva')}")
        print(f"    irs_base={rec.get('irs_base')}, irs={rec.get('irs')}")
        print(f"    seg_social_taxa={rec.get('seg_social_taxa')}, seg_social_base={rec.get('seg_social_base')}, seg_social={rec.get('seg_social')}")
        print(f"    liquido={rec.get('liquido')}")

        fid = rec.get('func_match_id')
        if not fid:
            alt = input("    Sem match auto. Introduza o ID do funcionário (ou Enter para saltar): ").strip()
            if not alt:
                print("    SALTO\n"); continue
            fid = int(alt)

        # Determine year
        ano_str = input(f"    Ano (Enter=2026): ").strip()
        ano = int(ano_str) if ano_str.isdigit() else 2026

        # Determine month
        mes_global = rec.get('mes_global', '').strip().lower()
        mes_auto = meses_nomes.get(mes_global)
        if mes_auto:
            print(f"    Mês detectado: {rec.get('mes_global')} → {mes_auto}")
            mes_str = input(f"    Confirmar mês {mes_auto} (Enter=confirmar, ou introduza número): ").strip()
            mes = int(mes_str) if mes_str.isdigit() else mes_auto
        else:
            mes_str = input(f"    Mês (1-14, ex: 3=Março): ").strip()
            mes = int(mes_str) if mes_str.isdigit() else 3

        # Update or create
        r = ReciboSalario.query.filter_by(funcionario_id=fid, ano=ano, mes=mes).first()
        if r:
            print(f"    A actualizar recibo existente ID={r.id}...")
        else:
            r = ReciboSalario(funcionario_id=fid, ano=ano, mes=mes,
                              mes_label=MESES_LABELS.get(mes, f'Mês {mes}'))
            db.session.add(r)
            print(f"    A criar novo recibo...")

        r.vencimento_base      = rec.get('vencimento_base', 0)
        r.vencimento_base_rht  = rec.get('vencimento_base_rht', 0)
        r.vencimento_base_g    = rec.get('vencimento_base_g', 0)
        r.premios              = rec.get('premios', 0)
        r.faltas_dias          = rec.get('faltas_dias', 0)
        r.faltas_horas         = rec.get('faltas_horas', 0)
        r.horas_extra          = rec.get('horas_extra_horas', 0)
        r.horas_extra_rht      = rec.get('horas_extra_rht', 0)
        r.sub_refeicao_dias    = rec.get('sub_refeicao_dias', 0)
        r.sub_refeicao_vdia    = rec.get('sub_refeicao_vdia', 0)
        r.subsidio_refeicao    = rec.get('subsidio_refeicao', 0)
        r.outros_abonos        = rec.get('outros_abonos', 0)
        r.total_abonos         = rec.get('total_iliquido', 0)
        r.seg_social_taxa      = rec.get('seg_social_taxa', 0)
        r.seg_social_base      = rec.get('seg_social_base', 0)
        r.seg_social_func      = rec.get('seg_social', 0)
        r.irs_taxa             = rec.get('irs_taxa', 0)
        r.irs_parcela_abater   = rec.get('irs_parcela_abater', 0)
        r.irs_taxa_efetiva     = rec.get('irs_taxa_efetiva', 0)
        r.irs_base             = rec.get('irs_base', 0)
        r.irs_retencao         = rec.get('irs', 0)
        r.total_descontos      = rec.get('total_descontos', 0)
        r.liquido              = rec.get('liquido', 0)
        r.estado               = 'processado'
        r.notas                = f"Importado de Excel: {rec.get('sheet','')}"
        r.atualizado_em        = datetime.now()

        db.session.commit()
        print(f"    ✅ Gravado: venc={r.vencimento_base} | rht={r.vencimento_base_rht} | irs_taxa={r.irs_taxa} | parcela={r.irs_parcela_abater} | tx_ef={r.irs_taxa_efetiva} | líquido={r.liquido}\n")

print("Concluído.")
