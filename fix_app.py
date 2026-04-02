"""fix_app.py - Corrige o app.py localmente"""
import re

with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

fixes = 0

# Fix 1: Add session to flask imports
if 'send_from_directory, session' not in src:
    src = src.replace(
        'from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory',
        'from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session'
    )
    print("✅ session importado")
    fixes += 1
else:
    print("✅ session já importado")

# Fix 2: Remove before_request that uses session
old_before = '''@app.before_request
def make_session_permanent():
    session.permanent = True

'''
if old_before in src:
    src = src.replace(old_before, '')
    print("✅ before_request removido")
    fixes += 1
else:
    print("✅ before_request já removido")

# Fix 3: Remove ensure_sqlserver_running logger calls
src = src.replace('            logger.info("✅ SQL Server já está a correr")',
                  '            print("SQL Server a correr")')
src = src.replace('            logger.info("🔄 A iniciar SQL Server Express...")',
                  '            print("A iniciar SQL Server...")')
src = src.replace('                logger.info("✅ SQL Server iniciado com sucesso")',
                  '                print("SQL Server iniciado")')
src = src.replace('                logger.warning(f"⚠️  Não foi possível iniciar SQL Server: {start.stdout}")',
                  '                print(f"Aviso SQL Server: {start.stdout}")')
src = src.replace('        logger.warning(f"⚠️  Erro ao verificar SQL Server: {e}")',
                  '        print(f"Erro SQL Server: {e}")')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(src)

print(f"\n✅ app.py corrigido ({fixes} alterações). Reinicie o servidor.")
