"""
bak_restore.py
──────────────
Restauro automático de ficheiro .bak do PHC CS num SQL Server Express local.
Não requer SSMS — usa apenas T-SQL via pyodbc.

Fluxo:
  1. Upload do .bak pelo utilizador no browser
  2. Ficheiro guardado em bak_uploads/
  3. Ligação ao SQL Server Express (master DB)
  4. RESTORE DATABASE com o caminho do .bak
  5. Sincronização automática dos artigos/fornecedores

Requisitos no PC servidor:
  - SQL Server Express instalado (aka.ms/sqlserver2022express)
  - ODBC Driver 17 ou 18 for SQL Server
  - Utilizador SA ativo (ou Windows Authentication)
"""

import os
import logging
import pyodbc
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Conexão ao master (para operações de restauro) ────────────────────────────

def get_master_connection(cfg):
    """
    Connect to the 'master' database on local SQL Server Express.
    Restauro requer ligação à master, não à BD do PHC.
    """
    drivers = [
        'ODBC Driver 18 for SQL Server',
        'ODBC Driver 17 for SQL Server',
        'SQL Server Native Client 11.0',
        'SQL Server',
    ]
    last_err = None
    for driver in drivers:
        try:
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={cfg.servidor},{cfg.porta};"
                f"DATABASE=master;"
                f"autocommit=True;"
            )
            if cfg.autenticacao == 'windows':
                conn_str += "Trusted_Connection=yes;"
            else:
                conn_str += f"UID={cfg.utilizador};PWD={cfg.password};"
            if 'ODBC Driver 18' in driver:
                conn_str += "TrustServerCertificate=yes;"

            conn = pyodbc.connect(conn_str, timeout=15, autocommit=True)
            return conn
        except pyodbc.Error as e:
            last_err = e
    raise ConnectionError(f"Não foi possível ligar ao SQL Server: {last_err}")


# ── Verificações ──────────────────────────────────────────────────────────────

def check_sqlserver_available(cfg) -> tuple[bool, str]:
    """Ping SQL Server Express — check it's running."""
    try:
        conn = get_master_connection(cfg)
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0].split('\n')[0].strip()
        conn.close()
        return True, f"SQL Server encontrado: {version}"
    except ConnectionError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Erro: {e}"


