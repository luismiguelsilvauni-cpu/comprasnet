import sys, os
sys.path.insert(0, '.')

from app import app, db, init_db

with app.app_context():
    # Get DB path
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    print("DB URI:", uri)
    
    # Create all tables including backlog_item
    db.create_all()
    print("db.create_all() done")
    
    # Check
    from sqlalchemy import text
    with db.engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM backlog_item")).fetchone()[0]
        print("Items:", n)
