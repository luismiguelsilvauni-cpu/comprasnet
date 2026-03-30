"""
backup_manager.py
─────────────────
Automated and manual backup of ComprasNet SQLite database.
Supports local folder and network share destinations.
Runs as a background thread with daily scheduling.
"""

import os
import shutil
import logging
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_scheduler_thread = None
_stop_event = threading.Event()


def _backup_filename() -> str:
    return f"comprasnet_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"


def _cleanup_old_backups(path: str, manter_dias: int):
    """Remove backup files older than manter_dias."""
    if not os.path.isdir(path):
        return
    cutoff = datetime.now() - timedelta(days=manter_dias)
    for fname in os.listdir(path):
        if fname.startswith('comprasnet_backup_') and fname.endswith('.db'):
            fpath = os.path.join(path, fname)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    os.remove(fpath)
                    logger.info(f"Backup antigo removido: {fname}")
            except Exception as e:
                logger.warning(f"Erro ao remover backup {fname}: {e}")


def fazer_backup(app, cfg=None) -> tuple[bool, str]:
    """
    Perform a backup of the SQLite database.
    Returns (success, message).
    """
    with app.app_context():
        if cfg is None:
            from models import ConfigGeral
            cfg = ConfigGeral.query.first()

        db_path = os.path.join(
            os.path.dirname(app.instance_path),
            'instance', 'compras.db'
        )
        if not os.path.exists(db_path):
            # Try instance_path directly
            db_path = os.path.join(app.instance_path, 'compras.db')
        if not os.path.exists(db_path):
            return False, "Base de dados não encontrada."

        filename = _backup_filename()
        results = []
        ok = True

        destinations = []
        local = (cfg.backup_local_path or 'backups').strip() if cfg else 'backups'
        if local:
            if not os.path.isabs(local):
                local = os.path.join(os.path.dirname(db_path), '..', local)
            destinations.append(('local', os.path.normpath(local)))

        if cfg and cfg.backup_rede_path and cfg.backup_rede_path.strip():
            destinations.append(('rede', cfg.backup_rede_path.strip()))

        if not destinations:
            destinations.append(('local', os.path.normpath(
                os.path.join(os.path.dirname(db_path), '..', 'backups')
            )))

        for dest_type, dest_path in destinations:
            try:
                os.makedirs(dest_path, exist_ok=True)
                dest_file = os.path.join(dest_path, filename)
                shutil.copy2(db_path, dest_file)
                size_kb = os.path.getsize(dest_file) // 1024
                results.append(f"✅ {dest_type}: {dest_path} ({size_kb} KB)")
                # Cleanup old
                manter = cfg.backup_manter_dias if cfg else 30
                _cleanup_old_backups(dest_path, manter)
            except Exception as e:
                ok = False
                results.append(f"❌ {dest_type} ({dest_path}): {e}")

        # Update last backup timestamp
        try:
            from models import db, ConfigGeral
            if cfg:
                cfg.ultimo_backup    = datetime.utcnow()
                cfg.ultimo_backup_ok = ok
                db.session.commit()
        except Exception:
            pass

        msg = f"Backup '{filename}'\n" + "\n".join(results)
        logger.info(msg)
        return ok, msg


def listar_backups(app, cfg=None) -> list[dict]:
    """List all backup files with metadata."""
    with app.app_context():
        if cfg is None:
            from models import ConfigGeral
            cfg = ConfigGeral.query.first()

        local = (cfg.backup_local_path or 'backups').strip() if cfg else 'backups'
        db_path = os.path.join(app.instance_path, 'compras.db')
        if not os.path.isabs(local):
            local = os.path.join(os.path.dirname(db_path), '..', local)
        local = os.path.normpath(local)

        backups = []
        if os.path.isdir(local):
            for fname in sorted(os.listdir(local), reverse=True):
                if fname.startswith('comprasnet_backup_') and fname.endswith('.db'):
                    fpath = os.path.join(local, fname)
                    try:
                        stat = os.stat(fpath)
                        backups.append({
                            'nome':     fname,
                            'caminho':  fpath,
                            'tamanho':  stat.st_size // 1024,
                            'data':     datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M'),
                        })
                    except Exception:
                        pass
        return backups


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _scheduler_loop(app, get_cfg_fn):
    """Background thread that runs daily backup at configured time."""
    logger.info("Backup scheduler iniciado.")
    while not _stop_event.is_set():
        try:
            with app.app_context():
                cfg = get_cfg_fn()
                if cfg and cfg.backup_auto_ativo:
                    hora_str = cfg.backup_hora or '02:00'
                    h, m = map(int, hora_str.split(':'))
                    now = datetime.now()
                    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if target <= now:
                        target += timedelta(days=1)
                    wait_secs = (target - now).total_seconds()

                    # Sleep in small chunks to allow stop
                    slept = 0
                    while slept < wait_secs and not _stop_event.is_set():
                        time.sleep(min(60, wait_secs - slept))
                        slept += 60

                    if not _stop_event.is_set():
                        logger.info("A executar backup automático agendado...")
                        fazer_backup(app, cfg)
                else:
                    time.sleep(300)  # Check every 5 min if backup becomes active
        except Exception as e:
            logger.error(f"Erro no scheduler de backup: {e}")
            time.sleep(60)


def iniciar_scheduler(app):
    """Start the background backup scheduler thread."""
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
