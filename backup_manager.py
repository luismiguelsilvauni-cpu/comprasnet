"""
backup_manager.py
─────────────────
Automated and manual backup of ComprasNet SQLite database.
"""

import os, shutil, logging, threading, time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_scheduler_thread = None
_stop_event = threading.Event()
_last_backup_check = None  # Track last date we ran backup


def _backup_filename() -> str:
    return f"comprasnet_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"


def _cleanup_old_backups(path: str, manter_dias: int):
    if not os.path.isdir(path):
        return
    cutoff = datetime.now() - timedelta(days=manter_dias)
    for fname in os.listdir(path):
        if fname.startswith('comprasnet_backup_') and fname.endswith('.db'):
            fpath = os.path.join(path, fname)
            try:
                if datetime.fromtimestamp(os.path.getmtime(fpath)) < cutoff:
                    os.remove(fpath)
                    logger.info(f"Backup antigo removido: {fname}")
            except Exception as e:
                logger.warning(f"Erro ao remover {fname}: {e}")


def _get_db_path(app):
    for candidate in [
        os.path.join(app.instance_path, 'compras.db'),
        os.path.join(os.path.dirname(app.instance_path), 'instance', 'compras.db'),
        os.path.join(os.path.dirname(app.root_path), 'instance', 'compras.db'),
    ]:
        if os.path.exists(candidate):
            return candidate
    return None


def fazer_backup(app, cfg=None) -> tuple:
    with app.app_context():
        if cfg is None:
            from models import ConfigGeral
            cfg = ConfigGeral.query.first()

        db_path = _get_db_path(app)
        if not db_path:
            return False, "Base de dados não encontrada."

        filename = _backup_filename()
        results = []
        ok = True

        local = (cfg.backup_local_path or 'backups').strip() if cfg else 'backups'
        destinations = []
        if not os.path.isabs(local):
            local = os.path.join(os.path.dirname(db_path), local)
        destinations.append(('local', os.path.normpath(local)))

        if cfg and cfg.backup_rede_path and cfg.backup_rede_path.strip():
            destinations.append(('rede', cfg.backup_rede_path.strip()))

        for dest_type, dest_path in destinations:
            try:
                os.makedirs(dest_path, exist_ok=True)
                dest_file = os.path.join(dest_path, filename)
                shutil.copy2(db_path, dest_file)
                size_kb = os.path.getsize(dest_file) // 1024
                results.append(f"✅ {dest_type}: {dest_path} ({size_kb} KB)")
                _cleanup_old_backups(dest_path, cfg.backup_manter_dias if cfg else 30)
            except Exception as e:
                ok = False
                results.append(f"❌ {dest_type} ({dest_path}): {e}")

        try:
            from models import db, ConfigGeral
            if cfg:
                cfg.ultimo_backup = datetime.utcnow()
                cfg.ultimo_backup_ok = ok
                db.session.commit()
        except Exception:
            pass

        msg = f"Backup '{filename}'\n" + "\n".join(results)
        logger.info(msg)
        return ok, msg


def listar_backups(app, cfg=None) -> list:
    with app.app_context():
        if cfg is None:
            from models import ConfigGeral
            cfg = ConfigGeral.query.first()
        db_path = _get_db_path(app) or ''
        local = (cfg.backup_local_path or 'backups').strip() if cfg else 'backups'
        if not os.path.isabs(local):
            local = os.path.join(os.path.dirname(db_path), local)
        local = os.path.normpath(local)
        backups = []
        if os.path.isdir(local):
            for fname in sorted(os.listdir(local), reverse=True):
                if fname.startswith('comprasnet_backup_') and fname.endswith('.db'):
                    fpath = os.path.join(local, fname)
                    try:
                        stat = os.stat(fpath)
                        backups.append({
                            'nome': fname,
                            'caminho': fpath,
                            'tamanho': stat.st_size // 1024,
                            'data': datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M'),
                        })
                    except Exception:
                        pass
        return backups


