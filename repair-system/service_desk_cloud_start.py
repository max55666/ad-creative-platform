"""Single-process, non-preloaded launch for the isolated cloud workbench."""
import os
import sys
import time


def prepare_environment():
    os.environ['WEB_CONCURRENCY'] = '1'
    os.environ['TZ'] = 'Asia/Taipei'
    os.environ.pop('GUNICORN_CMD_ARGS', None)
    if hasattr(time, 'tzset'):
        time.tzset()
    try:
        port = int(os.environ.get('PORT', '10000'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit('Invalid internal cloud port') from None
    return port


def main():
    port = prepare_environment()
    args = [sys.executable, '-m', 'gunicorn', '--bind', '0.0.0.0:' + str(port),
        '--workers', '1', '--worker-class', 'gthread', '--threads', '4',
        '--timeout', '90', '--graceful-timeout', '30', '--keep-alive', '5',
        '--limit-request-line', '4094', '--limit-request-fields', '100',
        '--limit-request-field_size', '8190', '--error-logfile', '-',
        '--log-level', 'warning', '--forwarded-allow-ips', '*',
        'service_desk_cloud:application']
    try:
        os.execv(sys.executable, args)
    except Exception:
        raise SystemExit('Independent cloud workbench could not be started') from None


if __name__ == '__main__':
    main()
