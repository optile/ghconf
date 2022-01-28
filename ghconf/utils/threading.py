import threading
from typing import Optional


class KillSwitchReceived(Exception):
    pass


class ThreadEx(threading.Thread):
    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs=None, *, daemon=None) -> None:
        super().__init__(group, target, name, args, kwargs, daemon=daemon)
        self.exc = None  # type: Optional[BaseException]

    def run(self) -> None:
        try:
            super().run()
        except KillSwitchReceived:
            pass
        except BaseException as e:
            self.exc = e

    def has_exception(self) -> bool:
        return self.exc is not None

    def join(self, timeout: Optional[float] = None, raise_exception: bool = True) -> None:
        super().join(timeout)
        if raise_exception and self.exc:
            raise self.exc


