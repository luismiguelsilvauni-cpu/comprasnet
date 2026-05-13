import sys
sys.path.insert(0, '.')
from app import app, db
from sqlalchemy import text

with app.app_context():
    # Check all equipamento_documento records
    rows = db.session.execute(text(
        "SELECT id, equipamento_id, componente, titulo, pdf_filename FROM equipamento_documento ORDER BY id DESC LIMIT 20"
    )).fetchall()
    
    print(f"Total documentos: {len(rows)}")
    for r in rows:
        print(f"  id={r[0]} eid={r[1]} comp={r[2]} titulo={r[3][:40]} file={r[4]}")
    
    # Check outros_bulk specifically
    bulk = db.session.execute(text(
        "SELECT id, equipamento_id, titulo FROM equipamento_documento WHERE componente='outros_bulk'"
    )).fetchall()
    print(f"\noutros_bulk: {len(bulk)} registos")
    for r in bulk:
        print(f"  id={r[0]} eid={r[1]} titulo={r[2]}")
