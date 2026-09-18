"""Serialize publication/deletion against readers in the single-process local service."""

from threading import RLock

storage_lock = RLock()


def synchronized(function):
    from functools import wraps

    @wraps(function)
    def wrapped(*args, **kwargs):
        with storage_lock:
            return function(*args, **kwargs)

    return wrapped
