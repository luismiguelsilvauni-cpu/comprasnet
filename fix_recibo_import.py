"""Fix incorrectly imported recibo values by re-parsing from Excel."""
import sys, os, xlrd
sys.path.insert(0, os.path.dirname(__file__))

xls_path = input("Caminho para o ficheiro Excel (Enter para em_testes.xls): ").strip()
if not xls_path:
    xls_path = os.path.join(os.path.dirname(__file__), 'uploads', 'salarios', 'em_testes.xls')
    if not os.path.exists(xls_path):
        xls_path = input("Ficheiro não encontrado. Caminho completo: ").strip()

from app import app
from models import db

with app.app_context():
    # Import the parse function
    from app import _parse_recibos_excel, ReciboSalario, Funcionario, MESES_LABELS
    from datetime import datetime

    resultado = _parse_recibos_excel(xls_path)
    print(f"\nEncontrados {len(resultado)} recibo(s) no Excel:")

    for rec in resultado:
        print(f"\n  Sheet: {rec['sheet']}")
        print(f"  vencimento_base: {rec.get('vencimento_base')}")
        print(f"  vencimento_base_rht: {rec.get('vencimento_base_rht')}")
        print(f"  irs_taxa: {rec.get('irs_taxa')}")
        print(f"  irs_base: {rec.get('irs_base')}")
        print(f"  irs: {rec.get('irs')}")
        print(f"  seg_social_taxa: {rec.get('seg_social_taxa')}")
        print(f"  seg_social_base: {rec.get('seg_social_base')}")
        print(f"  seg_social: {rec.get('seg_social')}")

        fid = rec.get('func_match_id')
        if not fid:
            print(f"  SKIP: sem funcionário associado")
            continue

        ano = int(input(f"  Ano do recibo (Enter=2026): ").strip() or 2026)
        mes = int(input(f"  Mês (1-14, Enter=3 para Março): ").strip() or 3)

        r = ReciboSalario.query.filter_by(funcionario_id=fid, ano=ano, mes=mes).first()
        if r:
            print(f"  Actualizando recibo ID {r.id}...")
        else:
            r = ReciboSalario(funcionario_id=fid, ano=ano, mes=mes,
                mes_label=MESES_LABELS.get(mes, f'Mês {mes}'))
            db.session.add(r)
            print(f"  Criando novo recibo...")

        r.vencimento_base     = rec.get('vencimento_base', 0)
        r.vencimento_base_rht = rec.get('vencimento_base_rht', 0)
        r.vencimento_base_g   = rec.get('vencimento_base_g', 0)
        r.premios             = rec.get('premios', 0)
        r.faltas_dias         = rec.get('faltas_dias', 0)
        r.faltas_horas        = rec.get('faltas_horas', 0)
        r.horas_extra         = rec.get('horas_extra_horas', 0)
        r.horas_extra_rht     = rec.get('horas_extra_rht', 0)
        r.sub_refeicao_dias   = rec.get('sub_refeicao_dias', 0)
        r.sub_refeicao_vdia   = rec.get('sub_refeicao_vdia', 0)
        r.subsidio_refeicao   = rec.get('subsidio_refeicao', 0)
        r.outros_abonos       = rec.get('outros_abonos', 0)
        r.total_abonos        = rec.get('total_iliquido', 0)
        r.seg_social_taxa     = rec.get('seg_social_taxa', 0)
        r.seg_social_base     = rec.get('seg_social_base', 0)
        r.seg_social_func     = rec.get('seg_social', 0)
        r.irs_taxa            = rec.get('irs_taxa', 0)
        r.irs_base            = rec.get('irs_base', 0)
        r.irs_retencao        = rec.get('irs', 0)
        r.total_descontos     = rec.get('total_descontos', 0)
        r.liquido             = rec.get('liquido', 0)
        r.estado              = 'processado'
        r.atualizado_em       = datetime.now()
        db.session.commit()
        print(f"  ✅ Recibo corrigido: vencimento={r.vencimento_base}, IRS taxa={r.irs_taxa}, IRS={r.irs_retencao}, líquido={r.liquido}")

print("\nConcluído.")
