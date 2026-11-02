"""Cross-process lock so only one command drives the phone windows / shared cache files at a time.

Uses an OS-level file lock, so it is released automatically if the holder crashes (no stale locks).
"""

import os
import tempfile
import time

DEFAULT_LOCK_PATH = os.path.join(tempfile.gettempdir(), "geelark-cloud-phone.lock")
DEFAULT_TIMEOUT = 60.0

try:
    import msvcrt  # Windows
except ImportError:
    msvcrt = None
    try:
        import fcntl  # POSIX
    except ImportError:
        fcntl = None


class LockTimeout(RuntimeError):
    """Another GeeLark command held the device lock for longer than the timeout."""


def _timeout_from_env():
    try:
        return float(os.environ.get("GEELARK_LOCK_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


class DeviceLock:
    def __init__(self, path=None, timeout=None):
        self.path = path or os.environ.get("GEELARK_LOCK_PATH") or DEFAULT_LOCK_PATH
        self.timeout = _timeout_from_env() if timeout is None else timeout
        self._fh = None

    def _try_lock(self):
        if msvcrt:
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        elif fcntl:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def acquire(self):
        if not msvcrt and not fcntl:
            return self  # no locking primitive available; degrade to no-op
        self._fh = open(self.path, "a+")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._try_lock()
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self._fh.close()
                    self._fh = None
                    raise LockTimeout(
                        f"Another GeeLark command is still running (waited {self.timeout:.0f}s). "
                        "Retry shortly or raise GEELARK_LOCK_TIMEOUT."
                    )
                time.sleep(0.1)

    def release(self):
        if not self._fh:
            return
        try:
            if msvcrt:
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
