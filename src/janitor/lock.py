import os
from pathlib import Path


class LockError(Exception):
    pass


def acquire_lock(path: str) -> None:
    lock = Path(path)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        # Check if the PID in the lock file is still alive
        try:
            pid = int(lock.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale lock — remove and retry
            lock.unlink(missing_ok=True)
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        raise LockError(f"Janitor is already running (pid: {pid}, lock: {path})")


def release_lock(path: str) -> None:
    lock = Path(path)
    if lock.exists():
        lock.unlink()
