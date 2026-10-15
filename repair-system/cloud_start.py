"""Launch one cloud application process; never echo environment secrets."""

import os
import sys
import time
from pathlib import Path


def prepare_environment():
    os.environ['REPAIR_DEPLOYMENT'] = 'cloud'
    os.environ['REPAIR_MODE'] = 'live'
    os.environ['REPAIR_LOCAL_SETUP'] = '0'
    os.environ.setdefault('REPAIR_DATA_DIR', '/var/data/repair-system')
    os.environ.setdefault('TZ', 'Asia/Taipei')
    os.environ['WEB_CONCURRENCY'] = '1'
    # Render's Python defaults include preload and access logs. OAuth codes and
    # entry tickets must not be recorded, and background threads start in-worker.
    os.environ.pop('GUNICORN_CMD_ARGS', None)
    if hasattr(time, 'tzset'):
        time.tzset()
    try:
        port = int(os.environ.get('PORT', '10000'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit('Invalid cloud port configuration') from None
    return port


def main():
    try:
        port = prepare_environment()
        from cloud_bootstrap import bootstrap_from_secret_files
        from database_tools import import_on_start
        data_dir = Path(os.environ['REPAIR_DATA_DIR'])
        bootstrap_from_secret_files(data_dir)
        import_on_start(data_dir)
        # Explicit operator-only maintenance runs before any request or worker.
        # With no reviewed approval marker this performs no database operations.
        from test_case_cleanup import run_on_start
        run_on_start(data_dir)
    except Exception:
        raise SystemExit('Cloud setup or data import failed; existing data was preserved. Operator review required.') from None
    args = [sys.executable, '-m', 'gunicorn',
            '--bind', '0.0.0.0:' + str(port),
            '--workers', '1', '--worker-class', 'gthread', '--threads', '8',
            '--timeout', '60', '--graceful-timeout', '30', '--keep-alive', '5',
            '--limit-request-line', '4094', '--limit-request-fields', '100',
            '--limit-request-field_size', '8190', '--error-logfile', '-',
            '--log-level', 'warning', '--forwarded-allow-ips', '*',
            'production:application']
    try:
        os.execv(sys.executable, args)
    except Exception:
        raise SystemExit('Cloud application could not be started; operator review required.') from None


if __name__ == '__main__':
    main()
