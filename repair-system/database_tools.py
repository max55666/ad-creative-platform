"""Consistent SQLite backups and an offline, one-time cloud data import.

These operations are local to the operator's filesystem. They never upload data
or include customer fields in output. Live case files are excluded from packages.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

BACKUP_NAME = re.compile(r'repairs-\d{8}T\d{6}-[a-f0-9]{8}\.sqlite3\Z')


def _open_readonly(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Database source is unavailable')
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)


def _validate(connection):
    if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise ValueError('Database integrity check failed')
    columns = {row[1] for row in connection.execute('PRAGMA table_info(cases)')}
    if not {'id', 'user_id', 'request_id', 'data', 'status', 'created', 'history'} <= columns:
        raise ValueError('Not a repair database')


def _snapshot(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = destination.with_name('.snapshot-' + secrets.token_hex(8) + '.tmp')
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with closing(_open_readonly(source)) as src:
            _validate(src)
            with closing(sqlite3.connect(temp)) as dst:
                src.backup(dst)
                _validate(dst)
        os.replace(temp, destination)
    finally:
        if temp.exists():
            temp.unlink()


def backup_database(source, directory, keep=14):
    if not 1 <= keep <= 365:
        raise ValueError('Invalid backup retention')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = 'repairs-' + time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + '-' + secrets.token_hex(4) + '.sqlite3'
    destination = directory / name
    _snapshot(source, destination)
    snapshots = sorted((p for p in directory.iterdir()
                        if p.is_file() and not p.is_symlink() and BACKUP_NAME.fullmatch(p.name)),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    for old in snapshots[keep:]:
        if old.resolve().parent == directory:
            old.unlink()
    return destination


def import_on_start(data_dir):
    """Import only before starting the application, refusing existing records.

    Upload the snapshot into data_dir/import first, then set the environment
    variable and restart. A completed import is never re-applied on restart.
    """
    source_value = os.environ.get('REPAIR_IMPORT_SNAPSHOT', '')
    if not source_value:
        return False
    data_dir = Path(data_dir).resolve()
    source = Path(source_value)
    import_dir = (data_dir / 'import').resolve()
    if source.is_symlink() or not source.is_absolute() or source.resolve().parent != import_dir:
        raise ValueError('Import source must be a regular file in the import directory')
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError('Import snapshot is unavailable')
    digest_state = hashlib.sha256()
    with source.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest_state.update(chunk)
    digest = digest_state.hexdigest()
    marker = data_dir / '.import-completed.json'
    if marker.exists():
        if json.loads(marker.read_text(encoding='utf-8')).get('sha256') == digest:
            return False
        raise ValueError('A different snapshot was already imported')
    target = data_dir / 'repairs.db'
    if target.exists():
        with closing(_open_readonly(target)) as current:
            tables = {row[0] for row in current.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('cases', 'line_receipts', 'line_outbox', 'line_webhook_events', 'cloud_outbox'):
                if table in tables and current.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]:
                    raise ValueError('Import refused: the destination already contains records')
    _snapshot(source, target)
    with os.fdopen(os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as f:
        json.dump({'sha256': digest, 'completedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, f)
    return True


_BACKUP_STARTED = False


def start_backup_worker(database):
    global _BACKUP_STARTED
    if _BACKUP_STARTED or os.environ.get('REPAIR_DEPLOYMENT') != 'cloud':
        return
    _BACKUP_STARTED = True
    directory = Path(database).parent / 'backups'

    def run():
        while True:
            try:
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                last = max((p.stat().st_mtime for p in directory.iterdir()
                            if p.is_file() and not p.is_symlink() and BACKUP_NAME.fullmatch(p.name)), default=0)
                if time.time() - last >= 86400:
                    backup_database(database, directory)
            except Exception:
                # Do not log filenames, customer content, or exception arguments.
                print('Database backup failed; operator review required.', flush=True)
            time.sleep(3600)

    threading.Thread(target=run, name='database-backup', daemon=True).start()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a local consistent repair database backup')
    parser.add_argument('source', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        backup_database(args.source, args.directory)
    except Exception:
        raise SystemExit('Backup failed. Check the database and directory permissions.') from None
    print('Consistent database backup created. No data was uploaded.')
