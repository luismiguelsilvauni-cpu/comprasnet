import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS fichas_tecnicas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero INTEGER NOT NULL UNIQUE,
    grupo_designacao VARCHAR(200) NOT NULL,
    grupo_marca VARCHAR(100) DEFAULT '',
    grupo_modelo VARCHAR(100) DEFAULT '',
    grupo_serie VARCHAR(100) DEFAULT '',
    grupo_ano VARCHAR(10) DEFAULT '',
    motor_marca VARCHAR(100) DEFAULT '',
    motor_modelo VARCHAR(100) DEFAULT '',
    motor_serie VARCHAR(100) DEFAULT '',
    motor_potencia VARCHAR(50) DEFAULT '',
    motor_cilindros VARCHAR(20) DEFAULT '',
    cliente_nome VARCHAR(200) DEFAULT '',
    observacoes TEXT DEFAULT '',
    criado_por INTEGER, criado_em DATETIME, atualizado_em DATETIME)""")

cur.execute("""CREATE TABLE IF NOT EXISTS ficha_componentes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ficha_id INTEGER NOT NULL REFERENCES fichas_tecnicas(id),
    categoria VARCHAR(100) DEFAULT 'Geral',
    ordem INTEGER DEFAULT 0,
    designacao VARCHAR(200) NOT NULL,
    part_number VARCHAR(100) DEFAULT '',
    marca VARCHAR(100) DEFAULT '',
    referencia_equiv VARCHAR(200) DEFAULT '',
    quantidade VARCHAR(20) DEFAULT '1',
    unidade VARCHAR(20) DEFAULT 'un',
    intervalo VARCHAR(100) DEFAULT '',
    notas VARCHAR(400) DEFAULT '')""")

cur.execute("""CREATE TABLE IF NOT EXISTS ficha_documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ficha_id INTEGER NOT NULL REFERENCES fichas_tecnicas(id),
    tipo VARCHAR(20) DEFAULT 'documento',
    nome_original VARCHAR(255) NOT NULL,
    nome_ficheiro VARCHAR(255) NOT NULL,
    descricao VARCHAR(300) DEFAULT '',
    tamanho INTEGER DEFAULT 0,
    mime VARCHAR(100) DEFAULT '',
    criado_por INTEGER, criado_em DATETIME)""")

conn.commit()
conn.close()
print("OK: tabelas fichas tecnicas criadas")
