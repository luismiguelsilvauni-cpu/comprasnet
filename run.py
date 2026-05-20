import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db

with app.app_context():
    db.create_all()

# Start automatic backup scheduler
try:
    from backup_manager import iniciar_scheduler
    iniciar_scheduler(app)
except Exception as e:
    import logging
    logging.getLogger(__name__).error(f"Erro ao iniciar scheduler de backup: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
