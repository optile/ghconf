from typing import Any, Callable, Dict


class Event:
    def __init__(self) -> None:
        self.listeners = {}  # type: Dict[int, Callable[[Any], None]]
        self.id = 0

    def fire(self, *args: Any, **kwargs: Any):
        for listener in self.listeners.values():
            listener(*args, **kwargs)

    def subscribe(self, listener: Callable[[Any], None]) -> int:
        self.listeners[self.id] = listener
        self.id = self.id + 1
        return self.id

    def unsubscribe(self, id_: int):
        if id_ in self.listeners:
            del self.listeners[id_]


event_config_complete = Event()
event_repolist_complete = Event()
