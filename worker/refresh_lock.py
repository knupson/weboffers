"""Exclusión por archivo compartida entre la cadena y el ciclo horario."""
from functools import wraps
from pathlib import Path
import os
import time


def locked_refresh(refresh):
    @wraps(refresh)
    def locked(catalog, prices_path, *args, **kwargs):
        lock_path = Path(prices_path).with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock:
            if os.name == "posix":
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)
            else:
                # Permite correr las pruebas también en Windows.
                import msvcrt
                lock.write(b"\0")
                lock.flush()
                lock.seek(0)
                while True:
                    try:
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.1)
            try:
                return refresh(catalog, prices_path, *args, **kwargs)
            finally:
                if os.name == "posix":
                    fcntl.flock(lock, fcntl.LOCK_UN)
                else:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    return locked
