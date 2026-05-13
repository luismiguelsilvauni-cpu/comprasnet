import re

with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

# Replace logger calls inside ensure_sqlserver_running with print
old = '''def ensure_sqlserver_running():
    """Start SQL Server Express if not running."""
    import subprocess, time'''

new = '''def ensure_sqlserver_running():
    """Start SQL Server Express if not running."""
    import subprocess, time
    import logging as _logging
    _log = _logging.getLogger("sqlserver")'''

src = src.replace(old, new)

# Replace all logger. with _log. inside this function only
# Simple approach: replace all occurrences of logger. in the function
src = src.replace(
    '            logger.info("✅ SQL Server já está a correr")',
    '            _log.info("SQL Server ja esta a correr")'
)
src = src.replace(
    '            logger.info("🔄 A iniciar SQL Server Express...")',
    '            _log.info("A iniciar SQL Server Express...")'
)
src = src.replace(
    '                logger.info("✅ SQL Server iniciado com sucesso")',
    '                _log.info("SQL Server iniciado")'
)
src = src.replace(
    '                logger.warning(f"⚠️  Não foi possível iniciar SQL Server: {start.stdout}")',
    '                _log.warning(f"Nao foi possivel iniciar SQL Server: {start.stdout}")'
)
src = src.replace(
    '        logger.warning(f"⚠️  Erro ao verificar SQL Server: {e}")',
    '        _log.warning(f"Erro SQL Server: {e}")'
)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(src)

print("OK - ficheiro corrigido")
