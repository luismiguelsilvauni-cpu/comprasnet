import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app, db, FornecedorPHC, LinhaPedido

with app.app_context():
    count = FornecedorPHC.query.count()
    print(f"FornecedorPHC local: {count} registos")
    if count > 0:
        sample = FornecedorPHC.query.limit(3).all()
        for f in sample:
            print(f"  - {f.no}: {f.nome}")
    
    # Check fornecedor_hab in linhas
    forn_habs = db.session.query(LinhaPedido.fornecedor_hab)\
        .filter(LinhaPedido.fornecedor_hab != None)\
        .filter(LinhaPedido.fornecedor_hab != '')\
        .distinct().limit(10).all()
    print(f"\nFornec. Hab. em pedidos: {len(forn_habs)}")
    for f in forn_habs:
        print(f"  - {f[0]}")
