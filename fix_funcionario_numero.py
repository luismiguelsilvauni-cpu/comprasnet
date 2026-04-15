"""Fix funcionario numero via direct DB update."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app, db
from models import Funcionario

with app.app_context():
    fid = input("ID do funcionário (ver URL na página): ").strip()
    novo_num = input("Novo número: ").strip()
    
    f = Funcionario.query.get(int(fid))
    if not f:
        print("Funcionário não encontrado")
        sys.exit(1)
    
    existente = Funcionario.query.filter_by(numero=novo_num).first()
    if existente and existente.id != f.id:
        print(f"ERRO: Nº {novo_num} já existe para {existente.nome}")
        sys.exit(1)
    
    print(f"Alterar {f.nome}: {f.numero} → {novo_num}")
    confirma = input("Confirmar? (s/n): ").strip().lower()
    if confirma == 's':
        f.numero = novo_num
        db.session.commit()
        print("OK: número actualizado")
    else:
        print("Cancelado")
