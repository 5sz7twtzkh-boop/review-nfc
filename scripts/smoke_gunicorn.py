"""Start the actual production command on Linux and probe it over HTTP."""
import os
import secrets
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory() as directory:
        env = os.environ.copy()
        env.update(SECRET_KEY=secrets.token_hex(32), ADMIN_PASSWORD=secrets.token_urlsafe(24),
                   PORT='8765', DATABASE_URL='sqlite:///' + (Path(directory) / 'smoke.db').as_posix())
        process = subprocess.Popen(['gunicorn', 'app:app'], env=env)
        try:
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError('Gunicorn exited before readiness')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=2) as response:
                        assert response.status == 200
                        break
                except OSError:
                    time.sleep(.25)
            else:
                raise RuntimeError('Gunicorn did not become ready')
            for path in ['/', '/r/001', '/health', '/admin/login']:
                with urllib.request.urlopen('http://127.0.0.1:8765' + path, timeout=5) as response:
                    assert response.status == 200, path
                    print(path, response.status)
        finally:
            process.terminate()
            process.wait(timeout=15)


if __name__ == '__main__':
    main()
