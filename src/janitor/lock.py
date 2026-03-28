import os
from pathlib import Path


class LockError(Exception):
    pass


def acquire_lock(path: str) -> None:
    lock = Path(path)
    if lock.exists():
        raise LockError(f"Janitor is already running (lock: {path})")
    lock.write_text(str(os.getpid()))


def release_lock(path: str) -> None:
    lock = Path(path)
    if lock.exists():
        lock.unlink()