def get_sql_data_path(cfg) -> str:
    """
    Get default SQL Server data directory.
    The .bak file must be accessible from here (or use MOVE in RESTORE).
    """
    try:
        conn = get_master_connection(cfg)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SERVERPROPERTY('InstanceDefaultDataPath') AS data_path,
                   SERVERPROPERTY('InstanceDefaultLogPath')  AS log_path
        """)
        row = cursor.fetchone()
        conn.close()
        return str(row[0] or ''), str(row[1] or '')
    except Exception:
        return '', ''


def get_backup_file_info(cfg, bak_path: str) -> tuple[list, str | None]:
    """
    Read the logical file names inside the .bak using RESTORE FILELISTONLY.
    Returns (file_list, error).
    """
    try:
        conn = get_master_connection(cfg)
        cursor = conn.cursor()
        cursor.execute(f"RESTORE FILELISTONLY FROM DISK = N'{bak_path}'")
        files = []
        for row in cursor.fetchall():
            files.append({
                'logical_name': row[0],
                'physical_name': row[1],
                'type': row[2],  # D=Data, L=Log
            })
        conn.close()
        return files, None
    except Exception as e:
        return [], str(e)


# ── Restauro ──────────────────────────────────────────────────────────────────

def restore_bak(cfg, bak_path: str, progress_callback=None) -> tuple[bool, str]:
    """
    Restore a .bak file to the SQL Server Express instance.

    cfg        : ConfigPHC instance (servidor, porta, utilizador, password, base_dados)
    bak_path   : full Windows path to the .bak file (e.g. C:\\bak_uploads\\phc.bak)
    progress_callback : optional function(message: str) for status updates

    Returns (success, message).
    """

    def log(msg):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    db_name = cfg.base_dados or 'PHC'

    # 1. Check SQL Server is available
    log("A verificar SQL Server Express...")
    ok, msg = check_sqlserver_available(cfg)
    if not ok:
        return False, msg

    # 2. Read logical file names from backup
    log("A ler estrutura do ficheiro .bak...")
    files, err = get_backup_file_info(cfg, bak_path)
    if err:
        return False, f"Erro ao ler .bak: {err}\n\nVerifique que o SQL Server tem permissão de leitura na pasta onde guardou o .bak."
    if not files:
        return False, "Ficheiro .bak vazio ou inválido."

    log(f"  → {len(files)} ficheiro(s) lógico(s) encontrado(s)")

    # 3. Get SQL Server data/log paths
    data_path, log_path = get_sql_data_path(cfg)
    if not data_path:
        data_path = f"C:\\Program Files\\Microsoft SQL Server\\MSSQL16.SQLEXPRESS\\MSSQL\\DATA\\"
    if not log_path:
        log_path = data_path

    # 4. Build MOVE clauses so SQL Server places files in its own data dir
    move_clauses = []
    for f in files:
        logical = f['logical_name']
        if f['type'] == 'L':  # Log file
            dest = os.path.join(log_path, f"{db_name}_log.ldf")
        else:  # Data file
            dest = os.path.join(data_path, f"{db_name}.mdf")
        move_clauses.append(f"MOVE N'{logical}' TO N'{dest}'")

    move_sql = ', '.join(move_clauses)

    # 5. Drop existing DB if present (WITH NO_WAIT to force)
    log(f"A preparar base de dados '{db_name}'...")
    try:
        conn = get_master_connection(cfg)
        cursor = conn.cursor()

        # Check if DB exists
        cursor.execute(f"SELECT COUNT(*) FROM sys.databases WHERE name = N'{db_name}'")
        exists = cursor.fetchone()[0] > 0

        if exists:
            log(f"  → Base de dados '{db_name}' já existe. A substituir...")
            # Set single user to drop connections
            cursor.execute(f"""
                ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE
            """)
            cursor.execute(f"DROP DATABASE [{db_name}]")
            log(f"  → Base de dados anterior removida.")

        conn.close()
    except Exception as e:
        return False, f"Erro ao preparar BD: {e}"

    # 6. RESTORE
    log("A restaurar .bak... (pode demorar 1-3 minutos)")
    restore_sql = f"""
        RESTORE DATABASE [{db_name}]
        FROM DISK = N'{bak_path}'
        WITH {move_sql},
             REPLACE,
             RECOVERY,
             STATS = 10
    """
    try:
        conn = get_master_connection(cfg)
        cursor = conn.cursor()
        cursor.execute(restore_sql)

        # Consume all result sets (STATS generates messages)
        while cursor.nextset():
            pass

        conn.close()
        log(f"✅ Base de dados '{db_name}' restaurada com sucesso.")
        return True, f"Restauro concluído. Base de dados '{db_name}' pronta."

    except pyodbc.Error as e:
        err_msg = str(e)
        if '3234' in err_msg or 'logical file' in err_msg.lower():
            return False, (
                "Erro nos ficheiros lógicos do backup.\n"
                "O .bak pode ser de uma versão diferente do SQL Server.\n"
                f"Detalhe: {err_msg}"
            )
        elif 'permission' in err_msg.lower() or '5' in err_msg:
            return False, (
                "Sem permissão para restaurar.\n"
                "Verifique que o utilizador SQL tem a role 'dbcreator' ou 'sysadmin'.\n"
                f"Detalhe: {err_msg}"
            )
        else:
            return False, f"Erro no restauro: {err_msg}"
    except Exception as e:
        return False, f"Erro inesperado: {e}"


# ── Verificar se BD restaurada é PHC CS ──────────────────────────────────────

def verify_phc_database(cfg) -> tuple[bool, str, dict]:
    """
    After restore, verify the DB has expected PHC CS tables.
    Returns (ok, message, stats).
    """
    stats = {}
    try:
        from phc_sync import get_phc_connection
        conn = get_phc_connection(cfg)
        cursor = conn.cursor()

        # Check key PHC tables exist
        for table in ['st', 'ec']:
            cursor.execute(f"""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = '{table}'
            """)
            if cursor.fetchone()[0] == 0:
                conn.close()
                return False, (
                    f"Tabela '{table}' não encontrada.\n"
                    "Este .bak não parece ser uma base de dados PHC CS."
                ), {}

        # Count records
        cursor.execute("SELECT COUNT(*) FROM st WHERE ISNULL(inactivo,0)=0")
        stats['artigos'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM ec WHERE fornecedor=1 AND ISNULL(inactivo,0)=0")
        stats['fornecedores'] = cursor.fetchone()[0]

        conn.close()
        return True, (
            f"Base de dados PHC CS válida — "
            f"{stats['artigos']} artigos, {stats['fornecedores']} fornecedores."
        ), stats

    except Exception as e:
        return False, f"Erro ao verificar BD: {e}", {}
