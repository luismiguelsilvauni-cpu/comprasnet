with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

if 'def init_db' in src:
    print("init_db ja existe")
else:
    func = """
def init_db():
    with app.app_context():
        db.create_all()

"""
    src = src.replace("\nif __name__ == '__main__':", func + "\nif __name__ == '__main__':")
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("OK: init_db adicionado")
