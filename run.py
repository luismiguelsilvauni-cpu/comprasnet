import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
