import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'compras.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Tabelas ausencias
cur.execute("""CREATE TABLE IF NOT EXISTS ausencia_registos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionario(id),
    tipo VARCHAR(30) NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    ano INTEGER NOT NULL,
    formato VARCHAR(10) DEFAULT 'dia',
    horas REAL DEFAULT 0,
    dias_uteis REAL DEFAULT 0,
    estado VARCHAR(20) DEFAULT 'aprovado',
    aprovado_por INTEGER,
    aprovado_em DATETIME,
    observacoes TEXT DEFAULT '',
    tem_documento BOOLEAN DEFAULT 0,
    documento_path VARCHAR(300),
    criado_por INTEGER,
    criado_em DATETIME,
    alterado_por INTEGER,
    alterado_em DATETIME)""")
cur.execute("CREATE INDEX IF NOT EXISTS ix_ausencias_func_ano ON ausencia_registos(funcionario_id, ano)")

cur.execute("""CREATE TABLE IF NOT EXISTS ausencia_saldos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionario(id),
    ano INTEGER NOT NULL,
    dias_direito REAL DEFAULT 22,
    dias_ajuste REAL DEFAULT 0,
    notas_ajuste VARCHAR(300) DEFAULT '',
    dias_gozados REAL DEFAULT 0,
    dias_restantes REAL DEFAULT 0,
    UNIQUE(funcionario_id, ano))""")

cur.execute("""CREATE TABLE IF NOT EXISTS empresa_fechos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ano INTEGER NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    descricao VARCHAR(200) DEFAULT '',
    criado_por INTEGER,
    criado_em DATETIME)""")

# Período salarial em config_geral
cfg_cols = [r[1] for r in cur.execute("PRAGMA table_info(config_geral)").fetchall()]
for col, typ, default in [
    ('salario_dia_inicio', 'INTEGER', '1'),
    ('salario_dia_fecho',  'INTEGER', '27'),
]:
    if col not in cfg_cols:
        cur.execute(f"ALTER TABLE config_geral ADD COLUMN {col} {typ} DEFAULT {default}")
        print(f"OK: config_geral.{col}")
    else:
        print(f"ok: {col} ja existe")

conn.commit()
conn.close()
print("Concluido.")

# Periodos salariais
cur.execute("""CREATE TABLE IF NOT EXISTS periodos_salariais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ano INTEGER NOT NULL,
    mes INTEGER NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    estado VARCHAR(10) DEFAULT 'aberto',
    notas TEXT DEFAULT '',
    criado_por INTEGER,
    criado_em DATETIME,
    fechado_por INTEGER,
    fechado_em DATETIME,
    UNIQUE(ano, mes))""")

# Horas extra
cur.execute("""CREATE TABLE IF NOT EXISTS horas_extra (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionario(id),
    periodo_id INTEGER REFERENCES periodos_salariais(id),
    data DATE NOT NULL,
    hora_inicio VARCHAR(5) NOT NULL,
    hora_fim VARCHAR(5) NOT NULL,
    total_horas REAL DEFAULT 0,
    categoria VARCHAR(20) DEFAULT 'dia_util',
    estado VARCHAR(20) DEFAULT 'pendente',
    observacoes TEXT DEFAULT '',
    criado_por INTEGER,
    criado_em DATETIME,
    alterado_por INTEGER,
    alterado_em DATETIME)""")

# Config horario
cur.execute("""CREATE TABLE IF NOT EXISTS config_horario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hora_inicio VARCHAR(5) DEFAULT '08:30',
    hora_fim VARCHAR(5) DEFAULT '17:30',
    horas_dia REAL DEFAULT 8.0,
    pausa_almoco REAL DEFAULT 1.0)""")
# Insert default if empty
if cur.execute("SELECT COUNT(*) FROM config_horario").fetchone()[0] == 0:
    cur.execute("INSERT INTO config_horario (hora_inicio,hora_fim,horas_dia,pausa_almoco) VALUES ('08:30','17:30',8.0,1.0)")
    print("OK: config_horario default inserido")

conn.commit()
conn.close()
print("Concluido.")