# ── Scheduler (fixed) ──────────────────────────────────────────────────────────

def _scheduler_loop(app, get_cfg_fn):
    global _last_backup_check
    logger.info("Backup scheduler iniciado.")
    while not _stop_event.is_set():
        try:
            with app.app_context():
                cfg = get_cfg_fn()
                if cfg and cfg.backup_auto_ativo:
                    hora_str = cfg.backup_hora or '02:00'
                    h, m = map(int, hora_str.split(':'))
                    now = datetime.now()
                    today_target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    today_str = now.strftime('%Y-%m-%d')

                    # Run if we're within 2 minutes of target and haven't run today
                    diff = abs((now - today_target).total_seconds())
                    if diff < 120 and _last_backup_check != today_str:
                        logger.info("A executar backup automático agendado...")
                        _last_backup_check = today_str
                        fazer_backup(app, cfg)
                else:
                    pass
        except Exception as e:
            logger.error(f"Erro no scheduler de backup: {e}")

        # Check every 60 seconds
        _stop_event.wait(60)


def iniciar_scheduler(app):
    global _scheduler_thread, _stop_event
    _stop_event.clear()

    def get_cfg():
        from models import ConfigGeral
        return ConfigGeral.query.first()

    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, args=(app, get_cfg),
        daemon=True, name='BackupScheduler'
    )
    _scheduler_thread.start()
    logger.info("Backup scheduler thread iniciada.")


def parar_scheduler():
    _stop_event.set()


def fazer_backup_completo(app, cfg=None) -> tuple:
    """
    Full backup: SQLite DB + uploads folder → ZIP archive.
    Includes: database, uploaded PDFs, photos, manuals, embarcacoes files.
    """
    import zipfile
    with app.app_context():
        if cfg is None:
            from models import ConfigGeral
            cfg = ConfigGeral.query.first()

        db_path = _get_db_path(app)
        if not db_path:
            return False, "Base de dados não encontrada."

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_name = f"comprasnet_backup_{ts}.zip"

        local = (cfg.backup_local_path or 'backups').strip() if cfg else 'backups'
        if not os.path.isabs(local):
            local = os.path.join(os.path.dirname(db_path), local)
        local = os.path.normpath(local)
        os.makedirs(local, exist_ok=True)

        zip_path = os.path.join(local, zip_name)
        results = []
        ok = True

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 1. Database
                zf.write(db_path, 'compras.db')
                results.append('✅ Base de dados')

                # 2. Uploads folder
                uploads_dir = os.path.join(os.path.dirname(db_path), 'uploads')
                if os.path.isdir(uploads_dir):
                    count = 0
                    for root, dirs, files in os.walk(uploads_dir):
                        for fname in files:
                            fpath = os.path.join(root, fname)
                            arcname = os.path.relpath(fpath, os.path.dirname(uploads_dir))
                            zf.write(fpath, arcname)
                            count += 1
                    results.append(f'✅ Uploads ({count} ficheiros)')

            size_mb = os.path.getsize(zip_path) / 1024 / 1024
            results.append(f'📦 {zip_name} ({size_mb:.1f} MB)')

            # Copy to network if configured
            if cfg and cfg.backup_rede_path and cfg.backup_rede_path.strip():
                try:
                    import shutil
                    shutil.copy2(zip_path, os.path.join(cfg.backup_rede_path.strip(), zip_name))
                    results.append(f'✅ Rede: {cfg.backup_rede_path}')
                except Exception as e:
                    results.append(f'❌ Rede: {e}')

            _cleanup_old_backups(local, cfg.backup_manter_dias if cfg else 30)

        except Exception as e:
            ok = False
            results.append(f'❌ Erro: {e}')

        try:
            from models import db
            if cfg:
                cfg.ultimo_backup = datetime.utcnow()
                cfg.ultimo_backup_ok = ok
                db.session.commit()
        except Exception:
            pass

        return ok, '\n'.join(results)
