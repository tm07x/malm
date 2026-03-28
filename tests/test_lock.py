import pytest
from janitor.lock import acquire_lock, release_lock, LockError


def test_acquire_and_release(tmp_path):
    lock_path = tmp_path / "janitor.lock"
    acquire_lock(str(lock_path))
    assert lock_path.exists()
    release_lock(str(lock_path))
    assert not lock_path.exists()


def test_double_acquire_fails(tmp_path):
    lock_path = tmp_path / "janitor.lock"
    acquire_lock(str(lock_path))
    with pytest.raises(LockError, match="already running"):
        acquire_lock(str(lock_path))
    release_lock(str(lock_path))


def test_release_nonexistent_is_safe(tmp_path):
    lock_path = tmp_path / "janitor.lock"
    release_lock(str(lock_path))  # should not raise
