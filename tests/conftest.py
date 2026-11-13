"""Test bootstrap.

systempi targets Linux and imports ``fcntl``, ``pty``, ``termios`` and ``tty``
at module scope. The repository collector under test only needs ``fcntl.flock``
for its private lockfile, so on a non-POSIX host we provide minimal,
in-process equivalents. This keeps the collector's tests runnable on a
developer workstation without changing any production code path.
"""

import os
import sys
import types


if os.name != "posix":  # pragma: no cover - exercised only on Windows
    # In-process advisory lock keyed by file identity. Two handles to the same
    # file in one process contend exactly like two fds would under flock(2).
    _held = {}

    def _file_key(file_descriptor):
        stat_result = os.fstat(file_descriptor)
        return (stat_result.st_dev, stat_result.st_ino)

    def _flock(file_descriptor, operation):
        key = _file_key(file_descriptor)
        owner = _held.get(key)
        if operation & _fcntl.LOCK_UN:
            if owner == file_descriptor:
                del _held[key]
            return None
        if operation & _fcntl.LOCK_EX:
            if owner is not None and owner != file_descriptor:
                if operation & _fcntl.LOCK_NB:
                    raise BlockingIOError("resource temporarily unavailable")
                raise RuntimeError("blocking flock is not supported by this shim")
            _held[key] = file_descriptor
        return None

    _fcntl = types.ModuleType("fcntl")
    _fcntl.LOCK_EX = 2
    _fcntl.LOCK_NB = 4
    _fcntl.LOCK_UN = 8
    _fcntl.flock = _flock
    sys.modules.setdefault("fcntl", _fcntl)

    for name in ("pty", "termios", "tty"):
        sys.modules.setdefault(name, types.ModuleType(name))
else:
    import fcntl as _fcntl  # noqa: F401
