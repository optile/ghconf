from typing import Any, Callable, Set


class Event:
    def __init__(self) -> None:
        self.listeners = {}  # type: Dict[Callable[[Any], None]]
        self.id = 0

    def fire(self, *args: Any, **kwargs: Any):
        for l in self.listeners:
            l(*args, **kwargs)

    def subscribe(self, listener: Callable[[Any], None]) -> int:
        self.listeners[self.id] = listener
        self.id = self.id + 1
        return self.id

    def unsubscribe(self, id):
        if id in self.listeners:
            del self.listeners[id]


event_config_complete = Event()
event_repolist_complete = Event()
