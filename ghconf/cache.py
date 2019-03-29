# -* encoding: utf-8 *-
from typing import Dict, Callable, Any, Optional

_store = {}  # type: Dict[str, Any]
listeners = {}  # type: Dict[str, Callable[[], None]]


def clearcache() -> None:
    global _store
    _store = {}
    for _, listener in listeners.items():
        listener()


def store(key: str, value: Any) -> None:
    global _store
    _store[key] = value


def get(key: str, value: Any, default: Optional[Any] = None) -> Any:
    return _store.get(key, default)


def lazy_get_or_store(key: str, eval: Callable[[], Any]) -> Any:
    if not callable(eval):
        raise ValueError("lazy_get_or_store requires a callable for parameter 'eval'")

    if key in _store:
        return _store[key]
    else:
        value = eval()
        if value is not None:
            _store[key] = value
            return _store[key]
    raise ValueError("No such key '%s'" % key)
