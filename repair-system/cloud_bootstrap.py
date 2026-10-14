"""Prepare operator-provided cloud secret files without exposing their contents.

Only explicit environment file paths are read. SQLite import decisions remain in
database_tools.import_on_start; an existing database is never replaced here.
"""

import base64
import hashlib
import json
import os
import secrets
from contextlib import closing
from pathlib import Path

import database_tools

MAX_CONFIG_BYTES = 65535
MAX_BASE64_BYTES = 16 * 1024 * 1024


def _source(name):
    value = os.environ.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Cloud bootstrap source is unavailable')
    return Path(value)


def _read(path, limit):
    try:
        path = path.resolve(strict=True)
        if not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ValueError
        with path.open('rb') as file:
            raw = file.read(limit + 1)
        if not 0 < len(raw) <= limit:
            raise ValueError
        return raw
    except (OSError, ValueError):
        raise ValueError('Cloud bootstrap source is unavailable or too large') from None


def _directory(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('Cloud bootstrap data directory is invalid')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError('Cloud bootstrap data directory is invalid')
    os.chmod(path, 0o700)
    return path


def _config(raw):
    try:
        values = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(values, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in values.items()):
            raise ValueError
    except (ValueError, UnicodeError, TypeError):
        raise ValueError('Cloud bootstrap private configuration is invalid') from None
    return raw


def _validate_snapshot(path):
    try:
        with closing(database_tools._open_readonly(path)) as connection:
            database_tools._validate(connection)
    except Exception:
        raise ValueError('Cloud bootstrap repair snapshot is invalid') from None


def _atomic_write(destination, raw, validate=None):
    destination = Path(destination)
    if destination.is_symlink() or destination.exists() and not destination.is_file():
        raise ValueError('Cloud bootstrap destination is invalid')
    temp = destination.with_name('.bootstrap-' + secrets.token_hex(8) + '.tmp')
    created = False
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(fd, 'wb') as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temp, 0o600)
        if validate:
            validate(temp)
        os.replace(temp, destination)
    finally:
        if created and temp.exists():
            temp.unlink()


def _prepare_snapshot(data_dir, raw):
    try:
        decoded = base64.b64decode(raw, validate=True)
        if not decoded or base64.b64encode(decoded) != raw:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Cloud bootstrap snapshot encoding is invalid') from None
    digest = hashlib.sha256(decoded).hexdigest()
    marker = data_dir / '.import-completed.json'
    if marker.is_symlink():
        raise ValueError('Cloud bootstrap import marker is invalid')
    if marker.exists():
        try:
            state = json.loads(_read(marker, 4096).decode('utf-8'))
            if not isinstance(state, dict) or state.get('sha256') != digest:
                raise ValueError
        except (ValueError, UnicodeError, TypeError):
            raise ValueError('Cloud bootstrap refuses a different completed import') from None
    import_dir = _directory(data_dir / 'import')
    if import_dir.parent != data_dir:
        raise ValueError('Cloud bootstrap import directory is invalid')
    destination = import_dir / 'repairs.sqlite3'
    if destination.is_symlink():
        raise ValueError('Cloud bootstrap import destination is invalid')
    if destination.exists():
        if hashlib.sha256(_read(destination, MAX_BASE64_BYTES)).hexdigest() != digest:
            raise ValueError('Cloud bootstrap refuses to replace an import snapshot')
        _validate_snapshot(destination)
        os.chmod(destination, 0o600)
    else:
        _atomic_write(destination, decoded, _validate_snapshot)
    return destination


def bootstrap_from_secret_files(data_dir):
    """Prepare optional operator sources; absent source variables read no files.

    Returns non-sensitive boolean flags. Config values are copied atomically;
    snapshots are validated and staged, then the original one-time importer is
    given their path. No network, messages, existing case DB changes or logging.
    """
    try:
        config_source = _source('REPAIR_CONFIG_SOURCE')
        base64_source = _source('REPAIR_IMPORT_BASE64_SOURCE')
        if config_source is None and base64_source is None:
            return {'configPrepared': False, 'snapshotPrepared': False}
        config_raw = _config(_read(config_source, MAX_CONFIG_BYTES)) if config_source is not None else None
        snapshot_raw = _read(base64_source, MAX_BASE64_BYTES) if base64_source is not None else None
        directory = _directory(data_dir)
        snapshot = _prepare_snapshot(directory, snapshot_raw) if snapshot_raw is not None else None
        if config_raw is not None:
            _atomic_write(directory / 'line-config.json', config_raw)
        if snapshot is not None:
            os.environ['REPAIR_IMPORT_SNAPSHOT'] = str(snapshot)
        return {'configPrepared': config_raw is not None, 'snapshotPrepared': snapshot is not None}
    except Exception:
        raise ValueError('Cloud bootstrap failed; operator review required') from None
